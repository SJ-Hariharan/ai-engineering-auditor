"""Engineering health score.

Methodology (also returned in the report so users can see it):
  * Each analysed category starts at 100.
  * Findings in the same category at the same file and line are one root cause reported by several
    rules or tools; only the most severe of them is scored (SC-02). Every finding is still reported.
  * Every scored finding deducts  base[severity] × confidence_factor.
  * Deductions within a category use diminishing returns: the k-th finding of the
    same rule counts 1/k, so one noisy rule cannot zero a category.
  * The category score is 100 × exp(-total/60): smooth and never negative; one high-confidence
    critical finding gives about 66.
  * A category with nothing to analyse (no parsed source files, or no security scanner that ran)
    is "not analysed": it has no score and its weight is shared among the other categories (SC-01).
  * Overall = weighted mean of the analysed categories, then capped: a high-confidence critical
    finding caps it at 79.9 (C at best); a security scanner that was skipped, failed or not run
    caps it at 89.9 (no A) and marks the result incomplete (SC-01).
Limitations are stated explicitly in METHODOLOGY.
"""

from __future__ import annotations

import math
from collections import defaultdict

SEVERITY_POINTS = {"critical": 25.0, "high": 12.0, "medium": 5.0, "low": 1.5, "info": 0.3}
CONFIDENCE_FACTOR = {"high": 1.0, "medium": 0.7, "low": 0.4}
WEIGHTS = {"security": 0.30, "reliability": 0.20, "architecture": 0.20, "code_quality": 0.15,
           "maintainability": 0.15}
LABELS = {"security": "Security", "reliability": "Testing & Reliability",
          "architecture": "Architecture", "code_quality": "Code Quality",
          "maintainability": "Maintainability"}

# Scanners whose results make up the security category (names as in ScannerResult.name).
SECURITY_SCANNERS = ("semgrep", "gitleaks", "osv-scanner", "trivy")
# Overall-score caps (SC-01). Capping the score, not just the letter, keeps grade == grade(score)
# everywhere the score is shown (project lists recompute the grade from the number).
CRITICAL_CAP = 79.9  # a high-confidence critical finding: C at best
INCOMPLETE_CAP = 89.9  # a security scanner skipped / failed / not run: no A

METHODOLOGY = {
    "summary": "Each analysed category starts at 100 and loses points for findings, weighted by severity "
               "and confidence, with diminishing returns for repeated findings of the same rule. "
               "Findings in the same category at the same file and line count once (the most severe). "
               "Categories with nothing to analyse are marked not analysed and their weight is shared "
               "among the others. The overall score is a weighted average of the analysed categories, "
               "capped when there is a high-confidence critical finding or a security scanner did not run.",
    "severity_points": SEVERITY_POINTS,
    "confidence_factor": CONFIDENCE_FACTOR,
    "weights": WEIGHTS,
    "caps": {"critical": CRITICAL_CAP, "incomplete": INCOMPLETE_CAP},
    "formula": "category = 100 × exp(−Σ points / 60); overall = min(Σ weight × category / Σ weight "
               "over analysed categories, caps)",
    "limitations": [
        "This score is a prioritisation aid, not a security certification or compliance attestation.",
        "Static analysis cannot prove the absence of vulnerabilities; business-logic and "
        "authorisation flaws are often invisible to pattern matching.",
        "Scanners that were skipped or failed contribute no findings. The score is then marked "
        "incomplete and capped at 89.9, but it can still be higher than reality — check the "
        "scanner status table.",
        "Two different issues reported on the same line of the same file, in the same category, "
        "are scored as one.",
        "Thresholds for size and complexity are conventions, not laws; subjective findings are "
        "labelled as such.",
        "Dependency results reflect advisory databases at scan time.",
    ],
}


def grade(score: float) -> str:
    return "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 55 else "F"


def build_coverage(parsed_files: int, scanners: list[dict] | None) -> dict[str, dict]:
    """What each category was able to analyse.

    ``parsed_files``: source files the built-in analyzers parsed. ``scanners``: scanner summaries
    (``ScannerResult.summary()``), or None when the security scanners were not run at all.
    Returns ``{category: {"analysed": bool, "complete": bool, "note": str}}``.
    """
    builtin = {"analysed": parsed_files > 0, "complete": True,
               "note": "" if parsed_files > 0 else "No supported source files were parsed."}
    cov = {c: dict(builtin) for c in WEIGHTS if c != "security"}
    if scanners is None:
        cov["security"] = {"analysed": False, "complete": False,
                           "note": "Security scanners were not run."}
        return cov
    status = {s.get("name"): s.get("status") for s in scanners}
    ok = [n for n in SECURITY_SCANNERS if status.get(n) == "ok"]
    missing = [f"{n} ({status.get(n) or 'not run'})" for n in SECURITY_SCANNERS if status.get(n) != "ok"]
    note = ("Did not run successfully: " + ", ".join(missing) + ".") if missing else ""
    cov["security"] = {"analysed": bool(ok), "complete": not missing, "note": note}
    return cov


def _rank(f: dict) -> tuple:
    """Most severe first; the string fields only break exact ties, so the choice is order-independent."""
    return (SEVERITY_POINTS[f["severity"]], CONFIDENCE_FACTOR.get(f["confidence"], 0.7),
            f.get("rule_id") or "", f.get("tool") or "", f.get("fingerprint") or "")


