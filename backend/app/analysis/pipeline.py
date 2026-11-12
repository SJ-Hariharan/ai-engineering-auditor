"""Deterministic analysis pipeline. Reads files only; never executes repository code."""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict, deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app.analysis import graph as graph_mod
from app.analysis import inventory as inv_mod
from app.analysis.common import RawFinding
from app.analysis.design import analyze_design
from app.analysis.parsing import ParsedFile, parse_file
from app.analysis.quality import DB_CALLS, analyze_quality
from app.analysis.scanners import deps, gitleaks, semgrep
from app.analysis.scanners.suppressions import find_suppressions
from app.analysis.scoring import SEVERITY_POINTS, build_coverage, compute_scores, priority
from app.analysis.testing import analyze_tests
from app.core.config import Settings

log = logging.getLogger(__name__)
HTTP_CALLS = {"fetch", "axios", "requests", "httpx"}

StageCallback = Callable[[str], None]


@dataclass
class AnalysisResult:
    summary: dict
    findings: list[dict]


def run_analysis(root: Path, settings: Settings, on_stage: StageCallback | None = None,
                 run_scanners: bool = True) -> AnalysisResult:
    stage = on_stage or (lambda s: None)

    stage("inventory")
    inv = inv_mod.walk(root, settings.max_file_bytes_analyzed)
    stack = inv_mod.detect_stack(inv)
    test_files = {f.path for f in inv.files if f.is_test}

    stage("parsing")
    parsed: dict[str, ParsedFile] = {}
    for f in inv.files:
        try:
            pf = parse_file(f.path, (root / f.path).read_bytes())
        except (OSError, ValueError) as exc:
            log.warning("parse failed for %s: %s", f.path, exc)
            continue
        if pf:
            parsed[f.path] = pf

    stage("architecture")
    graph = graph_mod.build_graph(root, parsed)
    graph_summary, findings = graph_mod.analyze_graph(graph, test_files)
    views = graph_mod.graph_views(graph, test_files)

    stage("design")
    design_summary, d_findings = analyze_design(root, parsed, inv, test_files)
    findings += d_findings

    stage("quality")
    quality_summary, q_findings = analyze_quality(root, parsed, {f.path: f.lines for f in inv.files},
                                                  test_files)
    findings += q_findings

    stage("testing")
    testing_summary, t_findings = analyze_tests(inv, graph, stack)
    findings += t_findings

    scanner_summaries: list[dict] = []
    suppressions = find_suppressions(root)
    if run_scanners:
        stage("security")
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                "semgrep": pool.submit(semgrep.run, root, settings),
                "gitleaks": pool.submit(gitleaks.run, root, settings),
                "osv": pool.submit(deps.run_osv, root, settings),
                "trivy": pool.submit(deps.run_trivy, root, settings),
            }
            results = {k: v.result() for k, v in futures.items()}
        findings += results["semgrep"].findings + results["gitleaks"].findings
        dep_findings = results["osv"].findings + deps.merge_dependency_findings(
            results["osv"].findings, results["trivy"].findings)
        deps.classify_dependency_findings(dep_findings, inv.runtime_deps, inv.dev_deps)
        findings += dep_findings
        findings += [f for f in results["trivy"].findings if f.rule_id != "vulnerable-dependency"]
        scanner_summaries = [r.summary() for r in results.values()]

    stage("scoring")
    finding_dicts = _dedupe(findings)
    coverage = build_coverage(len(parsed), scanner_summaries if run_scanners else None)
    scores = compute_scores(finding_dicts, coverage)
    finding_dicts.sort(key=lambda f: -priority(f))
    entry = inv_mod.entry_points(inv)
    flow = _data_flow(parsed, graph, entry, test_files)
    summary = {
        "stack": stack,
        "inventory": {
            "total_files": inv.total_files, "source_files": len(inv.files),
            "total_lines": sum(f.lines for f in inv.files), "skipped_large_files": inv.skipped_large,
            "tree": inv_mod.directory_tree(inv),
        },
        "entry_points": entry,
        "files": [
            {"path": f.path, "language": f.language, "lines": f.lines, "is_test": f.is_test,
             "functions": len(parsed[f.path].functions) if f.path in parsed else 0,
             "classes": len(parsed[f.path].classes) if f.path in parsed else 0,
             **graph_summary["metrics"].get(f.path, {})}
            for f in inv.files
        ],
        "symbols": {p: pf.symbols()[:200] for p, pf in list(parsed.items())[:1500]},
        "architecture": {k: v for k, v in graph_summary.items() if k != "metrics"} | {"graph": views},
        "design": design_summary,
        "quality": quality_summary,
        "testing": testing_summary,
        "data_flow": flow,
        "scanners": scanner_summaries,
        "suppressions": suppressions,
        "scores": scores,
        "counts": _counts(finding_dicts),
    }
    summary["overview"] = build_overview(summary)
    return AnalysisResult(summary=summary, findings=finding_dicts)


