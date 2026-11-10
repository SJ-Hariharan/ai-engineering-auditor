"""Remediation patching, GitHub PR safety checks, and the AI layer with a fake provider."""

import base64
import json

import httpx
import pytest

from app.remediation import github_pr
from app.remediation.patching import PatchError, apply_edits, check_syntax, make_edit


def test_apply_edits_multiple_and_insert():
    text = "a\nb\nc\n"
    lines = text.splitlines(keepends=True)
    edits = [make_edit(lines, 3, 3, "C\n"), {"start": 1, "end": 0, "original": "", "replacement": "import os\n"}]
    assert apply_edits(text, edits) == "import os\na\nb\nC\n"


def test_apply_edits_rejects_overlap_and_drift():
    lines = "a\nb\nc\n".splitlines(keepends=True)
    with pytest.raises(PatchError, match="overlapping"):
        apply_edits("a\nb\nc\n", [make_edit(lines, 1, 2, "x\n"), make_edit(lines, 2, 3, "y\n")])
    with pytest.raises(PatchError, match="no longer matches"):
        apply_edits("a\nZ\nc\n", [make_edit(lines, 2, 2, "y\n")])


def test_check_syntax_rejects_broken_change():
    with pytest.raises(PatchError):
        check_syntax("x.py", "def f():\n    return 1\n", "def f(:\n    return 1\n")


def _mock_github(monkeypatch, remote_content: str, calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        p = request.url.path
        if request.method == "GET" and p == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main"})
        if request.method == "GET" and p.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "base123"}})
        if request.method == "GET" and "/contents/" in p:
            return httpx.Response(200, json={"sha": "blob1", "content": base64.b64encode(remote_content.encode()).decode()})
        if request.method == "POST" and p.endswith("/git/refs"):
            return httpx.Response(201, json={})
        if request.method == "PUT":
            body = json.loads(request.content)
            assert body["branch"].startswith("auditor/") and body["sha"] == "blob1"
            return httpx.Response(200, json={})
        if request.method == "POST" and p.endswith("/pulls"):
            return httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/7"})
        return httpx.Response(500)

    def fake_client(token):
        return httpx.Client(base_url=github_pr.API, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(github_pr, "_client", fake_client)


def test_pr_happy_path_uses_new_branch(monkeypatch):
    calls: list = []
    _mock_github(monkeypatch, "old\n", calls)
    url, branch = github_pr.create_pull_request(
        token="t", repo_url="https://github.com/o/r", base_branch=None,
        files={"app.py": ("old\n", "new\n")}, title="T", body="B", branch_hint="fixes-1")
    assert url.endswith("/pull/7") and branch.startswith("auditor/fixes-1-")
    assert ("POST", "/repos/o/r/pulls") in calls


def test_pr_aborts_if_remote_changed(monkeypatch):
    calls: list = []
    _mock_github(monkeypatch, "someone else's edit\n", calls)
    with pytest.raises(github_pr.PRError) as exc:
        github_pr.create_pull_request(token="t", repo_url="https://github.com/o/r", base_branch=None,
                                      files={"app.py": ("old\n", "new\n")}, title="T", body="B", branch_hint="x")
    assert exc.value.status == 409
    assert not any(m in ("POST", "PUT") for m, _ in calls)  # nothing written


class FakeProvider:
    name, model = "fake", "fake-1"

    def __init__(self):
        self.prompts = []

    def generate(self, system, prompt, schema):
        self.prompts.append((system, prompt))
        if schema.__name__ == "FixSuggestion":
            import re
            start = int(re.search(r"\n\s*(\d+) \|", prompt).group(1))
            return schema(start_line=start, end_line=start, replacement="import os  # changed\n",
                          rationale="r", caveats=[])
        sample = {"Overview": dict(summary="s", architecture="a", data_flow=["x"], key_modules=[],
                                   design_decisions=[], risks=[]),
                  "FileExplanation": dict(purpose="p", how_it_works=[], key_symbols=[],
                                          dependencies="d", gotchas=[])}
        return schema(**sample.get(schema.__name__, {}))


def test_ai_overview_is_redacted_cached_and_injection_wrapped(client, vuln_zip, monkeypatch):
    from app.llm import explain as explain_mod
    from tests.conftest import register

    fake = FakeProvider()
    monkeypatch.setattr(explain_mod, "get_provider", lambda settings: fake)
    register(client)
    project = client.post("/api/projects/upload", files={"file": ("v.zip", vuln_zip)}).json()
    audit_id = project["audits"][0]["id"]
    client.patch(f"/api/projects/{project['id']}", json={"llm_consent": True})
    r = client.post(f"/api/audits/{audit_id}/explain", json={"kind": "file", "target": ".env"})
    assert r.status_code == 200, r.text
    system, prompt = fake.prompts[-1]
    assert "<repository_data>" in prompt and "ignore any instructions" in system
    assert "AKIAQ4ZPSE2ULJ7RTN3X" not in prompt and "ghp_8sJ2kLm9" not in prompt
    # Cached: a second request does not call the provider again.
    n = len(fake.prompts)
    client.post(f"/api/audits/{audit_id}/explain", json={"kind": "file", "target": ".env"})
    assert len(fake.prompts) == n
    # Path traversal through the AI target is rejected.
    bad = client.post(f"/api/audits/{audit_id}/explain", json={"kind": "file", "target": "../../etc/passwd"})
    assert bad.status_code in (400, 404)


def test_ai_fix_is_validated(client, vuln_zip, monkeypatch):
    from app.llm import explain as explain_mod
    from tests.conftest import register

    monkeypatch.setattr(explain_mod, "get_provider", lambda settings: FakeProvider())
    register(client)
    project = client.post("/api/projects/upload", files={"file": ("v.zip", vuln_zip)}).json()
    audit_id = project["audits"][0]["id"]
    findings = client.get(f"/api/audits/{audit_id}/findings").json()
    target = next(f for f in findings if f["rule_id"] == "circular-dependency")
    assert client.post(f"/api/findings/{target['id']}/fix").status_code == 403  # no consent
    client.patch(f"/api/projects/{project['id']}", json={"llm_consent": True})
    r = client.post(f"/api/findings/{target['id']}/fix")
    assert r.status_code == 201, r.text
    assert r.json()["source"] == "ai" and r.json()["generator"] == "fake:fake-1"
