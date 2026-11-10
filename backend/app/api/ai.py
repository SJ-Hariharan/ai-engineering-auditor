"""AI explanations (consent-gated)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_audit
from app.core.config import get_settings
from app.core.database import get_db
from app.llm.explain import ExplainError, explain
from app.llm.providers import provider_status
from app.models import AIArtifact, User
from app.schemas import AIArtifactOut, AIStatus, ExplainRequest

router = APIRouter(prefix="/api", tags=["ai"])


@router.get("/ai/status", response_model=AIStatus)
def ai_status(_: User = Depends(current_user)):
    name, configured, model = provider_status(get_settings())
    return AIStatus(provider=name, configured=configured, model=model)


@router.post("/audits/{audit_id}/explain", response_model=AIArtifactOut)
def explain_endpoint(audit_id: str, body: ExplainRequest, db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    audit = get_audit(db, user, audit_id)
    try:
        return explain(db, audit, body.kind, body.target, body.refresh)
    except ExplainError as exc:
        raise HTTPException(exc.status, str(exc)) from None


@router.get("/audits/{audit_id}/explanations", response_model=list[AIArtifactOut])
def list_explanations(audit_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    audit = get_audit(db, user, audit_id)
    return db.scalars(select(AIArtifact).where(AIArtifact.audit_id == audit.id)).all()
