"""Regression tests for SC-01 (unanalysed categories, failed scanners, critical findings) and
SC-02 (one root cause reported by several rules counted several times). Pure functions; no scanners."""

import itertools
import math
import random

import pytest

from app.analysis.common import RawFinding
from app.analysis.pipeline import _dedupe, run_analysis
from app.analysis.scoring import (
    CRITICAL_CAP,
    INCOMPLETE_CAP,
    SECURITY_SCANNERS,
    WEIGHTS,
    build_coverage,
    compute_scores,
    grade,
)
from app.core.config import Settings

ALL_OK = [{"name": n, "status": "ok"} for n in SECURITY_SCANNERS]


def f(sev="high", conf="high", rule="r", cat="security", file="app.py", line=10, tool="semgrep", fp=None):
    return {"category": cat, "severity": sev, "confidence": conf, "rule_id": rule, "kind": "objective",
            "file": file, "line": line, "tool": tool, "fingerprint": fp or f"{tool}|{rule}|{file}|{line}"}


def sec(findings, coverage=None):
    return compute_scores(findings, coverage)["categories"]["security"]["score"]


def full_coverage():
    return build_coverage(10, ALL_OK)


# ---------------------------------------------------------------- SC-02: one root cause, one penalty

def test_same_location_reported_by_several_rules_counts_once():
    one = sec([f(rule="a")])
    four = sec([f(rule=r) for r in "abcd"])
    assert one == four == 81.9  # was 44.9 for four rules (PRIORITIZED_FIXES SC-02)


def test_same_location_from_several_tools_keeps_most_severe():
    # Gitleaks (critical) and a Semgrep secret rule (high) on the same line → scored as the critical.
    pair = [f("high", rule="hardcoded-secret", tool="semgrep"), f("critical", rule="aws-key", tool="gitleaks")]
    assert sec(pair) == sec([f("critical", rule="aws-key", tool="gitleaks")])
    # Higher confidence wins between equal severities.
    assert sec([f("high", "low", rule="a"), f("high", "high", rule="b")]) == sec([f("high", "high")])


def test_choice_of_kept_finding_is_order_independent():
    group = [f("high", "high", rule="b"), f("high", "high", rule="a"), f("medium", rule="c"),
             f("critical", "medium", rule="d"), f("low", rule="e", line=11)]
    results = {repr(compute_scores(list(p), full_coverage())) for p in itertools.permutations(group)}
    assert len(results) == 1


def test_distinct_occurrences_are_still_penalised():
    one = sec([f(rule="sqli", line=10)])
    three = sec([f(rule="sqli", line=n) for n in (10, 20, 30)])
    other_file = sec([f(rule="sqli", line=10), f(rule="sqli", file="b.py", line=10)])
    assert three < one and other_file < one
    # Different rules on different lines are different issues.
    assert sec([f(rule="a", line=1), f(rule="b", line=2)]) < sec([f(rule="a", line=1)])


def test_same_location_in_different_categories_is_not_merged():
    s = compute_scores([f(cat="security"), f(cat="code_quality", rule="q")])["categories"]
    assert s["security"]["deduction"] > 0 and s["code_quality"]["deduction"] > 0


def test_findings_without_a_line_are_never_merged():
    # Two vulnerable packages in the same manifest: file-level, no line → two root causes.
    deps = [f(rule="vulnerable-dependency", file="uv.lock", line=None, fp="a"),
            f(rule="vulnerable-dependency", file="uv.lock", line=None, fp="b")]
    assert sec(deps) < sec(deps[:1])
    repo_level = [f(rule="x", file=None, line=None, fp="1"), f(rule="y", file=None, line=None, fp="2")]
    assert sec(repo_level) < sec(repo_level[:1])


def test_counts_keep_every_reported_finding_and_report_merges():
    c = compute_scores([f(rule=r) for r in "abc"] + [f(rule="a", line=99)])["categories"]["security"]
    assert c["counts"] == {"high": 4}
    assert c["merged_duplicates"] == 2


def test_dedupe_keeps_every_rule_at_a_location_in_the_report():
    def raw(rule, tool, sev, evidence="x"):
        return RawFinding(tool=tool, rule_id=rule, category="security", severity=sev, confidence="high",
                          kind="objective", title=rule, file="src/server.js", line=50, evidence=evidence)
    out = _dedupe([raw("js-eval", "semgrep", "high"), raw("js-reflected-xss-express", "semgrep", "high"),
                   raw("js-eval", "semgrep", "high"),  # exact repeat → dropped
                   raw("js-eval", "semgrep", "critical", evidence="y")])  # same rule+line → most severe
    assert sorted((d["rule_id"], d["severity"]) for d in out) == [("js-eval", "critical"),
                                                                 ("js-reflected-xss-express", "high")]


# ---------------------------------------------------------------- SC-01: N/A, renormalising, caps

def test_lone_critical_secret_cannot_grade_better_than_c():
    s = compute_scores([f("critical", rule="aws-key", tool="gitleaks")], full_coverage())
    assert s["uncapped_overall"] == 89.8  # was the final score before the fix (grade B)
    assert s["overall"] == CRITICAL_CAP and s["grade"] == "C"
    assert [c["reason"] for c in s["caps"]] == ["critical"]


def test_critical_cap_needs_high_confidence_and_never_raises_a_score():
    medium = compute_scores([f("critical", "medium")], full_coverage())
    assert medium["caps"] == [] and medium["overall"] == medium["uncapped_overall"]
    many = [f("critical", rule=f"r{i}", line=i) for i in range(1, 8)]
    low = compute_scores(many, full_coverage())
    assert low["overall"] == low["uncapped_overall"] < CRITICAL_CAP


