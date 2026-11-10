"""Shared types for analyzers."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RawFinding:
    tool: str
    rule_id: str
    category: str  # security | architecture | code_quality | reliability | maintainability
    severity: str  # critical | high | medium | low | info
    confidence: str  # high | medium | low
    kind: str  # objective | subjective
    title: str
    file: str | None = None
    line: int | None = None
    end_line: int | None = None
    evidence: str = ""
    explanation: str = ""
    impact: str = ""
    remediation: str = ""
    principle: str | None = None
    references: list[str] = field(default_factory=list)
    # Optional extra component of the fingerprint (e.g. a package@version)
    fingerprint_key: str = ""

    def fingerprint(self) -> str:
        """Stable across re-runs: ignores line numbers so small edits don't 'move' findings."""
        basis = "|".join(
            [self.tool, self.rule_id, self.file or "", self.fingerprint_key or self.evidence.strip()[:200]]
        )
        return hashlib.sha256(basis.encode()).hexdigest()[:32]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("fingerprint_key")
        d["fingerprint"] = self.fingerprint()
        return d


def clip(text: str, limit: int = 600) -> str:
    text = text.rstrip()
    return text if len(text) <= limit else text[:limit] + " …"
