"""Common scanner plumbing."""

from __future__ import annotations

import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.analysis.common import RawFinding
from app.sandbox.process import run_tool


@dataclass
class ScannerResult:
    name: str
    status: str = "ok"  # ok | skipped | failed
    version: str | None = None
    duration_s: float = 0.0
    message: str = ""
    findings: list[RawFinding] = field(default_factory=list)

    def summary(self) -> dict:
        return {"name": self.name, "status": self.status, "version": self.version,
                "duration_s": round(self.duration_s, 2), "message": self.message,
                "findings": len(self.findings)}


def tool_version(binary: str, args: list[str]) -> str | None:
    if not shutil.which(binary):
        return None
    res = run_tool([binary, *args], timeout=30)
    m = re.search(r"\d+\.\d+(?:\.\d+)?", res.stdout or res.stderr)
    return m.group(0) if m else "unknown"


def timed(name: str, binary: str, version_args: list[str],
          fn: Callable[[ScannerResult], None]) -> ScannerResult:
    result = ScannerResult(name=name)
    version = tool_version(binary, version_args)
    if version is None:
        result.status = "skipped"
        result.message = f"{binary} is not installed on the worker"
        return result
    result.version = version
    start = time.monotonic()
    try:
        fn(result)
    except Exception as exc:  # scanner failures must not abort the audit
        result.status = "failed"
        result.message = f"{type(exc).__name__}: {str(exc)[:300]}"
    result.duration_s = time.monotonic() - start
    return result


# App-owned scanner configuration. Scanned repositories are untrusted: they must not be able to
# switch off or allow-list their own findings (SEC-01), so every scanner is pointed at these.
SCANNER_CONFIG_DIR = Path(__file__).resolve().parent.parent / "scanner_config"


def read_lines(root: Path, rel: str, line: int | None, context: int = 2) -> str:
    if not line:
        return ""
    try:
        lines = (root / rel).read_text("utf-8", "replace").splitlines()
    except OSError:
        return ""
    start = max(line - 1 - context, 0)
    return "\n".join(lines[start:line + context])[:800]


def cvss_to_severity(score: float | None) -> str:
    if score is None:
        return "medium"
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low"
