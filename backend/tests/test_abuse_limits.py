"""Regressions for SEC-02 (login lockout), SEC-04 (upload size), SEC-05 (clone size), SEC-06 (quotas)."""

import sys

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_sessionmaker
from app.ingestion import github
from app.ingestion.workspace import IngestionError
from app.models import Audit, Project, User
from app.sandbox.process import run_tool
from tests.conftest import register

EMAIL, PASSWORD = "alice@example.com", "correct-horse-battery"


def _new_client():
    from app.main import create_app
    return TestClient(create_app(), headers={"X-Auditor-Client": "1"})


def _login(c, password=PASSWORD, email=EMAIL):
    return c.post("/api/auth/login", json={"email": email, "password": password}).status_code


# ---------------------------------------------------------------- SEC-02

def test_attacker_failures_do_not_lock_out_a_known_device(client):
    register(client)  # the victim's browser now holds a device cookie
    with _new_client() as attacker:
        codes = [_login(attacker, "wrong-password-x") for _ in range(15)]
        assert codes[:10] == [401] * 10 and set(codes[10:]) == {429}  # attacker is throttled
    assert _login(client) == 200  # victim, same email, still gets in


def test_unknown_clients_share_a_budget_per_email(client):
    register(client)
    with _new_client() as a, _new_client() as b:
        for _ in range(10):
            assert _login(a, "wrong-password-x") == 401
        assert _login(b) == 429  # a fresh browser with no device cookie is throttled for this email
    assert _login(client) == 200


def test_successful_logins_are_not_counted(client):
    register(client)
    assert all(_login(client) == 200 for _ in range(15))


def test_a_known_device_has_its_own_failure_limit(client):
    register(client)
    codes = [_login(client, "wrong-password-x") for _ in range(11)]
    assert codes[-1] == 429  # a stolen device cookie cannot brute-force without limit


def test_forged_or_foreign_device_cookie_is_ignored(client):
    register(client)
    with _new_client() as attacker:
        attacker.cookies.set("auditor_device", "0" * 16 + ".nonce." + "f" * 64, path="/api/auth")
        for _ in range(10):
            _login(attacker, "wrong-password-x")
        assert _login(attacker) == 429  # forged cookie gives no separate budget


def test_unknown_email_failures_are_throttled_too(client):
    codes = [_login(client, "wrong-password-x", "nobody@example.com") for _ in range(12)]
    assert 429 in codes


# ---------------------------------------------------------------- SEC-04

def test_oversized_body_rejected_before_parsing(client):
    register(client)
    from app.core.config import get_settings
    too_big = get_settings().max_upload_bytes + 2 * 1024 * 1024
    r = client.post("/api/projects/upload", content=b"x", headers={
        "content-type": "multipart/form-data; boundary=x", "content-length": str(too_big)})
    assert r.status_code == 413
    assert client.get("/api/projects").json() == []  # no project was created


