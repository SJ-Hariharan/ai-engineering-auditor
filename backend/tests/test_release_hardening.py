"""Regressions for SEC-03 (secrets in non-Gitleaks evidence) and SEC-07 (unsafe production settings)."""

import pytest
from pydantic import ValidationError

from app import jobs
from app.analysis.pipeline import AnalysisResult
from app.core.config import Settings
from tests.conftest import register

SECRET = "super-secret-dev-key-123"
KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"


def _fake_analysis(*args, **kwargs):
    def finding(rule, line, evidence, fp):
        return {"tool": "semgrep", "rule_id": rule, "category": "security", "severity": "high",
                "confidence": "high", "kind": "objective", "title": rule, "file": "server/app.py",
                "line": line, "end_line": line, "evidence": evidence, "explanation": "", "impact": "",
                "remediation": "", "principle": None, "references": [], "fingerprint": fp}
    findings = [finding("py-hardcoded-secret-key", 13, f'app.secret_key = "{SECRET}"', "a" * 32),
                finding("high-complexity", 20, f"def f():\n    token = '{KEY}'", "b" * 32)]
    return AnalysisResult(summary={"scores": {"overall": 50, "grade": "F", "categories": {},
                                              "methodology": {"summary": "", "limitations": []}},
                                   "overview": {"paragraphs": []}}, findings=findings)


def test_non_gitleaks_secrets_are_redacted_in_api_and_markdown(monkeypatch, client, vuln_zip):
    monkeypatch.setattr(jobs, "run_analysis", _fake_analysis)
    register(client)
    project = client.post("/api/projects/upload", files={"file": ("v.zip", vuln_zip)}).json()
    audit_id = project["audits"][0]["id"]
    assert client.get(f"/api/audits/{audit_id}").json()["status"] == "completed"
    findings = client.get(f"/api/audits/{audit_id}/findings").text
    md = client.get(f"/api/audits/{audit_id}/report.md").text
    for text in (findings, md):
        assert SECRET not in text and KEY not in text
        assert "[REDACTED]" in text
    assert 'app.secret_key = "[REDACTED]"' in md  # context kept, value removed


@pytest.mark.parametrize("overrides", [{"cookie_secure": False}, {"cookie_secure": True, "inline_jobs": True}])
def test_production_rejects_unsafe_settings(overrides):
    with pytest.raises(ValidationError, match="Unsafe production configuration"):
        Settings(env="production", **overrides)


def test_production_requires_a_secret_key():
    with pytest.raises(ValidationError, match="AUDITOR_SECRET_KEY"):
        Settings(env="production", cookie_secure=True, inline_jobs=False, secret_key="short")


def test_production_accepts_safe_settings_and_dev_is_unchanged():
    assert Settings(env="production", cookie_secure=True, inline_jobs=False, secret_key="x" * 32).is_production
    assert not Settings(env="development", cookie_secure=False, inline_jobs=True).is_production


def test_production_template_must_be_filled_in(monkeypatch, tmp_path):
    """The shipped .env.production.example is rejected until its placeholder secret is replaced."""
    from pathlib import Path
    for var in ("AUDITOR_ENV", "AUDITOR_INLINE_JOBS"):  # test env vars would override the file
        monkeypatch.delenv(var, raising=False)
    template = Path(__file__).resolve().parents[2] / ".env.production.example"
    with pytest.raises(ValidationError, match="AUDITOR_SECRET_KEY"):
        Settings(_env_file=template)
    filled = tmp_path / ".env"
    filled.write_text(template.read_text().replace(
        "CHANGE-ME-run-python-c-import-secrets-print-secrets-token-urlsafe-48", "k" * 48))
    assert Settings(_env_file=filled).is_production  # filled in, it is accepted
