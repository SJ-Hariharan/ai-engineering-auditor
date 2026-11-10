"""Projects (a repository source) and the audits run against them."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_project, workspace_available
from app.core.config import get_settings
from app.core.database import get_db
from app.ingestion.workspace import delete_workspace
from app.jobs import enqueue, fail_stale_audits, upload_path
from app.models import Audit, Project, User
from app.schemas import (
    AuditBrief,
    AuditOut,
    GitHubProjectCreate,
    ProjectDetail,
    ProjectOut,
    ProjectUpdate,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


def audit_brief(a: Audit) -> AuditBrief:
    scores = (a.summary or {}).get("scores") or {}
    counts = ((a.summary or {}).get("counts") or {}).get("by_severity") or {}
    return AuditBrief(id=a.id, status=a.status, stage=a.stage, error=a.error, commit_sha=a.commit_sha,
                      created_at=a.created_at, finished_at=a.finished_at,
                      overall_score=scores.get("overall"), finding_counts=counts)


def audit_out(a: Audit) -> AuditOut:
    return AuditOut(id=a.id, project_id=a.project_id, previous_audit_id=a.previous_audit_id,
                    status=a.status, stage=a.stage, error=a.error, commit_sha=a.commit_sha,
                    created_at=a.created_at, started_at=a.started_at, finished_at=a.finished_at,
                    workspace_available=workspace_available(a), summary=a.summary or {})


def project_out(p: Project, detail: bool = False) -> ProjectOut | ProjectDetail:
    base = dict(id=p.id, name=p.name, source_type=p.source_type, source_url=p.source_url,
                default_branch=p.default_branch, llm_consent=p.llm_consent,
                llm_consent_at=p.llm_consent_at, created_at=p.created_at,
                latest_audit=audit_brief(p.audits[0]) if p.audits else None)
    if detail:
        return ProjectDetail(**base, audits=[audit_brief(a) for a in p.audits])
    return ProjectOut(**base)


async def _save_upload(file: UploadFile, audit_id: str) -> None:
    limit = get_settings().max_upload_bytes
    dest = upload_path(audit_id)
    size = 0
    with open(dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                dest.parent.rmdir()
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                                    f"Upload exceeds {limit // (1024 * 1024)} MB")
            out.write(chunk)
    with open(dest, "rb") as fh:
        if fh.read(4) != b"PK\x03\x04":
            dest.unlink(missing_ok=True)
            dest.parent.rmdir()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "File is not a ZIP archive")


def _check_quota(db: Session, user: User) -> None:
    """Per-user limits so one account cannot monopolise the worker or the disk (SEC-06)."""
    s = get_settings()
    mine = select(func.count(Audit.id)).join(Project, Audit.project_id == Project.id).where(
        Project.owner_id == user.id)
    active = db.scalar(mine.where(Audit.status.in_(("queued", "running")))) or 0
    if active >= s.max_active_audits_per_user:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"You already have {active} audit(s) queued or running. "
                            "Wait for one to finish before starting another.")
    today = db.scalar(mine.where(Audit.created_at >= datetime.now(UTC) - timedelta(days=1))) or 0
    if today >= s.max_audits_per_user_per_day:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Daily limit of {s.max_audits_per_user_per_day} audits reached. Try again later.")


def _new_audit(db: Session, project: Project) -> Audit:
    prev = db.scalar(select(Audit).where(Audit.project_id == project.id, Audit.status == "completed")
                     .order_by(Audit.created_at.desc()))
    audit = Audit(project_id=project.id, previous_audit_id=prev.id if prev else None)
    db.add(audit)
    db.commit()
    return audit


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Project).where(Project.owner_id == user.id)
                      .order_by(Project.created_at.desc())).all()
    return [project_out(p) for p in rows]


@router.post("/github", response_model=ProjectDetail, status_code=201)
def create_github_project(body: GitHubProjectCreate, db: Session = Depends(get_db),
                          user: User = Depends(current_user)):
    _check_quota(db, user)
    owner, repo = body.url.rstrip("/").split("/")[-2:]
    project = Project(owner_id=user.id, name=f"{owner}/{repo}", source_type="github",
                      source_url=body.url.rstrip("/"), default_branch=body.branch)
    db.add(project)
    db.commit()
    audit = _new_audit(db, project)
    enqueue("run_audit", audit.id)
    db.refresh(project)
    return project_out(project, detail=True)


@router.post("/upload", response_model=ProjectDetail, status_code=201)
async def create_zip_project(file: UploadFile = File(...), name: str | None = Form(default=None),
                             db: Session = Depends(get_db), user: User = Depends(current_user)):
    _check_quota(db, user)
    raw_name = name or re.sub(r"\.zip$", "", file.filename or "upload", flags=re.I)
    clean = re.sub(r"[^\w .\-/]", "", raw_name)[:200].strip() or "Uploaded project"
    project = Project(owner_id=user.id, name=clean, source_type="zip")
    db.add(project)
    db.commit()
    audit = Audit(project_id=project.id)
    db.add(audit)
    db.commit()
    try:
        await _save_upload(file, audit.id)
    except HTTPException:
        db.delete(project)
        db.commit()
        raise
    enqueue("run_audit", audit.id)
    db.refresh(project)
    return project_out(project, detail=True)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project_detail(project_id: str, db: Session = Depends(get_db),
                       user: User = Depends(current_user)):
    return project_out(get_project(db, user, project_id), detail=True)


@router.patch("/{project_id}", response_model=ProjectDetail)
def update_project(project_id: str, body: ProjectUpdate, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    p = get_project(db, user, project_id)
    if body.name is not None:
        p.name = body.name
    if body.llm_consent is not None:
        p.llm_consent = body.llm_consent
        p.llm_consent_at = datetime.now(UTC) if body.llm_consent else None
    db.commit()
    return project_out(p, detail=True)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = get_project(db, user, project_id)
    for a in p.audits:
        delete_workspace(a.workspace_path)
    db.delete(p)
    db.commit()


@router.post("/{project_id}/audits", response_model=AuditOut, status_code=201)
async def rerun_audit(project_id: str, file: UploadFile | None = File(default=None),
                      db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = get_project(db, user, project_id)
    if any(a.status in ("queued", "running") for a in p.audits) and fail_stale_audits():
        db.expire_all()  # a stale audit was just marked failed; re-read the project's audits
    if any(a.status in ("queued", "running") for a in p.audits):
        raise HTTPException(status.HTTP_409_CONFLICT, "An audit is already in progress")
    if p.source_type == "zip" and file is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Upload the updated ZIP to re-run an audit for an uploaded project")
    _check_quota(db, user)
    audit = _new_audit(db, p)
    if file is not None and p.source_type == "zip":
        try:
            await _save_upload(file, audit.id)
        except HTTPException:
            db.delete(audit)
            db.commit()
            raise
    enqueue("run_audit", audit.id)
    return audit_out(audit)
