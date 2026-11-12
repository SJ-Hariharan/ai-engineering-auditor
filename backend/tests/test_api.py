"""API-level tests: auth, CSRF, cross-user isolation, the full audit → fix → PR flow."""

import pytest

from tests.conftest import register, requires_scanners


def test_auth_lifecycle(client):
    register(client)
    assert client.get("/api/auth/me").json()["email"] == "alice@example.com"
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    bad = client.post("/api/auth/login", json={"email": "alice@example.com", "password": "wrong-password-1"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login", json={"email": "ALICE@example.com", "password": "correct-horse-battery"})
    assert ok.status_code == 200
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_duplicate_registration_and_weak_password(client):
    register(client)
    assert client.post("/api/auth/register", json={"email": "alice@example.com",
                                                   "password": "another-long-pass"}).status_code == 409
    assert client.post("/api/auth/register", json={"email": "b@example.com", "password": "short"}).status_code == 422


def test_csrf_header_required(client):
    r = client.post("/api/auth/register", json={"email": "x@example.com", "password": "long-enough-pass"},
                    headers={"X-Auditor-Client": ""})
    assert r.status_code == 403


def test_login_rate_limit(client):
    codes = [client.post("/api/auth/login", json={"email": "z@example.com", "password": "wrong-password-x"}).status_code
             for _ in range(12)]
    assert 429 in codes


def test_requires_auth(client):
    assert client.get("/api/projects").status_code == 401


def test_github_url_validation(client):
    register(client)
    for url in ("http://github.com/a/b", "https://evil.com/a/b", "https://github.com/a/b/../../x",
                "file:///etc/passwd", "https://github.com/a"):
        assert client.post("/api/projects/github", json={"url": url}).status_code == 422, url


def test_upload_rejects_non_zip(client):
    register(client)
    r = client.post("/api/projects/upload", files={"file": ("x.zip", b"hello", "application/zip")})
    assert r.status_code == 422
    assert client.get("/api/projects").json() == []


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setenv("AUDITOR_MAX_UPLOAD_BYTES", "1000")
    from app.core.config import get_settings
    get_settings.cache_clear()
    register(client)
    r = client.post("/api/projects/upload", files={"file": ("x.zip", b"PK\x03\x04" + b"0" * 5000)})
    assert r.status_code == 413


@pytest.fixture
def audited(client, vuln_zip):
    register(client)
    r = client.post("/api/projects/upload", files={"file": ("vuln.zip", vuln_zip, "application/zip")})
    assert r.status_code == 201, r.text
    project = r.json()
    audit_id = project["audits"][0]["id"]
    audit = client.get(f"/api/audits/{audit_id}").json()
    assert audit["status"] == "completed", audit["error"]
    return project, audit


@requires_scanners
def test_full_audit_flow(client, audited):
    project, audit = audited
    s = audit["summary"]
    assert s["scores"]["overall"] < 90
    assert {sc["name"] for sc in s["scanners"]} == {"semgrep", "gitleaks", "osv-scanner", "trivy"}
    findings = client.get(f"/api/audits/{audit['id']}/findings").json()
    rules = {f["rule_id"] for f in findings}
    for expected in ("py-sql-injection-string-build", "js-reflected-xss-express", "circular-dependency",
                     "unresolved-import", "bare-except", "no-tests", "aws-access-token"):
        assert expected in rules, expected
    for f in findings:  # every finding carries the required report fields
        assert f["severity"] and f["category"] and f["confidence"] and f["kind"]
        assert f["explanation"] and f["impact"] and f["remediation"]
    # Secrets are never exposed: not in evidence, not in the file viewer.
    leaked = [f for f in findings if f["tool"] == "gitleaks"]
    assert leaked and all("AKIAQ4ZPSE2ULJ7RTN3X" not in f["evidence"] for f in leaked)
    env = client.get(f"/api/audits/{audit['id']}/files/.env").json()
    assert "AKIAQ4ZPSE2ULJ7RTN3X" not in env["content"] and "ghp_8sJ2" not in env["content"]
    # Report export
    md = client.get(f"/api/audits/{audit['id']}/report.md").text
    assert "not a security certification" in md and "AKIAQ4ZPSE2ULJ7RTN3X" not in md


def test_file_viewer_path_traversal(client, audited):
    _, audit = audited
    for path in ("../../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", "server/../../x"):
        r = client.get(f"/api/audits/{audit['id']}/files/{path}")
        assert r.status_code in (400, 404), (path, r.status_code)
    ok = client.get(f"/api/audits/{audit['id']}/files/server/app.py")
    assert ok.status_code == 200 and ok.json()["symbols"]


def test_cross_user_isolation(client, audited):
    project, audit = audited
    fid = client.get(f"/api/audits/{audit['id']}/findings").json()[0]["id"]
    client.post("/api/auth/logout")
    register(client, "mallory@example.com")
    assert client.get("/api/projects").json() == []
    for url in (f"/api/projects/{project['id']}", f"/api/audits/{audit['id']}",
                f"/api/audits/{audit['id']}/findings", f"/api/audits/{audit['id']}/files/server/app.py",
                f"/api/audits/{audit['id']}/fixes", f"/api/audits/{audit['id']}/report.md"):
        assert client.get(url).status_code == 404, url
    assert client.patch(f"/api/projects/{project['id']}", json={"llm_consent": True}).status_code == 404
    assert client.delete(f"/api/projects/{project['id']}").status_code == 404
    assert client.post(f"/api/findings/{fid}/fix").status_code == 404
    assert client.post(f"/api/audits/{audit['id']}/explain", json={"kind": "overview"}).status_code == 404


def test_deterministic_fix_approval_and_pr_rules(client, audited):
    project, audit = audited
    findings = client.get(f"/api/audits/{audit['id']}/findings").json()
    bare = next(f for f in findings if f["rule_id"] == "bare-except")
    r = client.post(f"/api/findings/{bare['id']}/fix")
    assert r.status_code == 201, r.text
    fix = r.json()
    assert fix["source"] == "deterministic"
    assert "-    except:" in fix["diff"] and "+    except Exception:" in fix["diff"]
    assert client.patch(f"/api/fixes/{fix['id']}", json={"status": "approved"}).json()["status"] == "approved"
    # PRs are only for GitHub projects, and require explicit confirmation.
    r = client.post(f"/api/audits/{audit['id']}/pull-request",
                    json={"github_token": "x" * 30, "confirm": True})
    assert r.status_code == 422
    r = client.post(f"/api/audits/{audit['id']}/pull-request",
                    json={"github_token": "x" * 30, "confirm": False})
    assert r.status_code == 422
    # The original repository copy is never modified by proposing/approving fixes.
    content = client.get(f"/api/audits/{audit['id']}/files/server/app.py").json()["content"]
    assert "    except:\n" in content


def test_ai_requires_consent_and_provider(client, audited):
    project, audit = audited
    r = client.post(f"/api/audits/{audit['id']}/explain", json={"kind": "overview"})
    assert r.status_code == 403
    client.patch(f"/api/projects/{project['id']}", json={"llm_consent": True})
    r = client.post(f"/api/audits/{audit['id']}/explain", json={"kind": "overview"})
    assert r.status_code == 503  # no provider configured in tests
    assert client.get("/api/ai/status").json() == {"provider": "none", "configured": False, "model": None}


def test_rerun_zip_requires_new_upload_and_compares(client, audited, vuln_zip):
    project, audit = audited
    assert client.post(f"/api/projects/{project['id']}/audits").status_code == 422
    r = client.post(f"/api/projects/{project['id']}/audits", files={"file": ("v.zip", vuln_zip)})
    assert r.status_code == 201
    second = client.get(f"/api/audits/{r.json()['id']}").json()
    comp = second["summary"]["comparison"]
    assert comp["previous_audit_id"] == audit["id"] and comp["new"] == 0 and comp["resolved"] == 0


def test_delete_project_removes_workspace(client, audited, tmp_path):
    project, audit = audited
    ws = tmp_path / "ws" / audit["id"]
    assert ws.exists()
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert not ws.exists()
    assert client.get(f"/api/audits/{audit['id']}").status_code == 404


def test_status_endpoint_is_small_and_owner_scoped(client, audited):
    """E-03: polling uses a payload of a few hundred bytes instead of the full summary."""
    _, audit = audited
    r = client.get(f"/api/audits/{audit['id']}/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed" and set(body) == {"id", "status", "stage", "error", "finished_at", "test_run"}
    full = client.get(f"/api/audits/{audit['id']}").content
    assert len(r.content) < 1000 < len(full)
    client.post("/api/auth/logout")
    from tests.conftest import register as reg
    reg(client, "mallory@example.com")
    assert client.get(f"/api/audits/{audit['id']}/status").status_code == 404
