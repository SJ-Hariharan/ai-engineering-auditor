"""Semgrep static analysis with the bundled rule set (offline by default)."""

from __future__ import annotations

import json
from pathlib import Path

from app.analysis.common import RawFinding
from app.analysis.scanners.base import ScannerResult, read_lines, timed
from app.core.config import Settings
from app.sandbox.process import run_tool

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"
SEVERITY = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
CRITICAL_CATEGORIES = {"sql-injection", "command-injection", "code-injection"}
# Replaces Semgrep's built-in default .semgrepignore (dependencies, build output, tests).
DEFAULT_EXCLUDES = ("node_modules", ".venv", "venv", "vendor", "dist", "build", ".next", "coverage",
                    "__pycache__", ".git", "test", "tests", "*.min.js")


def run(root: Path, settings: Settings) -> ScannerResult:
    def _scan(result: ScannerResult) -> None:
        configs = ["--config", str(RULES_DIR)]
        if not settings.offline:
            for extra in settings.semgrep_extra_configs:
                configs += ["--config", extra]
        argv = ["semgrep", "scan", *configs, "--json", "--metrics=off", "--disable-version-check",
                "--quiet", "--timeout", "30", "--max-target-bytes", str(settings.max_file_bytes_analyzed),
                "--jobs", "2",
                # SEC-01: the repository must not suppress its own findings. Ignore inline
                # `nosemgrep` comments and any .semgrepignore it ships, and apply our own
                # excludes (the same folders Semgrep skips by default) instead.
                "--disable-nosem", "--x-ignore-semgrepignore-files", "--no-git-ignore",
                *[arg for d in DEFAULT_EXCLUDES for arg in ("--exclude", d)],
                "."]
        res = run_tool(argv, cwd=root, timeout=settings.scanner_timeout_seconds,
                       env_extra={"SEMGREP_SEND_METRICS": "off", "SEMGREP_ENABLE_VERSION_CHECK": "0"})
        if res.timed_out:
            raise TimeoutError("semgrep timed out")
        data = json.loads(res.stdout or "{}")
        if res.returncode not in (0, 1) and not data.get("results"):
            raise RuntimeError(res.stderr.strip()[-300:] or f"exit code {res.returncode}")
        errors = [e.get("message", "")[:120] for e in data.get("errors", []) if e.get("level") == "error"]
        if errors:
            result.message = f"{len(errors)} file(s) could not be analysed"
        for r in data.get("results", []):
            result.findings.append(_to_finding(root, r))

    return timed("semgrep", "semgrep", ["--version"], _scan)


def _to_finding(root: Path, r: dict) -> RawFinding:
    extra = r.get("extra", {})
    meta = extra.get("metadata", {})
    rule = r["check_id"].rsplit(".", 1)[-1]
    category = meta.get("category", "security")
    severity = SEVERITY.get(extra.get("severity", "WARNING"), "medium")
    if category in CRITICAL_CATEGORIES and meta.get("confidence") == "HIGH":
        severity = "critical"
    path = r["path"].removeprefix("./")
    line = r["start"]["line"]
    cwe = meta.get("cwe")
    refs = [f"https://cwe.mitre.org/data/definitions/{cwe.split('-')[1]}.html"] if cwe else []
    return RawFinding(
        tool="semgrep", rule_id=rule, category="security", severity=severity,
        confidence=str(meta.get("confidence", "MEDIUM")).lower(), kind="objective",
        title=extra.get("message", rule).split(".")[0][:200],
        file=path, line=line, end_line=r["end"]["line"],
        evidence=read_lines(root, path, line, 1),
        explanation=f"{extra.get('message', '')} ({cwe or category}). Detected by Semgrep pattern "
                    f"matching; the code shown matched rule `{rule}`.",
        impact=meta.get("impact", ""), remediation=meta.get("fix", ""), references=refs,
        principle=category,
        fingerprint_key=f"{path}|{read_lines(root, path, line, 0).strip()[:200]}")
