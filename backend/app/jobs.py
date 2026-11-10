"""Background jobs: audits, sandboxed test runs, workspace cleanup.

Jobs are executed by RQ workers (`python -m app.worker`). With
AUDITOR_INLINE_JOBS=true they run in-process (tests, single-process demos).
"""

from __future__ import annotations

import logging
import threading
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.analysis.pipeline import run_analysis
from app.core.config import get_settings
from app.core.database import get_sessionmaker
from app.ingestion import github
from app.ingestion.workspace import (
    IngestionError,
    create_workspace,
    delete_workspace,
    expiry,
    source_dir,
    workspace_root,
)
from app.ingestion.zip_extract import extract_zip
from app.llm.redact import redact
from app.models import Audit, Finding, Project

log = logging.getLogger(__name__)
UPLOAD_NAME = "upload.zip"
JOB_TIMEOUT_SECONDS = 3600
# An audit still queued/running this long after it should have ended has lost its worker.
STALE_AFTER = timedelta(seconds=JOB_TIMEOUT_SECONDS + 15 * 60)


def enqueue(func_name: str, *args: str) -> None:
    settings = get_settings()
    if settings.inline_jobs:
        func = globals()[func_name]
        if settings.env == "test":
            func(*args)
        else:
            threading.Thread(target=func, args=args, daemon=True).start()
        return
    from redis import Redis
    from rq import Queue

    Queue("audits", connection=Redis.from_url(settings.redis_url)).enqueue(
        f"app.jobs.{func_name}", *args, job_timeout=JOB_TIMEOUT_SECONDS, result_ttl=3600,
        failure_ttl=86400)


def upload_path(audit_id: str) -> Path:
    """Where the API stores an uploaded ZIP until the worker extracts it."""
    d = workspace_root() / f"{audit_id}.upload"
    d.mkdir(mode=0o700, exist_ok=True)
    return d / UPLOAD_NAME


def run_audit(audit_id: str) -> None:
    settings = get_settings()
    Session = get_sessionmaker()
    with Session() as db:
        audit = db.get(Audit, audit_id)
        if audit is None:
            return
        project = db.get(Project, audit.project_id)
        audit.status, audit.stage, audit.started_at = "running", "ingestion", datetime.now(UTC)
        db.commit()
        purge_expired_workspaces()

        def on_stage(stage: str) -> None:
            audit.stage = stage
            db.commit()

        try:
            ws = create_workspace(audit_id)
            src = source_dir(ws)
            if project.source_type == "github":
                audit.commit_sha = github.clone(project.source_url, project.default_branch, src)
            else:
                up = upload_path(audit_id)
                try:
                    extract_zip(up, src)
                finally:
                    up.unlink(missing_ok=True)
                    up.parent.rmdir()
            audit.workspace_path, audit.workspace_expires_at = str(ws), expiry()
            db.commit()

            result = run_analysis(src, settings, on_stage=on_stage)
            for f in result.findings:
                # SEC-03: analyzers copy source lines into evidence; never store a secret verbatim,
                # whichever rule found it. Fingerprints were computed from the raw text already.
                db.add(Finding(audit_id=audit.id, **{**f, "evidence": redact(f["evidence"] or "")}))
            summary = result.summary
            summary["comparison"] = _compare(db, audit, {f["fingerprint"] for f in result.findings})
            audit.summary = summary
            audit.status, audit.stage = "completed", None
        except IngestionError as exc:
            audit.status, audit.error = "failed", str(exc)
            delete_workspace(audit.workspace_path or workspace_root() / audit_id)
            audit.workspace_path = None
        except Exception as exc:  # report, never leak internals beyond the type
            log.error("audit %s failed: %s", audit_id, traceback.format_exc())
            _record_failure(db, audit_id, f"Internal analysis error ({type(exc).__name__})")
            return
        audit.finished_at = datetime.now(UTC)
        try:
            db.commit()
        except Exception as exc:
            log.error("audit %s could not be saved: %s", audit_id, traceback.format_exc())
            _record_failure(db, audit_id, f"Internal analysis error ({type(exc).__name__})")


