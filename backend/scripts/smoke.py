"""End-to-end smoke test against a running API + worker.

    uv run python scripts/smoke.py --api http://localhost:8000 --github https://github.com/pallets/itsdangerous
"""

import argparse
import secrets
import sys
import time

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--github", default="https://github.com/pallets/itsdangerous")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()
    c = httpx.Client(base_url=args.api, headers={"X-Auditor-Client": "1"}, timeout=60)
    email = f"smoke-{secrets.token_hex(4)}@example.com"
    c.post("/api/auth/register", json={"email": email, "password": secrets.token_urlsafe(16)}).raise_for_status()
    project = c.post("/api/projects/github", json={"url": args.github}).raise_for_status().json()
    audit_id = project["audits"][0]["id"]
    print(f"project {project['name']} audit {audit_id}")
    deadline = time.time() + args.timeout
    last = None
    while time.time() < deadline:
        a = c.get(f"/api/audits/{audit_id}").raise_for_status().json()
        if a["stage"] != last:
            print(f"  {a['status']:<10} {a['stage'] or ''}")
            last = a["stage"]
        if a["status"] in ("completed", "failed"):
            break
        time.sleep(2)
    if a["status"] != "completed":
        print("FAILED:", a["error"])
        return 1
    s = a["summary"]
    print(f"commit {a['commit_sha']}  score {s['scores']['overall']} ({s['scores']['grade']})")
    for name, cat in s["scores"]["categories"].items():
        print(f"  {name:<16} {cat['score']:>5}  {cat['counts']}")
    for sc in s["scanners"]:
        print(f"  scanner {sc['name']:<12} {sc['status']:<8} {sc['findings']:>3} findings {sc['message']}")
    print("overview:", " ".join(s["overview"]["paragraphs"]))
    findings = c.get(f"/api/audits/{audit_id}/findings").raise_for_status().json()
    print(f"{len(findings)} findings, top 12:")
    for f in findings[:12]:
        loc = f"{f['file']}:{f['line']}" if f["line"] else (f["file"] or "repo")
        print(f"  [{f['severity']:<8}] {f['kind']:<10} {f['rule_id']:<28} {loc}  {f['title'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
