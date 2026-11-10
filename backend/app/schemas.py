"""Pydantic models: the public API contract (mirrored in frontend/src/lib/types.ts)."""

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Severity = Literal["critical", "high", "medium", "low", "info"]
Category = Literal["security", "architecture", "code_quality", "reliability", "maintainability"]
Confidence = Literal["high", "medium", "low"]
Kind = Literal["objective", "subjective"]

SEVERITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

GITHUB_URL_RE = re.compile(r"^https://github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100})/?$")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)


class UserOut(ORM):
    id: str
    email: str
    created_at: datetime


# ---------- projects ----------
class GitHubProjectCreate(BaseModel):
    url: str = Field(max_length=200)
    branch: str | None = Field(default=None, max_length=200, pattern=r"^[A-Za-z0-9._/-]+$")

    @field_validator("url")
    @classmethod
    def _github_only(cls, v: str) -> str:
        v = v.strip().removesuffix(".git")
        if not GITHUB_URL_RE.match(v):
            raise ValueError("Must be a public https://github.com/<owner>/<repo> URL")
        return v


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    llm_consent: bool | None = None


class AuditBrief(ORM):
    id: str
    status: str
    stage: str | None
    error: str | None
    commit_sha: str | None
    created_at: datetime
    finished_at: datetime | None
    overall_score: float | None = None
    finding_counts: dict[str, int] = Field(default_factory=dict)


class ProjectOut(ORM):
    id: str
    name: str
    source_type: str
    source_url: str | None
    default_branch: str | None
    llm_consent: bool
    llm_consent_at: datetime | None
    created_at: datetime
    latest_audit: AuditBrief | None = None


class ProjectDetail(ProjectOut):
    audits: list[AuditBrief] = Field(default_factory=list)


# ---------- audits ----------
class AuditOut(ORM):
    id: str
    project_id: str
    previous_audit_id: str | None
    status: str
    stage: str | None
    error: str | None
    commit_sha: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    workspace_available: bool
    summary: dict[str, Any]


class FindingOut(ORM):
    id: str
    fingerprint: str
    tool: str
    rule_id: str
    category: str
    severity: str
    confidence: str
    kind: str
    principle: str | None
    title: str
    file: str | None
    line: int | None
    end_line: int | None
    evidence: str
    explanation: str
    impact: str
    remediation: str
    references: list[str]
    has_fix: bool = False  # a fix proposal has already been generated
    fixable: bool = False  # a deterministic (non-AI) fixer exists for this rule


class FileContent(BaseModel):
    path: str
    language: str | None
    content: str
    truncated: bool
    symbols: list[dict[str, Any]]
    findings: list[FindingOut]


# ---------- remediation ----------
class FixOut(ORM):
    id: str
    finding_id: str
    file: str
    diff: str
    rationale: str
    source: str
    generator: str
    caveats: list[str]
    status: str
    created_at: datetime


class FixDecision(BaseModel):
    status: Literal["approved", "rejected", "pending"]


class PullRequestCreate(BaseModel):
    # Used for this single request and never stored or logged.
    github_token: str = Field(min_length=20, max_length=255, repr=False)
    title: str = Field(default="Fixes from AI Engineering Auditor", max_length=200)
    confirm: Literal[True]  # explicit approval is required


class PullRequestOut(ORM):
    id: str
    url: str
    branch: str
    fix_ids: list[str]
    created_at: datetime


# ---------- AI ----------
class ExplainRequest(BaseModel):
    kind: Literal["overview", "file", "symbol", "questions", "finding"]
    target: str = Field(default="", max_length=1000)
    refresh: bool = False


class AIArtifactOut(ORM):
    id: str
    kind: str
    target: str
    provider: str
    model: str
    content: dict[str, Any]
    created_at: datetime


class AIStatus(BaseModel):
    provider: str
    configured: bool
    model: str | None
