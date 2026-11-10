from pathlib import Path

from app.analysis.graph import analyze_graph, build_graph, strongly_connected
from app.analysis.parsing import parse_file
from app.analysis.quality import analyze_quality
from app.analysis.scoring import compute_scores
from app.llm.redact import redact


def _write(root: Path, files: dict[str, str]) -> dict:
    parsed = {}
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        parsed[rel] = parse_file(rel, text.encode())
    return parsed


def test_python_parsing_extracts_structure():
    pf = parse_file("m.py", b"""
import os
from .sib import thing
class A:
    def f(self, x, y):
        if x and y:
            return 1
        for i in range(3):
            while i: pass
@app.post("/items")
def create():
    try:
        pass
    except:
        pass
""")
    assert ("os", 2) in pf.imports and (".sib.thing", 3) in pf.imports
    f = next(s for s in pf.functions if s.name == "f")
    assert f.params == 2 and f.complexity == 5 and f.parent == "A"
    assert [r.method for r in pf.routes] == ["POST"]
    assert {i.rule for i in pf.error_issues} == {"bare-except", "swallowed-exception"}


def test_typescript_parsing_and_syntax_errors():
    pf = parse_file("a.tsx", b"import x from './b';\nexport const C = () => { try { a() } catch (e) {} };\nfunction (")
    assert ("./b", 1) in pf.imports
    assert any(i.rule == "empty-catch" for i in pf.error_issues)
    assert pf.syntax_errors


def test_cycle_detection_and_unresolved_imports(tmp_path):
    parsed = _write(tmp_path, {
        "src/a.ts": "import { b } from './b';",
        "src/b.ts": "import { c } from './c';",
        "src/c.ts": "import { a } from './a';\nimport x from './missing';",
        "src/d.ts": "import { a } from '@/a';",  # default @/ -> src/ alias
        "pkg/x.py": "from . import y",
        "pkg/y.py": "from pkg import x",
    })
    g = build_graph(tmp_path, parsed)
    assert ("src/d.ts", "src/a.ts") in g.edges
    summary, findings = analyze_graph(g, set())
    cycles = {tuple(sorted(c[:-1])) for c in summary["cycles"]}
    assert ("src/a.ts", "src/b.ts", "src/c.ts") in cycles
    assert ("pkg/x.py", "pkg/y.py") in cycles
    assert any(f.rule_id == "unresolved-import" and "missing" in f.title for f in findings)


def test_tarjan_large_chain_no_recursion_error():
    nodes = [str(i) for i in range(5000)]
    edges = {(str(i), str(i + 1)) for i in range(4999)} | {("4999", "0")}
    assert len(strongly_connected(nodes, edges)[0]) == 5000


def test_duplication_and_complexity(tmp_path):
    block = "\n".join(f"    total = total + compute_value(item_{i}, factor={i})" for i in range(12))
    branches = "\n".join(f"    if x == {i} and y:\n        return {i}" for i in range(20))
    files = {"a.py": f"def one(item):\n    total = 0\n{block}\n    return total\n",
             "b.py": f"def two(item):\n    total = 0\n{block}\n    return total\n",
             "c.py": f"def branchy(x, y):\n{branches}\n"}
    parsed = _write(tmp_path, files)
    _, findings = analyze_quality(tmp_path, parsed, {k: v.count("\n") for k, v in files.items()}, set())
    rules = {f.rule_id for f in findings}
    assert "duplicate-code" in rules and "high-complexity" in rules
    dup = next(f for f in findings if f.rule_id == "duplicate-code")
    assert dup.kind == "objective" and dup.principle == "DRY"


def test_scores_have_diminishing_returns_and_bounds():
    one = compute_scores([{"category": "security", "severity": "critical", "confidence": "high",
                           "rule_id": "r", "kind": "objective"}])
    many = compute_scores([{"category": "security", "severity": "low", "confidence": "high",
                            "rule_id": "same", "kind": "objective"}] * 500)
    assert 50 < one["categories"]["security"]["score"] < 70
    assert many["categories"]["security"]["score"] > 80  # one noisy rule can't zero a category
    assert compute_scores([])["overall"] == 100
    assert "not a security certification" in " ".join(one["methodology"]["limitations"])


def test_redaction():
    text = ('key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"\nAWS=AKIAQ4ZPSE2ULJ7RTN3X\n'
            'password = "hunter2hunter2"\nurl = "postgres://user:pa55@db:5432/x"\nok = 1')
    out = redact(text, {5})
    for secret in ("abcdefghijklmnop", "AKIAQ4ZPSE2ULJ7RTN3X", "hunter2hunter2", "pa55"):
        assert secret not in out
    assert "line redacted" in out


def test_dependency_classification(tmp_path):
    from app.analysis.common import RawFinding
    from app.analysis.inventory import walk
    from app.analysis.scanners.deps import classify_dependency_findings

    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\ndependencies=["Flask>=2"]\n[dependency-groups]\ndev=["pytest"]\n')
    (tmp_path / "package.json").write_text('{"dependencies":{"express":"4"},"devDependencies":{"vitest":"1"}}')
    inv = walk(tmp_path, 10**6)
    assert {"flask", "express"} <= inv.runtime_deps and {"pytest", "vitest"} <= inv.dev_deps

    def dep(name):
        return RawFinding(tool="osv-scanner", rule_id="vulnerable-dependency", category="security",
                          severity="high", confidence="high", kind="objective", title=name,
                          fingerprint_key=f"pypi|{name}|1.0")

    runtime, dev, transitive = dep("flask"), dep("pytest"), dep("urllib3")
    classify_dependency_findings([runtime, dev, transitive], inv.runtime_deps, inv.dev_deps)
    assert (runtime.severity, runtime.confidence) == ("high", "high")
    assert dev.severity == "medium" and "dev dependency" in dev.title
    assert transitive.severity == "high" and transitive.confidence == "medium"


def test_deterministic_fixers_produce_parseable_code():
    from types import SimpleNamespace

    from app.remediation.fixers import deterministic_fix
    from app.remediation.patching import apply_edits, check_syntax

    src = "import yaml\n\ndef load(t):\n    return yaml.load(t)\n\napp.run(debug=True)\n"
    lines = src.splitlines(keepends=True)
    for rule, line, expect in (("py-unsafe-deserialization", 4, "yaml.safe_load(t)"),
                               ("py-flask-debug-enabled", 6, 'os.environ.get("FLASK_DEBUG")')):
        f = SimpleNamespace(rule_id=rule, line=line, end_line=line, file="a.py")
        edits, rationale, _ = deterministic_fix(lines, f)
        out = apply_edits(src, edits)
        check_syntax("a.py", src, out)
        assert expect in out and rationale
    assert "import os\n" in apply_edits(src, deterministic_fix(
        lines, SimpleNamespace(rule_id="py-flask-debug-enabled", line=6, end_line=6, file="a.py"))[0])
