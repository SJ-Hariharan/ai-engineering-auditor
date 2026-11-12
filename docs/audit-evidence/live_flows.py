"""Live flow checks against a running Docker Compose stack, through the web proxy.

    cd backend && .venv/bin/python -u ../docs/audit-evidence/live_flows.py [http://localhost:3000]

Runs several audits back to back in the same worker (the REL-01 regression), plus auth, ZIP
ingestion, findings, file viewer, fixes, rerun comparison, isolation and deletion.
"""
import io
import secrets
import sys
import time
import zipfile
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
FIX = Path(__file__).resolve().parents[2] / "backend" / "tests" / "fixtures" / "vulnerable_app"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def zipped(src, prefix="vulnerable_app-main/"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                zf.write(p, prefix + p.relative_to(src).as_posix())
    return buf.getvalue()


# LIVE_TLS_VERIFY=0 accepts a self-signed certificate (Caddy's local CA for https://localhost).
VERIFY = __import__("os").environ.get("LIVE_TLS_VERIFY", "1") != "0"


def client():
    return httpx.Client(base_url=BASE, headers={"X-Auditor-Client": "1"}, timeout=120, verify=VERIFY)


def wait(c, aid, limit=300):
    t0 = time.time()
    while time.time() - t0 < limit:
        a = c.get(f"/api/audits/{aid}").json()
        if a["status"] in ("completed", "failed"):
            return a, time.time() - t0
        time.sleep(2)
    return a, time.time() - t0


a = client()
pw, email = secrets.token_urlsafe(16), f"live-{secrets.token_hex(3)}@example.com"
check("register", a.post("/api/auth/register", json={"email": email, "password": pw}).status_code == 201)
check("logout", a.post("/api/auth/logout").status_code == 204)
check("me after logout -> 401", a.get("/api/auth/me").status_code == 401)
check("wrong password -> 401", a.post("/api/auth/login", json={"email": email, "password": "wrong-password-1"}).status_code == 401)
r = a.post("/api/auth/login", json={"email": email, "password": pw})
check("login", r.status_code == 200)
ck = r.headers.get("set-cookie", "").lower()
check("cookie HttpOnly + SameSite=Lax", "httponly" in ck and "samesite=lax" in ck)
check("CSRF header enforced via proxy",
      a.post("/api/projects/github", json={"url": "https://github.com/pallets/markupsafe"},
             headers={"X-Auditor-Client": ""}).status_code == 403)

# Several audits back to back in the same worker process (REL-01).
for i, repo in enumerate(["https://github.com/pallets/markupsafe", "https://github.com/pallets/itsdangerous"], 1):
    p = a.post("/api/projects/github", json={"url": repo}).json()
    au, secs = wait(a, p["audits"][0]["id"])
    check(f"sequential GitHub audit #{i} ({repo.split('/')[-1]})", au["status"] == "completed",
          f"{au['status']} {au.get('error') or ''} {secs:.0f}s")

data = zipped(FIX)
r = a.post("/api/projects/upload", files={"file": ("vuln.zip", data, "application/zip")})
check("ZIP upload", r.status_code == 201, r.status_code)
proj = r.json()
aid = proj["audits"][0]["id"]
au, secs = wait(a, aid)
check("ZIP audit completed (3rd job in this worker)", au["status"] == "completed", f"{au['status']} {au.get('error') or ''} {secs:.0f}s")
s = au["summary"]
check("all scanners ok", all(x["status"] == "ok" for x in s["scanners"]), [(x["name"], x["status"]) for x in s["scanners"]])
fs = a.get(f"/api/audits/{aid}/findings").json()
rules = {f["rule_id"] for f in fs}
check("findings returned", len(fs) > 20, len(fs))
for rule in ("py-sql-injection-string-build", "aws-access-token", "circular-dependency", "unresolved-import"):
    check(f"detects {rule}", rule in rules)
env = a.get(f"/api/audits/{aid}/files/.env").json()
check("file viewer masks gitleaks secret", "AKIAQ4ZPSE2ULJ7RTN3X" not in env["content"])
check("file viewer traversal blocked", a.get(f"/api/audits/{aid}/files/..%2f..%2f..%2fetc%2fpasswd").status_code in (400, 404))
md = a.get(f"/api/audits/{aid}/report.md")
check("report.md export (gitleaks secret masked)", md.status_code == 200 and "AKIAQ4ZPSE2ULJ7RTN3X" not in md.text)

bare = next(f for f in fs if f["rule_id"] == "bare-except")
fx = a.post(f"/api/findings/{bare['id']}/fix").json()
check("deterministic fix diff", "+    except Exception:" in fx.get("diff", ""))
check("approve fix", a.patch(f"/api/fixes/{fx['id']}", json={"status": "approved"}).json().get("status") == "approved")
check("PR refused for ZIP project", a.post(f"/api/audits/{aid}/pull-request",
                                          json={"github_token": "x" * 30, "confirm": True}).status_code == 422)
cyc = next(f for f in fs if f["rule_id"] == "circular-dependency")
check("AI fix blocked without consent", a.post(f"/api/findings/{cyc['id']}/fix").status_code == 403)
check("sandbox disabled in Compose -> 503", a.post(f"/api/audits/{aid}/tests/run").status_code == 503)

r = a.post(f"/api/projects/{proj['id']}/audits", files={"file": ("v.zip", data)})
check("rerun accepted", r.status_code == 201, r.status_code)
au2, secs = wait(a, r.json()["id"])
comp = (au2.get("summary") or {}).get("comparison") or {}
check("rerun completed with comparison (4th job)", au2["status"] == "completed" and comp.get("previous_audit_id") == aid,
      {k: comp.get(k) for k in ("new", "resolved", "persisting")})

b = client()
b.post("/api/auth/register", json={"email": f"other-{secrets.token_hex(3)}@example.com", "password": secrets.token_urlsafe(16)})
codes = [b.get(u).status_code for u in (f"/api/projects/{proj['id']}", f"/api/audits/{aid}",
                                        f"/api/audits/{aid}/findings", f"/api/audits/{aid}/files/server/app.py")]
check("cross-user isolation (404)", all(c == 404 for c in codes), codes)
check("cross-user cannot change a fix", b.patch(f"/api/fixes/{fx['id']}", json={"status": "rejected"}).status_code == 404)
check("delete project", a.delete(f"/api/projects/{proj['id']}").status_code == 204)
check("deleted audit is gone", a.get(f"/api/audits/{aid}").status_code == 404)
print(f"\n{sum(results)}/{len(results)} checks passed", flush=True)
