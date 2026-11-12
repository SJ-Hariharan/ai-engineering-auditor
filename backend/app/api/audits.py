"""Audit results: summary, findings, file viewer, test runs and report export."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.inventory import LANG_BY_EXT
from app.analysis.scoring import priority
from app.api.deps import current_user, get_audit, workspace_available
from app.api.projects import audit_out
from app.core.config import get_settings
from app.core.database import get_db
from app.ingestion.workspace import safe_join, source_dir
from app.jobs import enqueue
from app.llm.redact import redact
from app.models import Finding, FixProposal, User
from app.remediation.fixers import FIXERS
from app.schemas import SEVERITY_ORDER, AuditOut, AuditStatusOut, FileContent, FindingOut

router = APIRouter(prefix="/api/audits", tags=["audits"])
MAX_VIEW_BYTES = 400_000


def finding_out(f: Finding, fixed_ids: set[str] | None = None) -> FindingOut:
    out = FindingOut.model_validate(f)
    # Evidence is redacted before storage; redacting again on read also covers audits stored before
    # that change (SEC-03). Idempotent for already-redacted text.
    out.evidence = redact(out.evidence or "")
    out.has_fix = bool(fixed_ids and f.id in fixed_ids)
    out.fixable = f.rule_id in FIXERS and bool(f.line) and f.tool != "gitleaks"
    return out


@router.get("/{audit_id}", response_model=AuditOut)
def get_audit_detail(audit_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return audit_out(get_audit(db, user, audit_id))


@router.get("/{audit_id}/status", response_model=AuditStatusOut)
def get_audit_status(audit_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """What the report page polls while an audit or a test run is in progress (E-03)."""
    a = get_audit(db, user, audit_id)
    run = ((a.summary or {}).get("testing") or {}).get("run")
    return AuditStatusOut(id=a.id, status=a.status, stage=a.stage, error=a.error,
                          finished_at=a.finished_at, test_run=run)


@router.get("/{audit_id}/findings", response_model=list[FindingOut])
def list_findings(
    audit_id: str,
    category: str | None = Query(default=None, max_length=32),
    severity: str | None = Query(default=None, max_length=16),
    kind: str | None = Query(default=None, max_length=16),
    file: str | None = Query(default=None, max_length=1000),
    sort: str = Query(default="priority", pattern="^(priority|severity|file)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    audit = get_audit(db, user, audit_id)
    q = select(Finding).where(Finding.audit_id == audit.id)
    if category:
        q = q.where(Finding.category == category)
    if severity:
        q = q.where(Finding.severity == severity)
    if kind:
        q = q.where(Finding.kind == kind)
    if file:
        q = q.where(Finding.file == file)
    rows = list(db.scalars(q).all())
    if sort == "priority":
        rows.sort(key=lambda f: -priority({"severity": f.severity, "confidence": f.confidence,
                                           "kind": f.kind, "category": f.category}))
    elif sort == "severity":
        rows.sort(key=lambda f: SEVERITY_ORDER.get(f.severity, 9))
    else:
        rows.sort(key=lambda f: (f.file or "", f.line or 0))
    fixed = set(db.scalars(select(FixProposal.finding_id).where(FixProposal.audit_id == audit.id)))
    return [finding_out(f, fixed) for f in rows]


@router.get("/{audit_id}/files/{path:path}", response_model=FileContent)
def get_file(audit_id: str, path: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    audit = get_audit(db, user, audit_id)
    if not workspace_available(audit):
        raise HTTPException(status.HTTP_410_GONE,
                            "Source files for this audit have been deleted (retention limit). "
                            "Re-run the audit to view code.")
    root = source_dir(Path(audit.workspace_path))
    try:
        target = safe_join(root, path)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid path") from None
    if not target.is_file() or target.is_symlink():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    raw = target.read_bytes()[:MAX_VIEW_BYTES]
    if b"\x00" in raw[:8000]:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Binary file")
    rel = target.relative_to(root.resolve()).as_posix()
    findings = db.scalars(select(Finding).where(Finding.audit_id == audit.id, Finding.file == rel)).all()
    content = raw.decode("utf-8", "replace")
    if any(f.tool == "gitleaks" for f in findings):
        content = _mask_secrets(content, [f for f in findings if f.tool == "gitleaks"])
    # SEC-03: also hide secrets other scanners would not report. Line by line, so line numbers (and
    # the finding markers on them) stay aligned with the file.
    content = "".join(redact(line) for line in content.splitlines(keepends=True))
    return FileContent(path=rel, language=LANG_BY_EXT.get(target.suffix.lower()), content=content,
                       truncated=target.stat().st_size > MAX_VIEW_BYTES,
                       symbols=(audit.summary.get("symbols") or {}).get(rel, []),
                       findings=[finding_out(f) for f in findings])


def _mask_secrets(content: str, leaks: list[Finding]) -> str:
    """Never display detected secrets, even in the file viewer."""
    lines = content.splitlines(keepends=True)
    for f in leaks:
        if f.line and 0 < f.line <= len(lines):
            lines[f.line - 1] = f.evidence + "\n"
    return "".join(lines)


@router.post("/{audit_id}/tests/run", status_code=202)
def run_tests(audit_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    audit = get_audit(db, user, audit_id)
    if audit.status != "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Audit has not completed")
    if not workspace_available(audit):
        raise HTTPException(status.HTTP_410_GONE, "Source files have expired; re-run the audit")
    if not get_settings().sandbox_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sandboxed test execution is disabled")
    run = ((audit.summary or {}).get("testing") or {}).get("run") or {}
    if run.get("status") == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "Tests are already running")
    enqueue("run_tests", audit.id)
    return {"status": "queued"}


def _na(score: float | None) -> str:
    return "N/A" if score is None else str(score)


@router.get("/{audit_id}/report.md", response_class=PlainTextResponse)
def export_markdown(audit_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    audit = get_audit(db, user, audit_id)
    if audit.status != "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Audit has not completed")
    s = audit.summary
    rows = list(db.scalars(select(Finding).where(Finding.audit_id == audit.id)))
    rows.sort(key=lambda f: -priority({"severity": f.severity, "confidence": f.confidence,
                                       "kind": f.kind, "category": f.category}))
    sc = s["scores"]
    out = [f"# Engineering report — {audit.project.name}", "",
           f"Commit: `{audit.commit_sha or 'uploaded archive'}` · Generated: {audit.finished_at:%Y-%m-%d %H:%M} UTC", "",
           f"**Overall: {_na(sc['overall'])} ({sc['grade']})** — a prioritisation aid, not a security certification.", ""]
    out += [f"> **Score capped at {cap['max']}:** {cap['note']}" for cap in sc.get("caps") or []]
    out += ["", "| Category | Score | Grade |", "|---|---|---|"]
    out += [f"| {c['label']} | {_na(c['score'])}{' (incomplete)' if c.get('status') == 'incomplete' else ''} "
            f"| {c['grade']} |" for c in sc["categories"].values()]
    out += [f"- {c['label']}: {c['note']}" for c in sc["categories"].values() if c.get("note")]
    sup = s.get("suppressions") or {}
    if sup.get("total"):
        files = ", ".join(f["file"] for f in sup.get("files", []))
        inline = ", ".join(f"{n} × {m}" for m, n in (sup.get("inline") or {}).items())
        out += ["", f"> **Scanner suppressions found and ignored:** {'; '.join(x for x in (files, inline) if x)}. "
                "Findings are reported regardless of suppression directives in the repository."]
    out += ["", "## Overview", "", *s["overview"]["paragraphs"], "", "## Findings (priority order)", ""]
    for f in rows:
        loc = f"{f.file}:{f.line}" if f.line else (f.file or "repository")
        out += [f"### [{f.severity.upper()}] {f.title}",
                f"*{f.category} · {f.kind} · confidence {f.confidence} · {f.tool}/{f.rule_id}* — `{loc}`", "",
                f"**Evidence**\n```\n{redact(f.evidence or '')}\n```", f"**Why it matters:** {f.impact}", "",
                f"**Explanation:** {f.explanation}", "", f"**Recommended fix:** {f.remediation}", ""]
    out += ["## Methodology", "", sc["methodology"]["summary"], "", "**Limitations**", ""]
    out += [f"- {lim}" for lim in sc["methodology"]["limitations"]]
    return "\n".join(out)