def scored_findings(findings: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """One finding per root cause (SC-02).

    Findings in the same category at the same file and line are treated as one issue reported by
    several rules or tools; the most severe is kept. Findings without a line (file- or repo-level,
    e.g. a vulnerable package in a manifest) are each their own root cause. Returns the findings to
    score and, per category, how many duplicates were folded in.
    """
    groups: dict[tuple, list[dict]] = {}
    for i, f in enumerate(findings):
        if f["category"] not in WEIGHTS:
            continue
        key = (f["category"], f["file"], f["line"]) if f.get("file") and f.get("line") else ("#", i)
        groups.setdefault(key, []).append(f)
    out: list[dict] = []
    merged: dict[str, int] = defaultdict(int)
    for group in groups.values():
        out.append(max(group, key=_rank))
        merged[group[0]["category"]] += len(group) - 1
    return out, dict(merged)


def compute_scores(findings: list[dict], coverage: dict[str, dict] | None = None) -> dict:
    """Category and overall scores. ``coverage`` comes from :func:`build_coverage`; when omitted,
    every category is treated as fully analysed (no N/A, no incompleteness cap)."""
    scored, merged = scored_findings(findings)
    per_rule_seen: dict[tuple[str, str], int] = defaultdict(int)
    totals: dict[str, float] = defaultdict(float)
    def pts(f: dict) -> float:
        return SEVERITY_POINTS[f["severity"]] * CONFIDENCE_FACTOR.get(f["confidence"], 0.7)

    # SC-03: the k-th finding of a rule counts 1/k, so the order must not depend on input order.
    # Largest deduction first; the rest of the key only breaks exact ties.
    ordered = sorted(scored, key=lambda f: (-pts(f), f["category"], f["rule_id"], f.get("file") or "",
                                            f.get("line") or 0, f.get("fingerprint") or ""))
    for f in ordered:
        key = (f["category"], f["rule_id"])
        per_rule_seen[key] += 1
        points = pts(f)
        totals[f["category"]] += points / per_rule_seen[key]
    counts: dict[str, dict[str, int]] = {c: defaultdict(int) for c in WEIGHTS}
    for f in findings:  # counts describe the reported findings, duplicates included
        if f["category"] in WEIGHTS:
            counts[f["category"]][f["severity"]] += 1

    cov = coverage or {}
    categories = {}
    for cat, weight in WEIGHTS.items():
        c = cov.get(cat, {"analysed": True, "complete": True, "note": ""})
        # Findings are evidence of analysis even if the coverage signal says otherwise.
        analysed = c["analysed"] or bool(counts[cat])
        score = round(100 * math.exp(-totals[cat] / 60), 1) if analysed else None
        status = "not_analysed" if not analysed else "scored" if c["complete"] else "incomplete"
        categories[cat] = {"label": LABELS[cat], "score": score,
                           "grade": grade(score) if score is not None else "N/A",
                           "status": status, "note": c.get("note", ""),
                           "weight": weight, "effective_weight": 0.0,
                           "deduction": round(totals[cat], 1),
                           "counts": {s: counts[cat][s] for s in SEVERITY_POINTS if counts[cat].get(s)},
                           "merged_duplicates": merged.get(cat, 0)}

    analysed_w = sum(v["weight"] for v in categories.values() if v["score"] is not None)
    for v in categories.values():
        if v["score"] is not None:
            v["effective_weight"] = round(v["weight"] / analysed_w, 4)
    uncapped = (round(sum(v["score"] * v["weight"] for v in categories.values() if v["score"] is not None)
                      / analysed_w, 1) if analysed_w else None)

    caps = []
    n_crit = sum(1 for f in scored if f["severity"] == "critical" and f["confidence"] == "high")
    if n_crit:
        caps.append({"reason": "critical", "max": CRITICAL_CAP,
                     "note": f"{n_crit} high-confidence critical finding(s): the grade cannot be above C."})
    # Only the security category depends on external scanners, so only it can be incomplete.
    incomplete = not cov.get("security", {}).get("complete", True)
    if incomplete:
        caps.append({"reason": "incomplete", "max": INCOMPLETE_CAP,
                     "note": "Not every security scanner ran successfully, so the result is incomplete "
                             "and cannot grade A."})
    overall = None if uncapped is None else min([uncapped, *(c["max"] for c in caps)])
    return {"overall": overall, "grade": grade(overall) if overall is not None else "N/A",
            "uncapped_overall": uncapped, "caps": caps, "complete": not incomplete,
            "not_analysed": [c for c, v in categories.items() if v["status"] == "not_analysed"],
            "categories": categories, "methodology": METHODOLOGY}


def priority(f: dict) -> float:
    """Rank for 'fix first': severity × confidence, objective before subjective, security first."""
    p = SEVERITY_POINTS[f["severity"]] * CONFIDENCE_FACTOR.get(f["confidence"], 0.7)
    if f["kind"] == "objective":
        p *= 1.3
    if f["category"] == "security":
        p *= 1.5
    elif f["category"] == "reliability":
        p *= 1.2
    return p
