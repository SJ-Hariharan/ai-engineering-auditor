"""Live checks for SEC-02 (no login lockout) and SEC-04 (body limit) through the Next.js proxy.

Run from auditor/backend against a running Compose stack:
    .venv/bin/python ../docs/audit-evidence/live_abuse_checks.py http://localhost:3000
"""

import os
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
H = {"X-Auditor-Client": "1"}
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


email = f"victim-{os.urandom(4).hex()}@example.com"
pw = "correct-horse-battery"
victim = httpx.Client(timeout=120)
r = victim.post(f"{BASE}/api/auth/register", json={"email": email, "password": pw}, headers=H)
check("victim registers", r.status_code == 201, r.status_code)
check("device cookie set through the proxy", any(c.name == "auditor_device" for c in victim.cookies.jar), "")

attacker = httpx.Client(timeout=30)
codes = [attacker.post(f"{BASE}/api/auth/login", json={"email": email, "password": "wrong-password-x"},
                       headers=H).status_code for _ in range(15)]
check("attacker throttled after 10 failures", codes[:10] == [401] * 10 and set(codes[10:]) == {429}, codes)
spoof = attacker.post(f"{BASE}/api/auth/login", json={"email": email, "password": "wrong-password-x"},
                      headers={**H, "X-Forwarded-For": "203.0.113.9"}).status_code
check("spoofed X-Forwarded-For does not reset the attacker's budget", spoof == 429, spoof)
r = victim.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, headers=H)
check("victim (known browser) still logs in during the attack", r.status_code == 200, r.status_code)

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
