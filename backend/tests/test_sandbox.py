"""Real Docker sandbox test. Skipped when Docker is unavailable."""

import pytest

from app.sandbox.docker_tests import docker_available, run_test_suite

pytestmark = [pytest.mark.docker,
              pytest.mark.skipif(not docker_available(), reason="Docker daemon not available")]


def test_sandbox_blocks_network_and_hides_host_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPER_SECRET_HOST_VAR", "leak-me")
    monkeypatch.setenv("AUDITOR_SANDBOX_ENABLED", "true")  # opt-in since the default became off
    from app.core.config import get_settings
    get_settings.cache_clear()
    src = tmp_path / "src"
    (src / "tests").mkdir(parents=True)
    (src / "requirements.txt").write_text("")
    (src / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (src / "tests" / "test_it.py").write_text(
        "import os, socket\nfrom calc import add\n"
        "def test_add():\n    assert add(1, 2) == 3\n"
        "def test_network_blocked():\n"
        "    try:\n        socket.create_connection(('1.1.1.1', 53), timeout=3); ok = True\n"
        "    except OSError:\n        ok = False\n"
        "    assert not ok\n"
        "def test_env_isolated():\n    assert 'SUPER_SECRET_HOST_VAR' not in os.environ\n"
        "def test_cannot_write_rootfs():\n"
        "    try:\n        open('/etc/pwned', 'w'); ok = True\n"
        "    except OSError:\n        ok = False\n"
        "    assert not ok\n")
    result = run_test_suite(tmp_path, {"test_frameworks": ["pytest"]})
    assert result["status"] == "passed", result.get("test", {}).get("output")
    assert result["counts"]["passed"] == 4
    assert result["coverage"]["percent"] == 100.0