def test_category_with_nothing_analysed_is_na_and_weights_renormalise():
    # A repository with no supported source files (e.g. only Go) and all scanners fine.
    cov = build_coverage(0, ALL_OK)
    s = compute_scores([f("high", rule="aws-key", tool="gitleaks", file="main.go")], cov)
    for c in ("reliability", "architecture", "code_quality", "maintainability"):
        assert s["categories"][c]["score"] is None and s["categories"][c]["grade"] == "N/A"
        assert s["categories"][c]["status"] == "not_analysed" and s["categories"][c]["effective_weight"] == 0
    assert s["not_analysed"] == ["reliability", "architecture", "code_quality", "maintainability"]
    assert s["overall"] == s["categories"]["security"]["score"] == 81.9  # not 94.6 from four free 100s
    assert s["categories"]["security"]["effective_weight"] == 1.0


def test_effective_weights_sum_to_one():
    for cov in (full_coverage(), build_coverage(0, ALL_OK), build_coverage(5, None)):
        s = compute_scores([], cov)
        total = sum(v["effective_weight"] for v in s["categories"].values())
        assert math.isclose(total, 1.0, abs_tol=1e-3)


def test_nothing_analysed_at_all_has_no_score():
    s = compute_scores([], build_coverage(0, None))
    assert s["overall"] is None and s["grade"] == "N/A" and len(s["not_analysed"]) == len(WEIGHTS)


@pytest.mark.parametrize("status", ["failed", "skipped", None])
def test_failed_skipped_or_missing_security_scanner_caps_and_marks_incomplete(status):
    scanners = [s for s in ALL_OK if s["name"] != "semgrep"]
    if status:
        scanners.append({"name": "semgrep", "status": status})
    s = compute_scores([], build_coverage(10, scanners))
    sec_cat = s["categories"]["security"]
    assert sec_cat["status"] == "incomplete" and "semgrep" in sec_cat["note"]
    assert s["complete"] is False and s["uncapped_overall"] == 100.0
    assert s["overall"] == INCOMPLETE_CAP and s["grade"] == "B"


def test_all_security_scanners_unavailable_makes_security_na_and_caps():
    s = compute_scores([], build_coverage(10, [{"name": n, "status": "skipped"} for n in SECURITY_SCANNERS]))
    assert s["categories"]["security"]["status"] == "not_analysed"
    assert s["overall"] == INCOMPLETE_CAP and s["complete"] is False


def test_findings_prove_a_category_was_analysed():
    # Built-in security heuristics can still report when every scanner is down.
    s = compute_scores([f("medium", tool="design")], build_coverage(10, None))
    assert s["categories"]["security"]["status"] == "incomplete"
    assert s["categories"]["security"]["score"] is not None


def test_both_caps_apply_lowest_wins():
    s = compute_scores([f("critical")], build_coverage(10, [{"name": "trivy", "status": "failed"}]))
    assert {c["reason"] for c in s["caps"]} == {"critical", "incomplete"} and s["overall"] == CRITICAL_CAP


def test_grade_always_matches_score():
    rng = random.Random(7)
    sevs = ["critical", "high", "medium", "low", "info"]
    for _ in range(300):
        findings = [f(rng.choice(sevs), rng.choice(["high", "medium", "low"]), rule=rng.choice("abc"),
                      cat=rng.choice(list(WEIGHTS)), line=rng.randint(1, 5)) for _ in range(rng.randint(0, 8))]
        cov = build_coverage(rng.choice([0, 3]), rng.choice([None, ALL_OK, ALL_OK[:2]]))
        s = compute_scores(findings, cov)
        assert s["grade"] == ("N/A" if s["overall"] is None else grade(s["overall"]))
        if s["overall"] is not None:
            assert s["overall"] <= s["uncapped_overall"]


def test_without_coverage_behaves_as_fully_analysed():
    s = compute_scores([])
    assert s["overall"] == 100 and s["caps"] == [] and s["complete"] is True and s["not_analysed"] == []


# ---------------------------------------------------------------- pipeline wiring

def test_pipeline_marks_unparsed_categories_na(tmp_path):
    (tmp_path / "main.go").write_text("package main\nfunc main() {}\n")
    s = run_analysis(tmp_path, Settings(), run_scanners=False).summary["scores"]
    assert s["overall"] is None and s["grade"] == "N/A"  # nothing analysable, scanners not run


def test_pipeline_without_scanners_is_incomplete(tmp_path):
    (tmp_path / "app.py").write_text("def f(x):\n    return x + 1\n")
    s = run_analysis(tmp_path, Settings(), run_scanners=False).summary["scores"]
    assert s["categories"]["security"]["status"] == "not_analysed"
    assert s["categories"]["architecture"]["status"] == "scored"
    assert s["complete"] is False and s["overall"] <= INCOMPLETE_CAP


def test_score_does_not_depend_on_input_order():
    """SC-03: same findings in any order give the same score (was 20 distinct scores in 200 orders)."""
    items = [f("high", "high", line=i) for i in range(3)] + [f("high", "low", line=10 + i) for i in range(3)]
    rng = random.Random(1)
    scores = set()
    for _ in range(200):
        rng.shuffle(items)
        scores.add(compute_scores(list(items), full_coverage())["categories"]["security"]["score"])
    assert len(scores) == 1
