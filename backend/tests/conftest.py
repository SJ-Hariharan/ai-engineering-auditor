import io
import os
import shutil
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITOR_ENV", "test")
    monkeypatch.setenv("AUDITOR_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("AUDITOR_INLINE_JOBS", "true")
    monkeypatch.setenv("AUDITOR_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("AUDITOR_LLM_PROVIDER", "none")
    monkeypatch.setenv("AUDITOR_OFFLINE", "true")  # no network in tests
    monkeypatch.delenv("AUDITOR_ANTHROPIC_API_KEY", raising=False)
    from app.api import auth
    from app.core import config, database

    config.get_settings.cache_clear()
    database.get_engine.cache_clear()
    database.get_sessionmaker.cache_clear()
    auth._attempts.clear()
    database.init_db()
    yield
    database.get_engine().dispose()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(), headers={"X-Auditor-Client": "1"}) as c:
        yield c


def register(c, email="alice@example.com", password="correct-horse-battery"):
    r = c.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r


def zip_dir(src: Path, prefix: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                zf.write(p, prefix + p.relative_to(src).as_posix())
    return buf.getvalue()


@pytest.fixture
def vuln_zip() -> bytes:
    return zip_dir(FIXTURES / "vulnerable_app", "vulnerable_app-main/")


def scanners_installed() -> bool:
    return all(shutil.which(t) for t in ("semgrep", "gitleaks"))


requires_scanners = pytest.mark.skipif(not scanners_installed() or os.environ.get("SKIP_SCANNERS") == "1",
                                       reason="semgrep/gitleaks not installed")
