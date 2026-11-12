"""Regressions for E-01 (identical defects merged) and E-05 (moved secrets churn)."""

from app.analysis.common import RawFinding
from app.analysis.pipeline import _dedupe, run_analysis
from app.analysis.scanners import gitleaks
from app.core.config import Settings

BLOCK = "\ndef f{n}():\n    try:\n        x = {n}\n    except:\n        pass\n"


def _bare_excepts(root):
    res = run_analysis(root, Settings(), run_scanners=False)
    return [f for f in res.findings if f["rule_id"] == "bare-except"]


def test_identical_defects_are_all_reported(tmp_path):
    (tmp_path / "a.py").write_text("".join(BLOCK.format(n=i) for i in range(3)).replace("x = 1", "x = 0")
                                   .replace("x = 2", "x = 0"))
    found = _bare_excepts(tmp_path)
    assert len(found) == 3  # was 1
    assert len({f["fingerprint"] for f in found}) == 3


def test_a_newly_added_copy_shows_as_one_new(tmp_path):
    src = tmp_path / "a.py"
    src.write_text(BLOCK.format(n=1) + BLOCK.format(n=1).replace("f1", "g1"))
    before = {f["fingerprint"] for f in _bare_excepts(tmp_path)}
    src.write_text(src.read_text() + BLOCK.format(n=1).replace("f1", "h1"))
    after = {f["fingerprint"] for f in _bare_excepts(tmp_path)}
    assert len(after - before) == 1 and before <= after  # was 0 new


def test_first_occurrence_keeps_the_pre_fix_fingerprint():
    raw = RawFinding(tool="quality", rule_id="r", category="code_quality", severity="low",
                     confidence="high", kind="objective", title="t", file="a.py", line=5, evidence="same")
    only = _dedupe([raw])[0]["fingerprint"]
    assert only == raw.fingerprint()
    second = RawFinding(**{**raw.__dict__, "line": 9})
    fps = [d["fingerprint"] for d in sorted(_dedupe([second, raw]), key=lambda d: d["line"])]
    assert fps[0] == raw.fingerprint() and fps[1] != fps[0]


def test_exact_repeats_at_one_location_still_collapse():
    raw = RawFinding(tool="semgrep", rule_id="r", category="security", severity="medium",
                     confidence="high", kind="objective", title="t", file="a.py", line=5, evidence="x")
    worse = RawFinding(**{**raw.__dict__, "severity": "high", "evidence": "y"})
    out = _dedupe([raw, worse])
    assert len(out) == 1 and out[0]["severity"] == "high"


def test_fingerprints_do_not_depend_on_input_order():
    a = [RawFinding(tool="t", rule_id="r", category="security", severity="low", confidence="high",
                    kind="objective", title="t", file="a.py", line=n, evidence="same") for n in (3, 8, 13)]
    one = {(d["line"], d["fingerprint"]) for d in _dedupe(a)}
    two = {(d["line"], d["fingerprint"]) for d in _dedupe(list(reversed(a)))}
    assert one == two


def _gl(line, rule="aws-access-token", path="config.py"):
    return {
        "File": path, "RuleID": rule, "StartLine": line, "EndLine": line, "StartColumn": 1, "EndColumn": 5,
        "Description": "d"}


def test_moved_secret_keeps_its_fingerprint(tmp_path):
    (tmp_path / "config.py").write_text("x = 1\n" * 30)
    before = _dedupe([gitleaks._to_finding(tmp_path, _gl(3))])[0]["fingerprint"]
    after = _dedupe([gitleaks._to_finding(tmp_path, _gl(17))])[0]["fingerprint"]
    assert before == after  # was "resolved + new"


def test_two_identical_secrets_in_one_file_stay_distinct(tmp_path):
    (tmp_path / "config.py").write_text("x = 1\n" * 30)
    out = _dedupe([gitleaks._to_finding(tmp_path, _gl(3)), gitleaks._to_finding(tmp_path, _gl(9))])
    assert len(out) == 2 and len({d["fingerprint"] for d in out}) == 2
