"""Job lifecycle regressions found in the release-readiness audit (REL-01, REL-02)."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app import jobs
from app.core.database import get_engine, get_sessionmaker
from app.models import Audit, Project, User
from tests.conftest import register


def _make_audit(status="running", started_ago=timedelta(0)) -> str:
    with get_sessionmaker()() as db:
        user = User(email=f"u{os.urandom(3).hex()}@example.com", password_hash="x")
        db.add(user)
        db.flush()
        project = Project(owner_id=user.id, name="p", source_type="zip")
        db.add(project)
        db.flush()
        started = datetime.now(UTC) - started_ago
        audit = Audit(project_id=project.id, status=status, started_at=started, created_at=started)
        db.add(audit)
        db.commit()
        return audit.id


def _audit(audit_id: str) -> Audit:
    with get_sessionmaker()() as db:
        return db.get(Audit, audit_id)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs os.fork")
def test_forked_child_does_not_reuse_parent_connections():
    """REL-01: an RQ work-horse (forked child) must get a fresh connection pool."""
    engine = get_engine()
    with engine.connect():
        pass  # leave one connection checked in to the parent's pool
    assert engine.pool.checkedin() >= 1
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # child
        os.close(read_fd)
        os.write(write_fd, str(get_engine().pool.checkedin()).encode())
        os._exit(0)
    os.close(write_fd)
    child_checked_in = int(os.read(read_fd, 16).decode())
    os.waitpid(pid, 0)
    assert child_checked_in == 0, "child inherited the parent's pooled connections"
    assert engine.pool.checkedin() >= 1, "parent's connections must be left alone"


def test_failure_is_recorded_even_if_session_is_broken():
    """REL-02: when the job's own session can no longer commit, the failure still lands."""
    audit_id = _make_audit()

    class BrokenSession:
        def rollback(self):
            raise RuntimeError("connection is gone")

    jobs._record_failure(BrokenSession(), audit_id, "Internal analysis error (X)")
    a = _audit(audit_id)
    assert a.status == "failed" and a.error == "Internal analysis error (X)" and a.finished_at


def test_analysis_crash_marks_audit_failed(monkeypatch, client, vuln_zip):
    def boom(*args, **kwargs):
        raise RuntimeError("analyzer crashed")

    monkeypatch.setattr(jobs, "run_analysis", boom)
    register(client)
    project = client.post("/api/projects/upload", files={"file": ("v.zip", vuln_zip)}).json()
    audit = client.get(f"/api/audits/{project['audits'][0]['id']}").json()
    assert audit["status"] == "failed"
    assert audit["error"] == "Internal analysis error (RuntimeError)"


def test_stale_audits_are_failed_but_recent_ones_are_not():
    old = _make_audit("running", started_ago=jobs.STALE_AFTER + timedelta(minutes=1))
    recent = _make_audit("running", started_ago=timedelta(minutes=5))
    assert jobs.fail_stale_audits() == 1
    assert _audit(old).status == "failed"
    assert _audit(recent).status == "running"


def test_stale_running_audit_does_not_block_rerun(client, vuln_zip):
    register(client)
    project = client.post("/api/projects/upload", files={"file": ("v.zip", vuln_zip)}).json()
    first = project["audits"][0]["id"]
    with get_sessionmaker()() as db:  # simulate a worker that died mid-audit hours ago
        a = db.get(Audit, first)
        a.status, a.started_at = "running", datetime.now(UTC) - jobs.STALE_AFTER - timedelta(hours=1)
        db.commit()
    r = client.post(f"/api/projects/{project['id']}/audits", files={"file": ("v.zip", vuln_zip)})
    assert r.status_code == 201, r.text
    assert client.get(f"/api/audits/{first}").json()["status"] == "failed"


def test_recent_running_audit_still_blocks_rerun(client, vuln_zip):
    register(client)
    project = client.post("/api/projects/upload", files={"file": ("v.zip", vuln_zip)}).json()
    with get_sessionmaker()() as db:
        a = db.get(Audit, project["audits"][0]["id"])
        a.status, a.started_at = "running", datetime.now(UTC)
        db.commit()
    r = client.post(f"/api/projects/{project['id']}/audits", files={"file": ("v.zip", vuln_zip)})
    assert r.status_code == 409


def test_purge_sweeps_old_orphans_but_keeps_live_workspaces():
    """SEC-08: source copies no audit references must not outlive the TTL."""
    root = jobs.workspace_root()
    old = (datetime.now(UTC) - timedelta(hours=jobs.get_settings().workspace_ttl_hours + 1)).timestamp()

    def folder(name: str, aged: bool) -> Path:
        p = root / name
        (p / "src").mkdir(parents=True, exist_ok=True)
        (p / "src" / "secret.py").write_text("x = 1\n")
        if aged:
            os.utime(p, (old, old))
        return p

    orphan = folder("crashed-job", aged=True)
    orphan_upload = folder("crashed-job.upload", aged=True)
    recent_orphan = folder("just-created", aged=False)
    running = _make_audit("running")
    running_upload = folder(f"{running}.upload", aged=True)
    kept_id = _make_audit("completed")
    kept = folder(kept_id, aged=True)
    with get_sessionmaker()() as db:
        a = db.get(Audit, kept_id)
        a.workspace_path, a.workspace_expires_at = str(kept), datetime.now(UTC) + timedelta(hours=1)
        db.commit()

    assert jobs.purge_expired_workspaces() >= 2
    assert not orphan.exists() and not orphan_upload.exists()
    assert recent_orphan.exists() and running_upload.exists() and kept.exists()


def test_compose_runs_scheduled_cleanup():
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    assert "python -m app.worker cleanup" in compose and "sleep 3600" in compose
