"""DET-11: advisories for packages reachable only through dev/test dependencies (per the lockfile)."""

import json

from app.analysis import inventory as inv_mod
from app.analysis.common import RawFinding
from app.analysis.scanners.deps import classify_dependency_findings

UV_LOCK = """
version = 1

[[package]]
name = "myapp"
version = "0.1.0"
source = { editable = "." }
dependencies = [{ name = "requests" }]

[package.optional-dependencies]
docs = [{ name = "sphinx" }]
server = [{ name = "gunicorn" }]

[package.dev-dependencies]
dev = [{ name = "pytest" }, { name = "tox" }]

[[package]]
name = "requests"
version = "2.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "certifi" }, { name = "urllib3" }]

[[package]]
name = "tox"
version = "4.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "virtualenv" }, { name = "certifi" }]

[[package]]
name = "virtualenv"
version = "20.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "Platform_Dirs" }]

[[package]]
name = "sphinx"
version = "8.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [{ name = "jinja2" }]
"""


def _inv(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    return inv_mod.walk(tmp_path, 1_000_000)


def test_uv_lock_dev_only_closure(tmp_path):
    inv = _inv(tmp_path, {"uv.lock": UV_LOCK})
    assert {"virtualenv", "platform-dirs", "jinja2"} <= inv.dev_only_transitive  # tox → virtualenv; docs group
    assert "certifi" not in inv.dev_only_transitive  # also reachable from runtime (requests): stays runtime
    assert "urllib3" not in inv.dev_only_transitive and "gunicorn" not in inv.dev_only_transitive


def test_package_lock_dev_flag(tmp_path):
    lock = {"lockfileVersion": 3, "packages": {
        "": {"name": "web"},
        "node_modules/react": {"version": "19.0.0"},
        "node_modules/eslint": {"version": "9.0.0", "dev": True},
        "node_modules/eslint/node_modules/minimatch": {"version": "3.0.0", "dev": True},
        "node_modules/@types/node": {"version": "22.0.0", "dev": True}}}
    inv = _inv(tmp_path, {"package-lock.json": json.dumps(lock)})
    assert {"minimatch", "@types/node"} <= inv.dev_only_transitive
    assert "react" not in inv.dev_only_transitive


def test_malformed_lockfile_is_ignored(tmp_path):
    inv = _inv(tmp_path, {"uv.lock": "not = [valid", "package-lock.json": "{"})
    assert inv.dev_only_transitive == set()


def _advisory(name, severity="critical"):
    return RawFinding(tool="osv-scanner", rule_id="vulnerable-dependency", category="security", severity=severity,
                      confidence="high", kind="objective", title=f"{name} has a vulnerability", file="uv.lock",
                      fingerprint_key=f"pypi|{name}|1.0")


def test_dev_only_transitive_advisory_is_lowered_and_explained():
    f = _advisory("virtualenv")
    classify_dependency_findings([f], runtime=set(), dev=set(), dev_only_transitive={"virtualenv"})
    assert (f.severity, f.confidence) == ("high", "medium")
    assert "(dev tooling, transitive)" in f.title and "development/test dependencies" in f.explanation


def test_runtime_and_unknown_transitives_are_not_lowered():
    direct, other = _advisory("requests"), _advisory("certifi")
    classify_dependency_findings([direct, other], runtime={"requests"}, dev=set(), dev_only_transitive={"tox"})
    assert direct.severity == "critical" and direct.confidence == "high"
    assert other.severity == "critical" and other.confidence == "medium" and "(transitive)" in other.title


BUN_LOCK = """{
  "lockfileVersion": 1,
  "workspaces": {
    "": { "name": "root", },
    "frontend": {
      "name": "frontend",
      "dependencies": { "react-router": "^1.0.0", },
      "devDependencies": { "react-email": "^6.0.0", "eslint": "^9", },
    },
  },
  "packages": {
    "react-router": ["react-router@1.0.0", "", { "dependencies": { "seroval": "^1.6.0" } }, "sha512-a"],
    "seroval": ["seroval@1.6.8", "", {}, "sha512-b"],
    "react-email": ["react-email@6.11.3", "", { "dependencies": { "glob": "^13", "seroval": "^1" } }, "sha512-c"],
    "glob": ["glob@13.0.6", "", { "dependencies": { "minimatch": "^10" } }, "sha512-d"],
    "minimatch": ["minimatch@10.2.6", "", {}, "sha512-e"],
    "eslint": ["eslint@9.0.0", "", { "dependencies": { "minimatch": "^3" } }, "sha512-f"],
    "eslint/minimatch": ["minimatch@3.1.2", "", {}, "sha512-g"],
  },
}
"""


def test_bun_lock_dev_only_closure(tmp_path):
    inv = _inv(tmp_path, {"bun.lock": BUN_LOCK})
    assert {"glob", "minimatch", "react-email", "eslint"} <= inv.dev_only_transitive
    assert "seroval" not in inv.dev_only_transitive  # runtime path via react-router wins
    assert "react-router" not in inv.dev_only_transitive
    assert "bun.lock" in inv.manifests
