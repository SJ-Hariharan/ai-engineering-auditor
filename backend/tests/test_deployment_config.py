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


class _ComposeLoader(yaml.SafeLoader):
    """Understands Compose's !reset / !override tags."""


_ComposeLoader.add_constructor("!reset", lambda loader, node: None)
_ComposeLoader.add_constructor("!override", lambda loader, node: loader.construct_object(node.value[0])
                               if isinstance(node.value, list) and node.value else None)


def test_production_overlay_exposes_only_https_ingress():
    prod = yaml.load((ROOT / "docker-compose.prod.yml").read_text(), Loader=_ComposeLoader)["services"]
    assert prod["web"]["ports"] is None  # !reset: the plain-HTTP UI port is not published
    assert prod["caddy"]["ports"] == ["80:80", "443:443", "443:443/udp"]
    assert prod["caddy"]["restart"] == "unless-stopped" and "healthcheck" in prod["caddy"]
    assert prod["caddy"]["depends_on"]["web"]["condition"] == "service_healthy"
    assert prod["caddy"]["cap_drop"] == ["ALL"] and prod["caddy"]["cap_add"] == ["NET_BIND_SERVICE"]


def test_client_ip_is_trusted_only_with_the_ingress_that_overwrites_it():
    prod = yaml.load((ROOT / "docker-compose.prod.yml").read_text(), Loader=_ComposeLoader)["services"]
    assert prod["api"]["environment"]["AUDITOR_TRUST_CLIENT_IP_HEADER"] == "true"
    assert "AUDITOR_TRUST_CLIENT_IP_HEADER" not in str(_compose()["api"].get("environment", {}))
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text()
    assert "header_up X-Auditor-Client-IP {remote_host}" in caddyfile
    assert "COPY Caddyfile" in (ROOT / "deploy" / "Dockerfile.caddy").read_text()
