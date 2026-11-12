"""Live checks for SEC-02 (no login lockout) and SEC-04 (body limit) through the running stack.

Run from auditor/backend against a running Compose stack:
    .venv/bin/python ../docs/audit-evidence/live_abuse_checks.py http://localhost:3000
Production overlay (Caddy on https://localhost with its local CA):
    LIVE_TLS_VERIFY=0 LIVE_COMPOSE="docker compose -p NAME -f docker-compose.yml -f docker-compose.prod.yml" \
        .venv/bin/python ../docs/audit-evidence/live_abuse_checks.py https://localhost
With LIVE_COMPOSE set, the "new browser on another IP" check sends a login from inside the Caddy
container, whose address (127.0.0.1) differs from the host's.
"""

import os
import shlex
import subprocess
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
VERIFY = os.environ.get("LIVE_TLS_VERIFY", "1") != "0"
COMPOSE = os.environ.get("LIVE_COMPOSE", "")
H = {"X-Auditor-Client": "1"}
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


email = f"victim-{os.urandom(4).hex()}@example.com"
pw = "correct-horse-battery"
victim = httpx.Client(timeout=120, verify=VERIFY)
r = victim.post(f"{BASE}/api/auth/register", json={"email": email, "password": pw}, headers=H)
check("victim registers", r.status_code == 201, r.status_code)
check("device cookie set through the proxy", any(c.name == "auditor_device" for c in victim.cookies.jar), "")

attacker = httpx.Client(timeout=30, verify=VERIFY)
codes = [attacker.post(f"{BASE}/api/auth/login", json={"email": email, "password": "wrong-password-x"},
                       headers=H).status_code for _ in range(15)]
check("attacker throttled after 10 failures", codes[:10] == [401] * 10 and set(codes[10:]) == {429}, codes)
spoof = attacker.post(f"{BASE}/api/auth/login", json={"email": email, "password": "wrong-password-x"},
                      headers={**H, "X-Forwarded-For": "203.0.113.9"}).status_code
check("spoofed X-Forwarded-For does not reset the attacker's budget", spoof == 429, spoof)
r = victim.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, headers=H)
check("victim (known browser) still logs in during the attack", r.status_code == 200, r.status_code)

if COMPOSE:  # production overlay: Caddy sets X-Auditor-Client-IP and the API trusts it
    spoofs = {attacker.post(f"{BASE}/api/auth/login", json={"email": email, "password": "wrong-password-x"},
                            headers={**H, "X-Auditor-Client-IP": f"198.51.100.{i}"}).status_code for i in range(5)}
    check("spoofed X-Auditor-Client-IP is overwritten by the ingress", spoofs == {429}, spoofs)
    body = '{"email": "%s", "password": "%s"}' % (email, pw)
    cmd = shlex.split(COMPOSE) + ["exec", "-T", "caddy", "curl", "-sk", "-o", "/dev/null", "-w", "%{http_code}",
                                  "-H", "X-Auditor-Client: 1", "-H", "content-type: application/json",
                                  "--data", body, "https://localhost/api/auth/login"]
    code = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()
    check("victim on a NEW browser from another IP logs in during the attack", code == "200", code)

big = 60 * 1024 * 1024
t = time.monotonic()
try:
    r = victim.post(f"{BASE}/api/projects/upload", headers=H,
                    files={"file": ("big.zip", b"PK\x03\x04" + b"0" * big, "application/zip")})
    code = r.status_code
except httpx.HTTPError as exc:  # the server may close the connection after answering 413
    code = f"connection closed ({type(exc).__name__})"
check("60 MB upload rejected", code == 413 or str(code).startswith("connection closed"),
      f"{code} in {time.monotonic() - t:.1f}s")
projects = victim.get(f"{BASE}/api/projects", headers=H).json()
check("no project created by the oversized upload", projects == [], len(projects))

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)