def _record_failure(db, audit_id: str, message: str) -> None:
    """Mark an audit failed even when `db` is unusable (e.g. its connection broke mid-job).

    Partial findings from the failed run are discarded by the rollback.
    """
    try:
        db.rollback()
    except Exception:  # the original session may be beyond repair; fall through to a fresh one
        log.warning("rollback failed for audit %s", audit_id, exc_info=True)
    try:
        with get_sessionmaker()() as fresh:
            audit = fresh.get(Audit, audit_id)
            if audit is None or audit.status == "completed":
                return
            audit.status, audit.error, audit.stage = "failed", message, None
            audit.finished_at = datetime.now(UTC)
            fresh.commit()
    except Exception:
        log.error("could not record failure of audit %s", audit_id, exc_info=True)


def fail_stale_audits(now: datetime | None = None) -> int:
    """Fail audits whose worker died (OOM, restart, RQ timeout) so projects are not locked forever."""
    now = now or datetime.now(UTC)
    cutoff = now - STALE_AFTER
    n = 0
    with get_sessionmaker()() as db:
        rows = db.scalars(select(Audit).where(Audit.status.in_(("queued", "running")))).all()
        for a in rows:
            ref = a.started_at or a.created_at
            if ref is not None and (ref if ref.tzinfo else ref.replace(tzinfo=UTC)) < cutoff:
                a.status, a.stage = "failed", None
                a.error = "The analysis worker stopped before this audit finished. Please re-run it."
                a.finished_at = now
                n += 1
        db.commit()
    return n


def _compare(db, audit: Audit, current: set[str]) -> dict | None:
    if not audit.previous_audit_id:
        return None
    prev = db.scalars(select(Finding).where(Finding.audit_id == audit.previous_audit_id)).all()
    before = {f.fingerprint: f for f in prev}
    resolved = [f for fp, f in before.items() if fp not in current]
    prev_audit = db.get(Audit, audit.previous_audit_id)
    prev_score = ((prev_audit.summary or {}).get("scores") or {}).get("overall") if prev_audit else None
    return {
        "previous_audit_id": audit.previous_audit_id,
        "previous_score": prev_score,
        "resolved": len(resolved), "new": len(current - set(before)),
        "persisting": len(current & set(before)),
        "resolved_findings": [{"title": f.title, "severity": f.severity, "file": f.file,
                               "category": f.category} for f in resolved[:50]],
    }


def run_tests(audit_id: str) -> None:
    from app.sandbox.docker_tests import run_test_suite

    Session = get_sessionmaker()
    with Session() as db:
        audit = db.get(Audit, audit_id)
        if audit is None or not audit.workspace_path:
            return
        summary = dict(audit.summary)
        testing = dict(summary.get("testing", {}))
        testing["run"] = {"status": "running", "started_at": datetime.now(UTC).isoformat()}
        summary["testing"] = testing
        audit.summary = summary
        db.commit()
        result = run_test_suite(Path(audit.workspace_path), summary.get("stack", {}))
        summary = dict(audit.summary)
        testing = dict(summary.get("testing", {}))
        testing["run"] = result
        summary["testing"] = testing
        audit.summary = summary
        db.commit()


def purge_expired_workspaces() -> int:
    """Delete repository copies past their TTL. Findings/metrics are kept.

    Also sweeps orphans (SEC-08): workspace or ``.upload`` folders older than the TTL that no
    audit references, e.g. left behind by a crashed or killed job before ``workspace_path`` was
    saved. Folders of queued/running audits and of unexpired audits are never touched.
    """
    Session = get_sessionmaker()
    n = 0
    now = datetime.now(UTC)
    with Session() as db:
        rows = db.scalars(select(Audit).where(Audit.workspace_path.is_not(None),
                                              Audit.workspace_expires_at < now)).all()
        for a in rows:
            delete_workspace(a.workspace_path)
            a.workspace_path = None
            n += 1
        db.commit()
        referenced = {Path(p).name for p in db.scalars(
            select(Audit.workspace_path).where(Audit.workspace_path.is_not(None)))}
        active = set(db.scalars(select(Audit.id).where(Audit.status.in_(("queued", "running")))))
    cutoff = (now - timedelta(hours=get_settings().workspace_ttl_hours)).timestamp()
    for entry in workspace_root().iterdir():
        if (not entry.is_dir() or entry.is_symlink() or entry.name in referenced
                or entry.name.removesuffix(".upload") in active or entry.stat().st_mtime >= cutoff):
            continue
        delete_workspace(entry)
        n += 1
    return n
