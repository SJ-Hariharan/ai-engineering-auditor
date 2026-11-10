"""Before/after evidence for SC-01 and SC-02 (scoring).

Run from auditor/backend:  .venv/bin/python ../docs/audit-evidence/scoring_sc01_sc02_checks.py
Output is saved as scoring_sc01_sc02_output.txt.

Part A uses synthetic findings and needs no scanners. Part B runs the real pipeline on the test
fixture with all scanners, then with Semgrep forced to fail (needs semgrep/gitleaks/osv-scanner/trivy
on the host; run outside the Claude command sandbox, where Semgrep crashes). Part C re-scores the
findings stored in benchmarks/results/*.json with the old and new formulas, so the scoring change is
measured on identical findings, independent of scanner or advisory-database drift.

"before" = a frozen copy of compute_scores as it was before the fix (legacy_compute_scores below).
"""

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.analysis import pipeline  # noqa: E402
from app.analysis.scanners.base import ScannerResult  # noqa: E402
from app.analysis.scoring import (  # noqa: E402
    SECURITY_SCANNERS,
    SEVERITY_POINTS,
    WEIGHTS,
    build_coverage,
    compute_scores,
    grade,
)
from app.core.config import Settings  # noqa: E402

CONF = {"high": 1.0, "medium": 0.7, "low": 0.4}


def legacy_compute_scores(findings):
    """compute_scores before SC-01/SC-02 (verbatim logic)."""
    seen, totals = defaultdict(int), defaultdict(float)
    for f in sorted(findings, key=lambda f: -SEVERITY_POINTS[f["severity"]]):
        if f["category"] not in WEIGHTS:
            continue
        seen[(f["category"], f["rule_id"])] += 1
        totals[f["category"]] += SEVERITY_POINTS[f["severity"]] * CONF.get(f["confidence"], 0.7) / seen[
            (f["category"], f["rule_id"])]
    cats = {c: round(100 * math.exp(-totals[c] / 60), 1) for c in WEIGHTS}
    overall = round(sum(cats[c] * w for c, w in WEIGHTS.items()), 1)
    return {"overall": overall, "grade": grade(overall), "categories": cats}


def f(sev="high", conf="high", rule="r", cat="security", file="app.py", line=10, tool="semgrep"):
    return {"category": cat, "severity": sev, "confidence": conf, "rule_id": rule, "kind": "objective",
            "file": file, "line": line, "tool": tool, "fingerprint": f"{tool}|{rule}|{file}|{line}"}


ALL_OK = [{"name": n, "status": "ok"} for n in SECURITY_SCANNERS]
FULL = build_coverage(10, ALL_OK)


def fmt(s):
    o = s["overall"]
    caps = ", ".join(f"{c['reason']}≤{c['max']}" for c in s.get("caps", [])) or "none"
    extra = f" (uncapped {s['uncapped_overall']}, caps: {caps})" if "caps" in s else ""
    return f"{o if o is not None else 'N/A'} {s['grade']}{extra}"


print("== A. Synthetic cases ==")
# SC-02: the PRIORITIZED_FIXES measurement (same issue as 1 rule vs 4 rules), now with a location.
one, four = [f(rule="a")], [f(rule=r) for r in "abcd"]
print(f"SC-02 same location, 1 rule  -> security before {legacy_compute_scores(one)['categories']['security']}, "
      f"after {compute_scores(one, FULL)['categories']['security']['score']}")
print(f"SC-02 same location, 4 rules -> security before {legacy_compute_scores(four)['categories']['security']}, "
      f"after {compute_scores(four, FULL)['categories']['security']['score']}")
apart = [f(rule=r, line=i) for i, r in enumerate("abcd", 1)]
print(f"SC-02 control: 4 rules on 4 different lines -> after {compute_scores(apart, FULL)['categories']['security']['score']}"
      " (distinct issues still each penalised)")
mixed = [f("high", rule="semgrep-secret"), f("critical", rule="aws-key", tool="gitleaks")]
print(f"SC-02 gitleaks critical + semgrep high on one line -> after security "
      f"{compute_scores(mixed, FULL)['categories']['security']['score']} "
      f"(= lone critical {compute_scores(mixed[1:], FULL)['categories']['security']['score']})")

crit = [f("critical", rule="aws-key", tool="gitleaks")]
print(f"SC-01 lone high-confidence critical secret -> before {fmt(legacy_compute_scores(crit))}, "
      f"after {fmt(compute_scores(crit, FULL))}")
print(f"SC-01 no findings, nothing analysable -> before {fmt(legacy_compute_scores([]))}, "
      f"after {fmt(compute_scores([], build_coverage(0, None)))}")
go = [f("high", rule="aws-key", tool="gitleaks", file="main.go")]
print(f"SC-01 Go-only repo (no parsed files), 1 high secret -> before {fmt(legacy_compute_scores(go))}, "
      f"after {fmt(compute_scores(go, build_coverage(0, ALL_OK)))}")
failed = [s if s["name"] != "semgrep" else {"name": "semgrep", "status": "failed"} for s in ALL_OK]
print(f"SC-01 no findings, Semgrep failed -> before {fmt(legacy_compute_scores([]))}, "
      f"after {fmt(compute_scores([], build_coverage(10, failed)))}")

print("\n== B. Real pipeline on backend/tests/fixtures/vulnerable_app ==")
fixture = ROOT / "backend" / "tests" / "fixtures" / "vulnerable_app"
real_semgrep = pipeline.semgrep.run


def run(label):
    r = pipeline.run_analysis(fixture, Settings(offline=True))
    s = r.summary["scores"]
    status = {x["name"]: x["status"] for x in r.summary["scanners"]}
    print(f"{label}: {len(r.findings)} findings, scanners {status}")
    print(f"   before {fmt(legacy_compute_scores(r.findings))}; after {fmt(s)}; "
          f"security {s['categories']['security']['score']} ({s['categories']['security']['status']}); "
          f"merged duplicates {sum(c['merged_duplicates'] for c in s['categories'].values())}")


run("all scanners (offline: OSV skipped by configuration)")


def failing_semgrep(root, settings):
    return ScannerResult(name="semgrep", status="failed", message="forced failure for this check")


pipeline.semgrep.run = failing_semgrep
try:
    run("Semgrep forced to fail")
finally:
    pipeline.semgrep.run = real_semgrep

print("\n== C. Stored benchmark findings re-scored (benchmarks/results/*.json) ==")
print("repo | findings | merged | before | after | security before→after | caps")
for p in sorted((ROOT / "benchmarks" / "results").glob("*.json")):
    d = json.loads(p.read_text())
    if "findings" not in d:
        continue
    new = compute_scores(d["findings"], build_coverage(1, d["scanners"]))
    old = legacy_compute_scores(d["findings"])
    merged = sum(c["merged_duplicates"] for c in new["categories"].values())
    caps = ",".join(c["reason"] for c in new["caps"]) or "-"
    print(f"{p.stem} | {len(d['findings'])} | {merged} | {old['overall']} {old['grade']} | "
          f"{new['overall']} {new['grade']} | {old['categories']['security']}→"
          f"{new['categories']['security']['score']} | {caps}")
