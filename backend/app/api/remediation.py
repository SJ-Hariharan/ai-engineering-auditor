"""Fix proposals (deterministic or AI), approval, and pull requests."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, get_audit, get_finding, get_fix, workspace_available
from app.core.database import get_db
from app.ingestion.workspace import safe_join, source_dir
from app.llm.explain import ExplainError, suggest_fix
from app.models import Audit, Finding, FixProposal, PullRequestRecord, User
from app.remediation.fixers import deterministic_fix
from app.remediation.github_pr import PRError, create_pull_request
from app.remediation.patching import PatchError, apply_edits, check_syntax, make_edit, unified_diff
from app.schemas import FixDecision, FixOut, PullRequestCreate, PullRequestOut

router = APIRouter(prefix="/api", tags=["remediation"])


def _source(audit: Audit, rel: str) -> str:
    if not workspace_available(audit):
        raise HTTPException(status.HTTP_410_GONE, "Source files for this audit have expired; re-run the audit.")
    try:
        p = safe_join(source_dir(Path(audit.workspace_path)), rel)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid path") from None
    return p.read_text("utf-8")


@router.post("/findings/{finding_id}/fix", response_model=FixOut, status_code=201)
def propose_fix(finding_id: str, use_ai: bool = False, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    f: Finding = get_finding(db, user, finding_id)
    audit = f.audit
    if not f.file or not f.line:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "This finding has no specific code location to change.")
    if f.tool == "gitleaks":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Leaked secrets must be revoked at the provider first; a code edit alone "
                            "does not fix them.")
    existing = db.scalar(select(FixProposal).where(FixProposal.finding_id == f.id,
                                                   FixProposal.status != "rejected"))
    if existing and not use_ai:
        return existing
    original = _source(audit, f.file)
    lines = original.splitlines(keepends=True)
    result = None if use_ai else deterministic_fix(lines, f)
    if result is not None:
        edits, rationale, caveats = result
        source, generator = "deterministic", f"fixer:{f.rule_id}"
    else:
        try:
            s, generator = suggest_fix(db, audit, f)
        except ExplainError as exc:
            raise HTTPException(exc.status, str(exc)) from None
        edits = [make_edit(lines, s.start_line, s.end_line, s.replacement)]
        rationale, caveats, source = s.rationale, s.caveats, "ai"
    try:
        proposed = apply_edits(original, edits)
        check_syntax(f.file, original, proposed)
    except PatchError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    if proposed == original:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The proposed fix changes nothing.")
    fx = FixProposal(audit_id=audit.id, finding_id=f.id, file=f.file, edits=edits,
                     diff=unified_diff(f.file, original, proposed), rationale=rationale,
                     source=source, generator=generator, caveats=caveats)
    db.add(fx)
    db.commit()
    return fx


@router.get("/audits/{audit_id}/fixes", response_model=list[FixOut])
def list_fixes(audit_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    audit = get_audit(db, user, audit_id)
    return db.scalars(select(FixProposal).where(FixProposal.audit_id == audit.id)
                      .order_by(FixProposal.created_at)).all()


@router.patch("/fixes/{fix_id}", response_model=FixOut)
def decide_fix(fix_id: str, body: FixDecision, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    fx = get_fix(db, user, fix_id)
    fx.status = body.status
    db.commit()
    return fx


@router.post("/audits/{audit_id}/pull-request", response_model=PullRequestOut, status_code=201)
def open_pull_request(audit_id: str, body: PullRequestCreate, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    audit = get_audit(db, user, audit_id)
    project = audit.project
    if project.source_type != "github":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Pull requests are only available for GitHub projects. Download the "
                            "diffs instead.")
    approved = db.scalars(select(FixProposal).where(FixProposal.audit_id == audit.id,
                                                    FixProposal.status == "approved")).all()
    if not approved:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Approve at least one fix first.")
    by_file: dict[str, list[FixProposal]] = {}
    for fx in approved:
        by_file.setdefault(fx.file, []).append(fx)
    files: dict[str, tuple[str, str]] = {}
    for path, fixes in by_file.items():
        original = _source(audit, path)
        try:
            new = apply_edits(original, [e for fx in fixes for e in fx.edits])
            check_syntax(path, original, new)
        except PatchError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{path}: {exc}") from None
        files[path] = (original, new)
    findings = {f.id: f for f in db.scalars(select(Finding).where(
        Finding.id.in_([fx.finding_id for fx in approved])))}
    lines = ["Fixes reviewed and approved in **AI Engineering Auditor**.", "",
             f"Audited commit: `{audit.commit_sha}`", ""]
    for fx in approved:
        fd = findings.get(fx.finding_id)
        lines += [f"### {fd.title if fd else fx.file}",
                  f"`{fx.file}` · {fd.severity if fd else ''} · source: {fx.source} ({fx.generator})",
                  "", fx.rationale, ""]
        lines += [f"- ⚠️ {c}" for c in fx.caveats] + [""]
    lines += ["---", "Please review and run your test suite before merging. Automated fixes can be wrong."]
    try:
        url, branch = create_pull_request(
            token=body.github_token, repo_url=project.source_url, base_branch=project.default_branch,
            files=files, title=body.title, body="\n".join(lines), branch_hint=f"fixes-{audit.id[:8]}")
    except PRError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    rec = PullRequestRecord(audit_id=audit.id, url=url, branch=branch, fix_ids=[fx.id for fx in approved])
    db.add(rec)
    db.commit()
    return rec


@router.get("/audits/{audit_id}/pull-requests", response_model=list[PullRequestOut])
def list_pull_requests(audit_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    audit = get_audit(db, user, audit_id)
    return db.scalars(select(PullRequestRecord).where(PullRequestRecord.audit_id == audit.id)).all()
