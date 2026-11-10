"""Authentication and owner-scoped resource loading.

All access to projects/audits/findings/fixes goes through these loaders, which
join to Project.owner_id. A resource owned by someone else yields 404 so its
existence is not revealed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import hash_token
from app.models import Audit, AuthSession, Finding, FixProposal, Project, User

SESSION_COOKIE = "auditor_session"


def current_user(
    db: Session = Depends(get_db),
    auditor_session: str | None = Cookie(default=None),
) -> User:
    if not auditor_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(auditor_session)))
    if row is None or _aware(row.expires_at) < datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    return row.user


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


def get_project(db: Session, user: User, project_id: str) -> Project:
    p = db.scalar(select(Project).where(Project.id == project_id, Project.owner_id == user.id))
    if p is None:
        raise _not_found("Project")
    return p


def get_audit(db: Session, user: User, audit_id: str) -> Audit:
    a = db.scalar(select(Audit).join(Project).where(Audit.id == audit_id, Project.owner_id == user.id))
    if a is None:
        raise _not_found("Audit")
    return a


def get_finding(db: Session, user: User, finding_id: str) -> Finding:
    f = db.scalar(select(Finding).join(Audit).join(Project)
                  .where(Finding.id == finding_id, Project.owner_id == user.id))
    if f is None:
        raise _not_found("Finding")
    return f


def get_fix(db: Session, user: User, fix_id: str) -> FixProposal:
    fx = db.scalar(select(FixProposal).join(Audit, FixProposal.audit_id == Audit.id).join(Project)
                   .where(FixProposal.id == fix_id, Project.owner_id == user.id))
    if fx is None:
        raise _not_found("Fix")
    return fx


def workspace_available(audit: Audit) -> bool:
    from pathlib import Path

    if not audit.workspace_path or not audit.workspace_expires_at:
        return False
    return _aware(audit.workspace_expires_at) > datetime.now(UTC) and Path(audit.workspace_path).exists()
