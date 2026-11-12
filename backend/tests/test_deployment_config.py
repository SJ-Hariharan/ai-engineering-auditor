"""Static checks of the deployment files (AC1, AC2). The live behaviour is checked against Compose."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _compose(name="docker-compose.yml") -> dict:
    return yaml.safe_load((ROOT / name).read_text())["services"]


def test_every_service_restarts_and_long_running_ones_report_health():
    services = _compose()
    for name, svc in services.items():
        assert svc.get("restart") == "unless-stopped", name
    for name in ("db", "redis", "api", "worker", "web"):
        assert "healthcheck" in services[name], name


def test_dependents_wait_for_healthy_dependencies():
    s = _compose()
    assert s["api"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert s["api"]["depends_on"]["redis"]["condition"] == "service_healthy"
    assert s["worker"]["depends_on"]["redis"]["condition"] == "service_healthy"
    assert s["web"]["depends_on"]["api"]["condition"] == "service_healthy"


def test_only_the_web_ui_is_published_and_only_on_loopback():
    for name, svc in _compose().items():
        ports = svc.get("ports", [])
        if name == "web":
            assert ports == ["127.0.0.1:3000:3000"]
        else:
            assert ports == [], name
