"""SEC-01: a scanned repository must not be able to suppress its own findings."""

import shutil
from pathlib import Path

import pytest

from app.analysis.scanners import deps, gitleaks, semgrep
from app.analysis.scanners.base import SCANNER_CONFIG_DIR
from app.analysis.scanners.suppressions import find_suppressions
from app.core.config import Settings
from app.sandbox.process import ProcessResult
from tests.conftest import FIXTURES, requires_scanners

SQLI_LINE = 'cur.execute(f"SELECT * FROM users WHERE id = {uid}")'


@pytest.fixture
def repo(tmp_path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURES / "vulnerable_app", dest)
    return dest


def _suppress_everything(root: Path) -> None:
    (root / ".semgrepignore").write_text("server/\nweb/\n*.py\n*.js\n*.tsx\n")
    app_py = root / "server" / "app.py"
    app_py.write_text(app_py.read_text().replace(SQLI_LINE, SQLI_LINE + "  # nosemgrep"))
    (root / ".gitleaks.toml").write_text(
        'title = "repo"\n[allowlist]\npaths = [\'\'\'.*\'\'\']\nregexes = [\'\'\'.*\'\'\']\n')
    (root / ".gitleaksignore").write_text(".env:aws-access-token:1\n.env:github-pat:2\n")
    env = root / ".env"
    env.write_text("\n".join(line + "  # gitleaks:allow" for line in env.read_text().splitlines()) + "\n")
    (root / ".trivyignore").write_text("DS-0002\nDS-0026\n")
    (root / "trivy.yaml").write_text("severity:\n  - CRITICAL\nmisconfiguration:\n  scanners: []\n")
    (root / "osv-scanner.toml").write_text('[[IgnoredVulns]]\nid = "GHSA-562c-5r94-xh97"\n')


def test_suppression_inventory_lists_files_and_inline_markers(repo):
    _suppress_everything(repo)
    s = find_suppressions(repo)
    files = {f["file"] for f in s["files"]}
    assert {".semgrepignore", ".gitleaks.toml", ".gitleaksignore", ".trivyignore", "trivy.yaml",
            "osv-scanner.toml"} <= files
    assert s["inline"]["nosemgrep"] == 1 and s["inline"]["gitleaks:allow"] == 2
    assert s["honoured"] is False and s["total"] >= 9


def test_clean_repo_reports_no_suppressions(repo):
    assert find_suppressions(repo)["total"] == 0


@requires_scanners
def test_semgrep_ignores_repo_semgrepignore_and_nosemgrep(repo):
    _suppress_everything(repo)
    result = semgrep.run(repo, Settings(offline=True))
    assert result.status == "ok", result.message
    rules = {f.rule_id for f in result.findings}
    assert "py-sql-injection-string-build" in rules  # despite `# nosemgrep` on that line
    assert len(result.findings) >= 15  # despite .semgrepignore excluding every source folder


@requires_scanners
def test_semgrep_still_skips_dependency_folders(repo):
    nm = repo / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("eval(userInput);\n")
    result = semgrep.run(repo, Settings(offline=True))
    assert not any((f.file or "").startswith("node_modules/") for f in result.findings)


@requires_scanners
def test_gitleaks_ignores_repo_config_ignorefile_and_allow_comments(repo):
    _suppress_everything(repo)
    result = gitleaks.run(repo, Settings(offline=True))
    assert result.status == "ok", result.message
    assert {f.rule_id for f in result.findings} >= {"aws-access-token", "github-pat"}
    # The repo's .gitleaksignore is only moved aside during the scan, then restored unchanged.
    assert (repo / ".gitleaksignore").read_text() == ".env:aws-access-token:1\n.env:github-pat:2\n"
    assert not list(repo.glob(".gitleaksignore.auditor-*"))


def test_trivy_and_osv_are_pointed_at_app_owned_config(repo, monkeypatch):
    """Trivy/OSV need a vulnerability DB or network, so check the arguments they receive."""
    seen: list[list[str]] = []

    def fake_run_tool(argv, **kwargs):
        seen.append(argv)
        return ProcessResult(0, "{}", "")

    monkeypatch.setattr(deps, "run_tool", fake_run_tool)
    monkeypatch.setattr("app.analysis.scanners.base.tool_version", lambda *a: "test")
    deps.run_trivy(repo, Settings(offline=False))
    deps.run_osv(repo, Settings(offline=False))
    trivy_argv = next(a for a in seen if a[0] == "trivy")
    osv_argv = next(a for a in seen if a[0] == "osv-scanner")
    assert trivy_argv[trivy_argv.index("--ignorefile") + 1] == ""
    assert trivy_argv[trivy_argv.index("--config") + 1] == ""
    assert osv_argv[osv_argv.index("--config") + 1] == str(SCANNER_CONFIG_DIR / "osv-scanner.toml")
    assert "--no-ignore" in osv_argv  # a .gitignore must not hide lockfiles from OSV
    assert (SCANNER_CONFIG_DIR / "osv-scanner.toml").is_file()
    assert not (SCANNER_CONFIG_DIR / "gitleaks-ignore" / ".gitleaksignore").exists()
