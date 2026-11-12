"""Gitleaks secret detection. Secrets are redacted by gitleaks AND never copied into evidence."""

from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

from app.analysis.common import RawFinding
from app.analysis.scanners.base import SCANNER_CONFIG_DIR, ScannerResult, timed
from app.core.config import Settings
from app.sandbox.process import run_tool

EXAMPLE_FILE = re.compile(r"(\.example|\.sample|\.template|example\.|fixtures?/|tests?/|mocks?/)", re.I)


def run(root: Path, settings: Settings) -> ScannerResult:
    def _scan(result: ScannerResult) -> None:
        argv = ["gitleaks", "dir", ".", "--report-format", "json", "--report-path", "-",
                "--no-banner", "--redact", "--exit-code", "0", "--log-level", "error",
                "--max-target-megabytes", "2",
                # SEC-01: never let the scanned repository configure or allow-list its own secrets.
                "--config", str(SCANNER_CONFIG_DIR / "gitleaks.toml"),
                "--gitleaks-ignore-path", str(SCANNER_CONFIG_DIR / "gitleaks-ignore"),
                "--ignore-gitleaks-allow"]
        with _repo_ignore_file_hidden(root):
            res = run_tool(argv, cwd=root, timeout=settings.scanner_timeout_seconds)
        if res.timed_out:
            raise TimeoutError("gitleaks timed out")
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip()[-300:] or f"exit code {res.returncode}")
        for item in json.loads(res.stdout or "[]"):
            result.findings.append(_to_finding(root, item))

    return timed("gitleaks", "gitleaks", ["version"], _scan)


@contextmanager
def _repo_ignore_file_hidden(root: Path):
    """Gitleaks always reads <source>/.gitleaksignore, even with --gitleaks-ignore-path (SEC-01).

    `root` is our disposable workspace copy, so move that file aside for the scan and put it back.
    """
    ignore = root / ".gitleaksignore"
    if not ignore.is_file() or ignore.is_symlink():
        yield
        return
    parked = root / f".gitleaksignore.auditor-{uuid.uuid4().hex}"
    ignore.rename(parked)
    try:
        yield
    finally:
        parked.rename(ignore)


def _masked_line(root: Path, rel: str, line: int, col_start: int, col_end: int) -> str:
    """Show where the secret is without revealing it: keep the line, mask the secret span."""
    try:
        text = (root / rel).read_text("utf-8", "replace").splitlines()[line - 1]
    except (OSError, IndexError):
        return "[secret redacted]"
    start, end = max(col_start - 1, 0), max(col_end, col_start)
    secret = text[start:end]
    keep = secret[:4] if len(secret) > 12 else ""
    return (text[:start] + keep + "•" * 8 + "[redacted]" + text[end:])[:300]


def _to_finding(root: Path, item: dict) -> RawFinding:
    path = item.get("File", "").removeprefix("./")
    line = int(item.get("StartLine") or 0) or None
    likely_example = bool(EXAMPLE_FILE.search(path))
    is_env = Path(path).name.startswith(".env")
    return RawFinding(
        tool="gitleaks", rule_id=item.get("RuleID", "secret"), category="security",
        severity="low" if likely_example else ("critical" if not is_env else "high"),
        confidence="low" if likely_example else "high", kind="objective",
        title=f"Possible exposed secret ({item.get('RuleID', 'generic')})",
        file=path, line=line, end_line=item.get("EndLine"),
        evidence=_masked_line(root, path, line, int(item.get("StartColumn") or 1),
                              int(item.get("EndColumn") or 1)) if line else "[secret redacted]",
        explanation=f"{item.get('Description', 'A credential pattern was found.')} The value is "
                    "never shown in this report." + (" The file looks like an example/test file, so "
                    "this may be a placeholder." if likely_example else ""),
        impact="Anyone with read access to the repository (or its history) can use this credential. "
               "Committed secrets should be treated as compromised.",
        remediation="Revoke/rotate the credential at the provider first, then remove it from the code, "
                    "load it from environment variables or a secret manager, and add the file to "
                    ".gitignore. Rewriting git history alone does not make a leaked key safe.",
        references=["https://github.com/gitleaks/gitleaks"],
        # No line number (E-05): a secret that moves is the same finding. Several identical
        # matches in one file are told apart by occurrence order in pipeline._dedupe.
        fingerprint_key=f"{path}|{item.get('RuleID')}")