def _dedupe(findings: list[RawFinding]) -> list[dict]:
    """Drop exact repeats, keep every distinct occurrence, never merge different rules.

    * Same category, file, line *and rule* (e.g. one rule matching twice on a line) → one finding,
      the most severe. Line-less findings collapse only when their fingerprints are equal.
    * Identical defects at *different* lines of a file share a base fingerprint (it ignores line
      numbers so edits don't move findings). They are distinct occurrences (E-01): each is kept,
      and the 2nd, 3rd … in line order get the fingerprint suffixed with their index. The first
      keeps the base fingerprint, so comparisons with audits made before this change still match.
    * Different rules or tools at the same location stay separate findings; scoring counts them
      once (``scoring.scored_findings``, SC-02).
    """
    out: dict[tuple, dict] = {}
    for f in findings:
        d = f.to_dict()
        key = (d["category"], d["file"], d["line"], d["rule_id"]) if d["line"] else (d["fingerprint"],)
        cur = out.get(key)
        if cur is None or SEVERITY_POINTS[d["severity"]] > SEVERITY_POINTS[cur["severity"]]:
            out[key] = d
    by_fp: dict[str, list[dict]] = defaultdict(list)
    for d in out.values():
        by_fp[d["fingerprint"]].append(d)
    for base, group in by_fp.items():
        group.sort(key=lambda d: (d["line"] or 0, d["end_line"] or 0, d["evidence"]))
        for i, d in enumerate(group[1:], start=1):
            d["fingerprint"] = hashlib.sha256(f"{base}#{i}".encode()).hexdigest()[:32]
    return list(out.values())


def _counts(findings: list[dict]) -> dict:
    sev: dict[str, int] = defaultdict(int)
    cat: dict[str, int] = defaultdict(int)
    for f in findings:
        sev[f["severity"]] += 1
        cat[f["category"]] += 1
    return {"total": len(findings), "by_severity": dict(sev), "by_category": dict(cat)}


def _data_flow(parsed: dict[str, ParsedFile], graph: graph_mod.Graph, entry: list[dict],
               test_files: set[str]) -> dict:
    routes = [
        {"method": r.method, "path": r.path, "file": p, "line": r.line, "handler": r.handler}
        for p, pf in parsed.items() if p not in test_files for r in pf.routes
    ]
    data_access = sorted(p for p, pf in parsed.items() if pf.calls & DB_CALLS and p not in test_files)
    external = sorted(p for p, pf in parsed.items() if pf.calls & HTTP_CALLS and p not in test_files)
    adj: dict[str, list[str]] = defaultdict(list)
    for a, b in graph.edges:
        adj[a].append(b)

    def reach(start: str, targets: set[str], depth: int = 4) -> list[str] | None:
        if start in targets:
            return [start]
        prev = {start: None}
        q = deque([(start, 0)])
        while q:
            v, d = q.popleft()
            if d >= depth:
                continue
            for w in adj[v]:
                if w in prev:
                    continue
                prev[w] = v
                if w in targets:
                    path = [w]
                    while prev[path[-1]] is not None:
                        path.append(prev[path[-1]])
                    return list(reversed(path))
                q.append((w, d + 1))
        return None

    flows = []
    targets = set(data_access)
    for rf in sorted({r["file"] for r in routes}):
        path = reach(rf, targets)
        if path:
            flows.append({"from": rf, "to": path[-1], "path": path, "kind": "route → data access"})
    for e in entry:
        if e.get("file") and e["file"] in parsed:
            path = reach(e["file"], targets)
            if path and len(path) > 1:
                flows.append({"from": e["file"], "to": path[-1], "path": path, "kind": "entry → data access"})
    return {"routes": routes[:300], "data_access": data_access[:100], "external_calls": external[:100],
            "flows": flows[:50],
            "method": "Routes from framework decorators/calls; data access and external calls from "
                      "call names (execute/query/fetch/requests…); paths follow resolved imports."}


def build_overview(s: dict) -> dict:
    """Plain-language, deterministic overview. Every sentence is derived from measured facts."""
    stack = s["stack"]
    langs = [lang for lang in stack["languages"] if lang.get("lines")]
    main = ", ".join(f"{lang['name']} ({lang['lines']:,} lines)" for lang in langs[:3]) or "no supported language"
    fw = ", ".join(stack["frameworks"]) or "no recognised framework"
    paras = [f"This repository contains {s['inventory']['source_files']} analysed source files written "
             f"in {main}, using {fw}."]
    if s["entry_points"]:
        eps = ", ".join(f"`{e['file'] or e['reason']}` ({e['kind']})" for e in s["entry_points"][:4])
        paras.append(f"Execution most likely starts at {eps}.")
    routes = s["data_flow"]["routes"]
    if routes:
        paras.append(f"It exposes {len(routes)} HTTP route(s), for example "
                     + ", ".join(f"`{r['method']} {r['path']}`" for r in routes[:4]) + ".")
    if stack["databases"]:
        paras.append(f"Data is stored using {', '.join(stack['databases'])}; "
                     f"{len(s['data_flow']['data_access'])} module(s) query it directly.")
    if s["data_flow"]["external_calls"]:
        paras.append(f"{len(s['data_flow']['external_calls'])} module(s) call external HTTP services.")
    t = s["testing"]
    paras.append(f"There are {t['test_files']} test file(s)"
                 + (f" using {', '.join(t['frameworks'])}" if t["frameworks"] else "")
                 + (f"; roughly {t['static_coverage_pct']}% of non-trivial modules are referenced by a test."
                    if t["static_coverage_pct"] is not None and t["test_files"] else "."))
    cycles = s["architecture"]["cycles"]
    if cycles:
        paras.append(f"The import graph contains {len(cycles)} circular dependency group(s).")
    top_dirs = sorted(s["inventory"]["tree"], key=lambda d: -d["lines"])[:4]
    areas = [{"path": d["path"], "files": d["files"], "lines": d["lines"]} for d in top_dirs]
    return {"paragraphs": paras, "largest_areas": areas, "generated_by": "deterministic"}
