"""Test inventory and static coverage estimation (no code is executed here)."""

from __future__ import annotations

from pathlib import PurePosixPath

from app.analysis.common import RawFinding
from app.analysis.graph import Graph
from app.analysis.inventory import Inventory


def _stem(path: str) -> str:
    name = PurePosixPath(path).name
    for suffix in (".test", ".spec", "_test"):
        name = name.replace(suffix + ".", ".")
    name = name.removeprefix("test_")
    return name.split(".")[0].lower()


def analyze_tests(inv: Inventory, graph: Graph, stack: dict) -> tuple[dict, list[RawFinding]]:
    tests = [f for f in inv.files if f.is_test]
    prod = [f for f in inv.files if not f.is_test]
    test_paths = {f.path for f in tests}
    # A module counts as "referenced by tests" if a test imports it or shares its base name.
    imported_by_tests = {b for a, b in graph.edges if a in test_paths}
    test_stems = {_stem(t.path) for t in tests}
    untested = [f for f in prod if f.path not in imported_by_tests and _stem(f.path) not in test_stems
                and _stem(f.path) not in {"index", "__init__", "types", "constants", "config"}
                and f.lines >= 20]
    untested.sort(key=lambda f: -f.lines)
    covered = len(prod) - len(untested)
    eligible = len([f for f in prod if f.lines >= 20])
    findings: list[RawFinding] = []

    if prod and not tests:
        findings.append(RawFinding(
            tool="testing", rule_id="no-tests", category="reliability", severity="high",
            confidence="high", kind="objective", title="No automated tests found",
            evidence=f"{len(prod)} source files and 0 test files (searched tests/, __tests__/, "
                     "test_*.py, *_test.py, *.test.*, *.spec.*).",
            explanation="Without tests there is no fast, repeatable way to know whether a change "
                        "breaks existing behaviour.",
            impact="Regressions reach users; refactoring (including fixes from this report) is risky.",
            remediation="Start with tests for the most critical paths (auth, payments, data writes), "
                        f"using {', '.join(stack.get('test_frameworks') or ['pytest/Vitest'])}.",
            fingerprint_key="repo"))
    elif untested and eligible:
        pct = round(100 * len(untested) / max(eligible, 1))
        top = untested[:12]
        findings.append(RawFinding(
            tool="testing", rule_id="untested-modules", category="reliability",
            severity="medium" if pct >= 50 else "low", confidence="medium", kind="objective",
            title=f"{len(untested)} source modules are not referenced by any test ({pct}%)",
            file=top[0].path,
            evidence="Largest untested modules:\n" + "\n".join(f"• {f.path} ({f.lines} lines)" for f in top),
            explanation="A module is considered referenced if a test file imports it or has a "
                        "matching name. This is a static estimate, not line coverage — run the "
                        "test suite with coverage for exact numbers.",
            impact="Behaviour in these modules can change without any test failing.",
            remediation="Add tests for the largest/most critical modules first.",
            fingerprint_key="repo"))

    summary = {
        "test_files": len(tests),
        "source_files": len(prod),
        "test_lines": sum(f.lines for f in tests),
        "source_lines": sum(f.lines for f in prod),
        "frameworks": stack.get("test_frameworks", []),
        "referenced_modules": covered,
        "untested_modules": [{"file": f.path, "lines": f.lines} for f in untested[:50]],
        "static_coverage_pct": round(100 * (eligible - len(untested)) / eligible) if eligible else None,
        "method": "static: test imports + filename matching",
    }
    return summary, findings
