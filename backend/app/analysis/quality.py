"""Engineering-principles analysis built on tree-sitter output.

Every finding carries the measured evidence. Threshold-based findings are marked
`subjective`: the measurement is exact, but whether it is a problem is a judgement.
Thresholds live in THRESHOLDS so they are visible and easy to tune.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path

from app.analysis.common import RawFinding, clip
from app.analysis.parsing import ParsedFile

THRESHOLDS = {
    "function_lines_low": 80, "function_lines_medium": 150,
    "complexity_medium": 15, "complexity_high": 30,
    "nesting": 5, "params": 6,
    "file_lines_low": 600, "file_lines_medium": 1200,
    "class_methods": 25, "class_lines": 600,
    "duplicate_window": 8,
}

DB_CALLS = {"execute", "query", "raw", "cursor", "findMany", "findUnique"}


def _snippet(lines: list[str], line: int, context: int = 2) -> str:
    start = max(line - 1 - context, 0)
    return clip("\n".join(lines[start:line - 1 + context + 1]), 800)


def analyze_quality(root: Path, parsed: dict[str, ParsedFile], line_counts: dict[str, int],
                    test_files: set[str]) -> tuple[dict, list[RawFinding]]:
    findings: list[RawFinding] = []
    all_functions = []
    for path, pf in parsed.items():
        is_test = path in test_files
        try:
            lines = (root / path).read_text("utf-8", "replace").splitlines()
        except OSError:
            continue
        for fn in pf.functions:
            all_functions.append((path, fn))
            if is_test:
                continue
            findings.extend(_function_findings(path, fn, lines))
        if not is_test:
            findings.extend(_file_findings(path, pf, line_counts.get(path, 0), lines))
            findings.extend(_naming(path, pf))
        findings.extend(_error_handling(path, pf, lines, is_test))
    findings.extend(_duplication(root, [p for p in parsed if p not in test_files]))

    complexities = [fn.complexity for _, fn in all_functions]
    summary = {
        "functions": len(all_functions),
        "classes": sum(len(pf.classes) for pf in parsed.values()),
        "avg_complexity": round(sum(complexities) / len(complexities), 2) if complexities else 0,
        "complex_functions": sum(1 for c in complexities if c > THRESHOLDS["complexity_medium"]),
        "long_functions": sum(1 for _, fn in all_functions if fn.length > THRESHOLDS["function_lines_low"]),
        "hotspots": [
            {"file": p, "name": fn.name, "line": fn.line, "complexity": fn.complexity, "lines": fn.length}
            for p, fn in sorted(all_functions, key=lambda x: -x[1].complexity)[:15]
            if p not in test_files
        ],
        "thresholds": THRESHOLDS,
    }
    return summary, findings


def _function_findings(path: str, fn, lines: list[str]) -> list[RawFinding]:
    out: list[RawFinding] = []
    T = THRESHOLDS
    header = _snippet(lines, fn.line, 0)
    if fn.complexity > T["complexity_medium"]:
        out.append(RawFinding(
            tool="quality", rule_id="high-complexity", category="code_quality",
            severity="high" if fn.complexity > T["complexity_high"] else "medium",
            confidence="high", kind="subjective", principle="KISS",
            title=f"`{fn.name}` has cyclomatic complexity {fn.complexity}",
            file=path, line=fn.line, end_line=fn.end_line, evidence=header,
            explanation=f"Cyclomatic complexity counts independent paths (branches, loops, boolean "
                        f"operators, handlers). {fn.complexity} exceeds the threshold of "
                        f"{T['complexity_medium']}. The number is exact; the threshold is a convention.",
            impact="Each path needs a test to be covered; complex functions hide edge-case bugs and "
                   "are risky to change.",
            remediation="Extract branches into well-named helpers, use early returns, or replace "
                        "conditionals with lookup tables/polymorphism.", fingerprint_key=f"{path}|{fn.name}"))
    if fn.length > T["function_lines_low"]:
        out.append(RawFinding(
            tool="quality", rule_id="long-function", category="maintainability",
            severity="medium" if fn.length > T["function_lines_medium"] else "low",
            confidence="high", kind="subjective", principle="Single Responsibility",
            title=f"`{fn.name}` is {fn.length} lines long", file=path, line=fn.line,
            end_line=fn.end_line, evidence=header,
            explanation=f"Functions over {T['function_lines_low']} lines usually do more than one thing.",
            impact="Long functions are hard to read, review and test in isolation.",
            remediation="Split into smaller functions that each do one named step.",
            fingerprint_key=f"{path}|{fn.name}"))
    if fn.max_nesting >= T["nesting"]:
        out.append(RawFinding(
            tool="quality", rule_id="deep-nesting", category="code_quality", severity="low",
            confidence="high", kind="subjective", principle="KISS",
            title=f"`{fn.name}` nests control flow {fn.max_nesting} levels deep", file=path,
            line=fn.line, evidence=header,
            explanation="Deeply nested blocks force readers to track many conditions at once.",
            impact="Higher chance of logic errors in rarely-taken branches.",
            remediation="Use guard clauses / early returns and extract inner loops.",
            fingerprint_key=f"{path}|{fn.name}"))
    if fn.params > T["params"]:
        out.append(RawFinding(
            tool="quality", rule_id="many-parameters", category="code_quality", severity="low",
            confidence="high", kind="subjective", principle="Readability",
            title=f"`{fn.name}` takes {fn.params} parameters", file=path, line=fn.line, evidence=header,
            explanation=f"More than {T['params']} parameters often signals missing abstraction.",
            impact="Call sites become error-prone (argument order mistakes).",
            remediation="Group related parameters into an object/dataclass.",
            fingerprint_key=f"{path}|{fn.name}"))
    return out


def _file_findings(path: str, pf: ParsedFile, n_lines: int, lines: list[str]) -> list[RawFinding]:
    out: list[RawFinding] = []
    T = THRESHOLDS
    if n_lines > T["file_lines_low"]:
        out.append(RawFinding(
            tool="quality", rule_id="large-file", category="maintainability",
            severity="medium" if n_lines > T["file_lines_medium"] else "low", confidence="high",
            kind="subjective", principle="Modularity", title=f"File has {n_lines} lines", file=path,
            evidence=f"{n_lines} lines, {len(pf.functions)} functions, {len(pf.classes)} classes.",
            explanation=f"Files over {T['file_lines_low']} lines tend to collect unrelated responsibilities.",
            impact="Harder to navigate and review; more merge conflicts.",
            remediation="Split by responsibility into smaller modules.", fingerprint_key=path))
    for c in pf.classes:
        length = c.end_line - c.line + 1
        if c.methods >= T["class_methods"] or length > T["class_lines"]:
            out.append(RawFinding(
                tool="quality", rule_id="large-class", category="maintainability", severity="medium",
                confidence="medium", kind="subjective", principle="Single Responsibility",
                title=f"Class `{c.name}` has {c.methods} methods across {length} lines",
                file=path, line=c.line, end_line=c.end_line, evidence=_snippet(lines, c.line, 0),
                explanation="Very large classes frequently mix several responsibilities (a 'god class'). "
                            "This is inferred from size alone; review whether the methods share one purpose.",
                impact="Changes for unrelated reasons collide in one class; testing requires heavy setup.",
                remediation="Identify clusters of methods that use the same fields and extract them.",
                fingerprint_key=f"{path}|{c.name}"))
    if pf.routes and pf.calls & DB_CALLS:
        r = pf.routes[0]
        out.append(RawFinding(
            tool="quality", rule_id="mixed-http-and-data-access", category="architecture",
            severity="low", confidence="low", kind="subjective", principle="Separation of Concerns",
            title="HTTP handlers and database queries in the same module", file=path, line=r.line,
            evidence=f"Defines {len(pf.routes)} route(s) (e.g. {r.method} {r.path}) and calls "
                     f"{', '.join(sorted(pf.calls & DB_CALLS))}.",
            explanation="Route handlers that query the database directly couple transport concerns "
                        "to persistence. Acceptable in small apps; a smell as the app grows.",
            impact="Business rules become hard to reuse (CLI, jobs, tests) and to test without a DB.",
            remediation="Move data access into a repository/service layer the handlers call.",
            fingerprint_key=path))
    return out


ERROR_RULES = {
    "bare-except": ("medium", "high", "objective", "Bare `except:` catches everything",
                    "A bare except also catches KeyboardInterrupt and SystemExit, and hides "
                    "programming errors such as NameError.",
                    "Failures are silently converted into wrong behaviour; shutdown can be blocked.",
                    "Catch the specific exceptions you expect (e.g. `except ValueError:`)."),
    "swallowed-exception": ("medium", "high", "objective", "Exception is caught and ignored",
                            "The handler body only contains `pass`/`continue`, so the error is "
                            "discarded without logging or recovery.",
                            "Bugs and outages become invisible; data may be left half-written.",
                            "Log the error with context, re-raise, or handle it explicitly."),
    "empty-catch": ("medium", "high", "objective", "Empty catch block",
                    "The catch block has no statements, so the error is silently discarded.",
                    "Failures become invisible and debugging becomes guesswork.",
                    "Log the error, rethrow it, or handle it explicitly; add a comment if ignoring "
                    "is truly intended."),
    "broad-except": ("low", "medium", "subjective", "Catches broad `Exception`",
                     "Catching `Exception` is sometimes right at process boundaries, but inside "
                     "business logic it tends to mask unexpected errors.",
                     "Unexpected errors may be handled as if they were expected ones.",
                     "Narrow the exception types, or make sure the error is logged and re-raised."),
}


def _error_handling(path: str, pf: ParsedFile, lines: list[str], is_test: bool) -> list[RawFinding]:
    out = []
    for issue in pf.error_issues:
        if is_test and issue.rule == "broad-except":
            continue
        sev, conf, kind, title, expl, impact, fix = ERROR_RULES[issue.rule]
        out.append(RawFinding(
            tool="quality", rule_id=issue.rule, category="reliability", severity=sev,
            confidence=conf, kind=kind, principle="Error Handling", title=title, file=path,
            line=issue.line, evidence=_snippet(lines, issue.line, 1), explanation=expl,
            impact=impact, remediation=fix, fingerprint_key=f"{path}|{issue.snippet}"))
    for line in pf.syntax_errors:
        out.append(RawFinding(
            tool="tree-sitter", rule_id="syntax-error", category="reliability", severity="high",
            confidence="medium", kind="objective", title="File does not parse cleanly", file=path,
            line=line, evidence=_snippet(lines, line, 1),
            explanation="The tree-sitter parser found a syntax error here. Confidence is medium "
                        "because very new language syntax can occasionally be unsupported.",
            impact="The file will likely fail to import/compile.",
            remediation="Fix the syntax error; run the language's compiler or linter to confirm.",
            fingerprint_key=f"{path}|syntax"))
    return out


_COMMENT = re.compile(r"^\s*(#|//|/\*|\*|\"\"\"|''')")
_TRIVIAL = re.compile(r"^\s*([})\]];?,?|import\b.*|from\s+\S+\s+import\b.*|export\s+\*.*|pass|return;?|else:?\s*{?|\}\s*else\s*\{)\s*$")


def _duplication(root: Path, paths: list[str]) -> list[RawFinding]:
    """Detect duplicated blocks of ≥N significant lines (whitespace-normalised) across files."""
    W = THRESHOLDS["duplicate_window"]
    windows: dict[str, list[tuple[str, int]]] = defaultdict(list)
    file_sig: dict[str, list[tuple[int, str]]] = {}
    for path in paths:
        try:
            raw = (root / path).read_text("utf-8", "replace").splitlines()
        except OSError:
            continue
        sig = [(i + 1, re.sub(r"\s+", " ", ln.strip())) for i, ln in enumerate(raw)
               if ln.strip() and not _COMMENT.match(ln) and not _TRIVIAL.match(ln)]
        file_sig[path] = sig
        for k in range(len(sig) - W + 1):
            chunk = "\n".join(s for _, s in sig[k:k + W])
            if len(chunk) < W * 12:  # ignore windows made of tiny lines
                continue
            h = hashlib.sha1(chunk.encode(), usedforsecurity=False).hexdigest()
            windows[h].append((path, k))

    # Merge consecutive matching windows between the same pair of files into blocks.
    pairs: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for occ in windows.values():
        if len(occ) < 2 or len(occ) > 6:
            continue
        a = occ[0]
        for b in occ[1:]:
            if a[0] == b[0] and abs(a[1] - b[1]) < W:
                continue
            key = (a[0], b[0])
            pairs[key].append((a[1], b[1]))
    findings = []
    for (fa, fb), starts in pairs.items():
        starts.sort()
        blocks: list[list[tuple[int, int]]] = []
        for s in starts:
            if blocks and s[0] - blocks[-1][-1][0] == 1 and s[1] - blocks[-1][-1][1] == 1:
                blocks[-1].append(s)
            else:
                blocks.append([s])
        for blk in blocks:
            n_sig = len(blk) + W - 1
            sa, sb = file_sig[fa], file_sig[fb]
            la, lb = sa[blk[0][0]][0], sb[blk[0][1]][0]
            la_end = sa[min(blk[-1][0] + W - 1, len(sa) - 1)][0]
            lb_end = sb[min(blk[-1][1] + W - 1, len(sb) - 1)][0]
            preview = "\n".join(s for _, s in sa[blk[0][0]:blk[0][0] + 6])
            findings.append(RawFinding(
                tool="quality", rule_id="duplicate-code", category="maintainability",
                severity="medium" if n_sig >= 25 else "low", confidence="high", kind="objective",
                principle="DRY",
                title=f"{n_sig} duplicated lines" + (" within the file" if fa == fb else f" also in {fb}"),
                file=fa, line=la, end_line=la_end,
                evidence=f"{fa}:{la}-{la_end} ≈ {fb}:{lb}-{lb_end}\n\n{clip(preview, 500)}",
                explanation="These blocks are identical after normalising whitespace and ignoring "
                            "comments/imports. Whether to merge them is a judgement call; small "
                            "duplication is sometimes clearer than a premature abstraction.",
                impact="Bug fixes must be applied in several places; copies drift apart over time.",
                remediation="Extract the shared logic into a function or module used by both.",
                fingerprint_key=f"{fa}|{fb}|{preview[:120]}"))
    findings.sort(key=lambda f: -int(f.title.split()[0]))
    return findings[:60]


_PY_FUNC = re.compile(r"^_{0,2}[a-z][a-z0-9_]*_{0,2}$")
_JS_FUNC = re.compile(r"^[a-zA-Z$][a-zA-Z0-9$]*$")  # camelCase or PascalCase (components)


def _naming(path: str, pf: ParsedFile) -> list[RawFinding]:
    """Flag functions that break the language's naming convention or are cryptically short."""
    bad: list[str] = []
    for fn in pf.functions:
        name = fn.name
        if name.startswith("<") or name in ("default",) or "." in name:
            continue
        if pf.grammar == "python":
            if not _PY_FUNC.match(name):
                bad.append(f"`{name}` (line {fn.line}) is not snake_case")
        elif not _JS_FUNC.match(name) or "_" in name.strip("_$"):
            bad.append(f"`{name}` (line {fn.line}) is not camelCase")
        if len(name.strip("_")) <= 2 and fn.length > 5:
            bad.append(f"`{name}` (line {fn.line}) is too short to describe a {fn.length}-line function")
    if not bad:
        return []
    return [RawFinding(
        tool="quality", rule_id="naming-convention", category="code_quality", severity="info",
        confidence="medium", kind="subjective", principle="Naming & Readability",
        title=f"{len(bad)} function name(s) break naming conventions", file=path,
        line=int(re.search(r"line (\d+)", bad[0]).group(1)),
        evidence="\n".join(bad[:10]),
        explanation="PEP 8 (Python) and common JS/TS style use snake_case / camelCase function "
                    "names. Consistent naming makes code searchable and predictable.",
        impact="Minor: slows reading and can confuse contributors.",
        remediation="Rename to follow the convention (use your editor's rename refactoring).",
        fingerprint_key=path)]
