"""Security proof-of-concept checks for the release-readiness audit.

Run from auditor/backend:   .venv/bin/python ../docs/audit-evidence/security_pocs.py
Needs semgrep and gitleaks on PATH (as the app itself does). Uses an isolated SQLite DB and
workspace in a temp dir; never executes repository code. Prints one line per check:
  VULNERABLE / HOLDS / INFO  <id> <description> <observed>
"""

import io
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
FIXTURE = BACKEND / "tests" / "fixtures" / "vulnerable_app"
TMP = Path(tempfile.mkdtemp(prefix="auditor-poc-"))
os.environ.update({
    "AUDITOR_ENV": "test", "AUDITOR_DATABASE_URL": f"sqlite:///{TMP}/poc.db",
    "AUDITOR_INLINE_JOBS": "true", "AUDITOR_WORKSPACE_ROOT": str(TMP / "ws"),
    "AUDITOR_OFFLINE": "true", "AUDITOR_LLM_PROVIDER": "none",
})
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from app.analysis.pipeline import run_analysis  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.database import init_db  # noqa: E402
from app.main import create_app  # noqa: E402

init_db()


def report(status, pid, desc, observed=""):
    print(f"{status:<10} {pid:<7} {desc}  ->  {observed}")


def zipped(src: Path, extra: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                zf.write(p, "app-main/" + p.relative_to(src).as_posix())
        for name, text in (extra or {}).items():
            zf.writestr("app-main/" + name, text)
    return buf.getvalue()


def client():
    return TestClient(create_app(), headers={"X-Auditor-Client": "1"})


# --- P1: login lockout of another user (rate-limit key = client IP + email) -----------------
victim = client()
pw = "victim-correct-horse-1"
victim.post("/api/auth/register", json={"email": "victim@example.com", "password": pw})
attacker = client()  # same client IP, as every request is behind the Next.js proxy in Compose
for _ in range(10):
    attacker.post("/api/auth/login", json={"email": "victim@example.com", "password": "wrong-guess-123"})
r = client().post("/api/auth/login", json={"email": "victim@example.com", "password": pw})
report("VULNERABLE" if r.status_code == 429 else "HOLDS", "P1",
       "10 failed logins by anyone lock the victim out for 5 min, from a browser that never signed in",
       f"victim login with correct password from a NEW browser -> {r.status_code}")
r = victim.post("/api/auth/login", json={"email": "victim@example.com", "password": pw})
report("VULNERABLE" if r.status_code == 429 else "HOLDS", "P1b",
       "the same attack locks the victim out of a browser they already signed in with",
       f"victim login with correct password from their KNOWN browser -> {r.status_code}")

# --- P2: account enumeration via registration -----------------------------------------------
r = client().post("/api/auth/register", json={"email": "victim@example.com", "password": "another-long-pass"})
report("VULNERABLE" if r.status_code == 409 else "HOLDS", "P2",
       "registration reveals whether an email has an account", f"{r.status_code} {r.json().get('detail')}")

# --- P3: secrets in non-gitleaks evidence and in the Markdown export --------------------------
c = client()
c.post("/api/auth/register", json={"email": "owner@example.com", "password": "owner-long-password"})
proj = c.post("/api/projects/upload", files={"file": ("a.zip", zipped(FIXTURE))}).json()
aid = proj["audits"][0]["id"]
findings = c.get(f"/api/audits/{aid}/findings").json()
leaky = [f for f in findings if "super-secret-dev-key-123" in f["evidence"]]
report("VULNERABLE" if leaky else "HOLDS", "P3a",
       "hard-coded secret value stored verbatim in finding evidence (non-gitleaks rule)",
       [f"{f['tool']}/{f['rule_id']}" for f in leaky])
md = c.get(f"/api/audits/{aid}/report.md").text
report("VULNERABLE" if "super-secret-dev-key-123" in md else "HOLDS", "P3b",
       "secret value appears in the exported Markdown report", "")
report("HOLDS" if "AKIAQ4ZPSE2ULJ7RTN3X" not in md else "VULNERABLE", "P3c",
       "gitleaks-detected AWS key is masked in the Markdown report", "")

# --- P4: cross-user access (IDOR) on every resource type -------------------------------------
fix = c.post(f"/api/findings/{next(f['id'] for f in findings if f['rule_id'] == 'bare-except')}/fix").json()
other = client()
other.post("/api/auth/register", json={"email": "other@example.com", "password": "other-long-password"})
codes = {
    "project": other.get(f"/api/projects/{proj['id']}").status_code,
    "audit": other.get(f"/api/audits/{aid}").status_code,
    "findings": other.get(f"/api/audits/{aid}/findings").status_code,
    "file": other.get(f"/api/audits/{aid}/files/server/app.py").status_code,
    "fixes": other.get(f"/api/audits/{aid}/fixes").status_code,
    "fix-patch": other.patch(f"/api/fixes/{fix['id']}", json={"status": "approved"}).status_code,
    "finding-fix": other.post(f"/api/findings/{findings[0]['id']}/fix").status_code,
    "explain": other.post(f"/api/audits/{aid}/explain", json={"kind": "overview"}).status_code,
    "rerun": other.post(f"/api/projects/{proj['id']}/audits").status_code,
    "delete": other.delete(f"/api/projects/{proj['id']}").status_code,
    "pr": other.post(f"/api/audits/{aid}/pull-request", json={"github_token": "x" * 30, "confirm": True}).status_code,
}
report("HOLDS" if all(v == 404 for v in codes.values()) else "VULNERABLE", "P4",
       "another user gets 404 on every owned resource", codes)

# --- P5: path traversal / absolute paths in the file viewer and AI target -------------------
c.patch(f"/api/projects/{proj['id']}", json={"llm_consent": True})
paths = ["../../../../etc/passwd", "/etc/passwd", "server/../../../x", "%2e%2e/%2e%2e/etc/passwd"]
fv = {p: c.get(f"/api/audits/{aid}/files/{p}").status_code for p in paths}
report("HOLDS" if all(v in (400, 404) for v in fv.values()) else "VULNERABLE", "P5", "file viewer traversal", fv)

# --- P6: repository can suppress its own findings via scanner config it ships ---------------
base = TMP / "suppress_base"
shutil.copytree(FIXTURE, base)
before = run_analysis(base, Settings(offline=True))
sup = TMP / "suppress_repo"
shutil.copytree(FIXTURE, sup)
(sup / ".semgrepignore").write_text("server/\nweb/\n")
(sup / ".gitleaksignore").write_text("")  # fingerprints filled below
(sup / ".gitleaks.toml").write_text('title = "x"\n[allowlist]\npaths = [\'\'\'.*\'\'\']\n')
after = run_analysis(sup, Settings(offline=True))


def count(res, tool):
    return sum(1 for f in res.findings if f["tool"] == tool)


report("VULNERABLE" if count(after, "semgrep") < count(before, "semgrep") else "HOLDS", "P6a",
       "a repo-supplied .semgrepignore hides semgrep findings",
       f"semgrep findings {count(before, 'semgrep')} -> {count(after, 'semgrep')}; "
       f"score {before.summary['scores']['overall']} -> {after.summary['scores']['overall']}")
report("VULNERABLE" if count(after, "gitleaks") < count(before, "gitleaks") else "HOLDS", "P6b",
       "a repo-supplied .gitleaks.toml allowlist hides secrets",
       f"gitleaks findings {count(before, 'gitleaks')} -> {count(after, 'gitleaks')}")
inline = TMP / "inline_repo"
shutil.copytree(FIXTURE, inline)
app_py = inline / "server" / "app.py"
app_py.write_text(app_py.read_text().replace(
    'cur.execute(f"SELECT * FROM users WHERE id = {uid}")',
    'cur.execute(f"SELECT * FROM users WHERE id = {uid}")  # nosemgrep'))
inl = run_analysis(inline, Settings(offline=True))
has_sqli = any(f["rule_id"] == "py-sql-injection-string-build" for f in inl.findings)
report("VULNERABLE" if not has_sqli else "HOLDS", "P6c",
       "an inline `# nosemgrep` comment hides a SQL injection", f"SQLi still reported: {has_sqli}")

print(f"\ntemp dir: {TMP}")
