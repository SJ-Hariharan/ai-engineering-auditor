"""Re-verification of fingerprint and scoring claims (release-readiness audit).

Run from auditor/backend:  .venv/bin/python ../docs/audit-evidence/scoring_fingerprint_checks.py
No scanners needed (run_scanners=False); pure analysis + scoring functions.

After the SC-01/SC-02 fix: S3 now reports the critical cap (79.9 C). S1 and S4 still print the old numbers
because these synthetic findings have no file/line and no coverage information, so they do not describe one
root cause or an unanalysed repository. The SC-01/SC-02 measurements with location and coverage are in
scoring_sc01_sc02_checks.py. The original output is kept in scoring_fingerprint_output.txt.
"""

import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.analysis.pipeline import run_analysis  # noqa: E402
from app.analysis.scoring import compute_scores  # noqa: E402
from app.core.config import Settings  # noqa: E402

tmp = Path(tempfile.mkdtemp())

# F1: two identical error-handling blocks in one file -> how many findings?
(tmp / "a.py").write_text(
    "def f():\n    try:\n        x = 1\n    except:\n        pass\n\n"
    "def g():\n    try:\n        y = 2\n    except:\n        pass\n")
res = run_analysis(tmp, Settings(), run_scanners=False)
bare = [f for f in res.findings if f["rule_id"] == "bare-except"]
print(f"F1 identical bare-excepts at lines 4 and 10 -> {len(bare)} finding(s): lines {[f['line'] for f in bare]}")

# F2: rerun comparison after adding a third identical defect: is it 'new'?
fps1 = {f["fingerprint"] for f in res.findings}
(tmp / "a.py").write_text((tmp / "a.py").read_text() + "\ndef h():\n    try:\n        z = 3\n    except:\n        pass\n")
res2 = run_analysis(tmp, Settings(), run_scanners=False)
fps2 = {f["fingerprint"] for f in res2.findings}
print(f"F2 after adding a 3rd bare-except: new fingerprints = {len(fps2 - fps1)}")


def f(sev, conf="high", rule="r", cat="security", kind="objective"):
    return {"category": cat, "severity": sev, "confidence": conf, "rule_id": rule, "kind": kind}


# S1: one root cause reported by several rules
one = compute_scores([f("high", rule="a")])["categories"]["security"]["score"]
four = compute_scores([f("high", rule=r) for r in "abcd"])["categories"]["security"]["score"]
print(f"S1 same issue as 1 rule -> security {one}; as 4 rules -> {four}")

# S2: order dependence
items = [f("high", "high")] * 3 + [f("high", "low")] * 3
scores = set()
rng = random.Random(1)
for _ in range(200):
    rng.shuffle(items)
    scores.add(compute_scores(list(items))["categories"]["security"]["score"])
print(f"S2 same 6 findings in 200 orders -> {len(scores)} distinct security scores, range {min(scores)}..{max(scores)}")

# S3: a lone critical secret and nothing else
print(f"S3 single critical, nothing else -> overall {compute_scores([f('critical')])['overall']} "
      f"grade {compute_scores([f('critical')])['grade']}")

# S4: empty input
print(f"S4 no findings at all (e.g. nothing analysable) -> overall {compute_scores([])['overall']}")