def test_streamed_body_is_cut_off_at_the_limit(client):
    register(client)
    from app.core.config import get_settings
    limit = get_settings().max_upload_bytes + 1024 * 1024
    sent = 0

    def chunks():  # no Content-Length: chunked transfer of a well-formed multipart file part
        nonlocal sent
        yield (b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.zip"\r\n'
               b"Content-Type: application/zip\r\n\r\nPK\x03\x04")
        block = b"0" * (1024 * 1024)
        while sent <= limit + 4 * len(block):
            sent += len(block)
            yield block

    r = client.post("/api/projects/upload", content=chunks(),
                    headers={"content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 413
    assert client.get("/api/projects").json() == []


def test_body_limit_stops_reading_at_the_limit():
    """ASGI level: the middleware stops pulling chunks once over the limit (TestClient buffers)."""
    import asyncio

    from app.core.body_limit import BodyLimitMiddleware

    pulled, seen_by_app, sent = 0, 0, []

    async def app(scope, receive, send):
        nonlocal seen_by_app
        while True:
            m = await receive()
            if m["type"] == "http.disconnect":
                await send({"type": "http.response.start", "status": 500, "headers": []})
                return
            seen_by_app += len(m["body"])
            if not m.get("more_body"):
                return

    async def receive():
        nonlocal pulled
        pulled += 1
        return {"type": "http.request", "body": b"0" * 1000, "more_body": pulled < 1000}

    async def send(m):
        sent.append(m)

    scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
    asyncio.run(BodyLimitMiddleware(app, 5000)(scope, receive, send))
    assert pulled == 6 and seen_by_app == 5000  # 6th chunk crossed the limit; nothing more read
    assert [m.get("status") for m in sent if m["type"] == "http.response.start"] == [413]


# ---------------------------------------------------------------- SEC-05

def test_run_tool_abort_if_stops_a_growing_process(tmp_path):
    out = tmp_path / "grow"
    script = f"import time\nf=open({str(out)!r},'wb')\nwhile True:\n    f.write(b'0'*65536); f.flush(); time.sleep(0.01)\n"
    res = run_tool([sys.executable, "-c", script], timeout=30,
                   abort_if=lambda: out.exists() and out.stat().st_size > 1_000_000)
    assert res.aborted and not res.timed_out


def test_clone_is_aborted_when_it_exceeds_the_size_limit(tmp_path, monkeypatch):
    dest = tmp_path / "src"

    def fake_run_tool(argv, *, abort_if=None, **kw):
        dest.mkdir(parents=True)
        (dest / "big.bin").write_bytes(b"0" * 2048)
        from app.sandbox.process import ProcessResult
        assert abort_if is not None and abort_if()  # the watchdog sees the clone growing
        return ProcessResult(-9, "", "aborted", aborted=True)

    monkeypatch.setenv("AUDITOR_MAX_EXTRACTED_BYTES", "1024")
    from app.core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setattr(github, "run_tool", fake_run_tool)
    with pytest.raises(IngestionError, match="size limit"):
        github.clone("https://github.com/o/r", None, dest)
    assert not dest.exists()


# ---------------------------------------------------------------- SEC-06

def _seed_audits(email: str, status: str, n: int) -> None:
    with get_sessionmaker()() as db:
        user = db.query(User).filter_by(email=email).one()
        project = Project(owner_id=user.id, name="p", source_type="zip")
        db.add(project)
        db.flush()
        for _ in range(n):
            db.add(Audit(project_id=project.id, status=status))
        db.commit()


def test_concurrent_audit_quota(client, vuln_zip):
    register(client)
    _seed_audits(EMAIL, "queued", 2)
    r = client.post("/api/projects/upload", files={"file": ("v.zip", vuln_zip)})
    assert r.status_code == 429 and "queued or running" in r.json()["detail"]
    r = client.post("/api/projects/github", json={"url": "https://github.com/o/r"})
    assert r.status_code == 429


def test_daily_audit_quota(client, vuln_zip, monkeypatch):
    monkeypatch.setenv("AUDITOR_MAX_AUDITS_PER_USER_PER_DAY", "3")
    from app.core.config import get_settings
    get_settings.cache_clear()
    register(client)
    _seed_audits(EMAIL, "completed", 3)
    r = client.post("/api/projects/upload", files={"file": ("v.zip", vuln_zip)})
    assert r.status_code == 429 and "Daily limit" in r.json()["detail"]


def test_quota_is_per_user(client, vuln_zip):
    register(client)
    _seed_audits(EMAIL, "queued", 2)
    with _new_client() as other:
        register(other, "bob@example.com")
        r = other.post("/api/projects/upload", files={"file": ("v.zip", vuln_zip)})
        assert r.status_code == 201


# ---------------------------------------------------------------- SEC-02 with the trusted ingress (AC3)

def _trust_ip(monkeypatch):
    monkeypatch.setenv("AUDITOR_TRUST_CLIENT_IP_HEADER", "true")
    from app.core.config import get_settings
    get_settings.cache_clear()


def _login_from(c, ip, password=PASSWORD, email=EMAIL):
    return c.post("/api/auth/login", json={"email": email, "password": password},
                  headers={"X-Auditor-Client-IP": ip}).status_code


def test_with_trusted_ip_a_new_browser_elsewhere_is_not_locked_out(client, monkeypatch):
    _trust_ip(monkeypatch)
    register(client)
    with _new_client() as attacker:
        codes = [_login_from(attacker, "203.0.113.7", "wrong-password-x") for _ in range(12)]
        assert codes[-1] == 429
    with _new_client() as new_browser:  # no device cookie, different IP
        assert _login_from(new_browser, "198.51.100.20") == 200


def test_ip_header_is_ignored_unless_trusted(client):
    register(client)
    with _new_client() as attacker:
        for i in range(10):  # rotating a spoofed header gains nothing by default
            _login_from(attacker, f"203.0.113.{i}", "wrong-password-x")
        assert _login_from(attacker, "203.0.113.99") == 429


def test_invalid_ip_header_falls_back_to_the_shared_budget(client, monkeypatch):
    _trust_ip(monkeypatch)
    register(client)
    with _new_client() as attacker:
        for _ in range(10):
            _login_from(attacker, "not-an-ip", "wrong-password-x")
        assert _login_from(attacker, "also-not-an-ip") == 429


def test_distributed_guessing_is_capped_per_email(client, monkeypatch):
    _trust_ip(monkeypatch)
    from app.api import auth
    register(client)
    with _new_client() as botnet:
        for i in range(auth.MAX_PER_EMAIL_ALL_IPS):
            _login_from(botnet, f"10.0.{i // 250}.{i % 250 + 1}", "wrong-password-x")
        assert _login_from(botnet, "192.0.2.200", "wrong-password-x") == 429
    assert _login(client) == 200  # the known device is still unaffected


def test_password_spraying_from_one_ip_is_capped(client, monkeypatch):
    _trust_ip(monkeypatch)
    from app.api import auth
    with _new_client() as sprayer:
        for i in range(auth.MAX_PER_IP_ALL_EMAILS):
            _login_from(sprayer, "203.0.113.50", "wrong-password-x", email=f"user{i}@example.com")
        assert _login_from(sprayer, "203.0.113.50", "wrong-password-x", email="fresh@example.com") == 429
        assert _login_from(sprayer, "203.0.113.51", "wrong-password-x", email="fresh@example.com") == 401
