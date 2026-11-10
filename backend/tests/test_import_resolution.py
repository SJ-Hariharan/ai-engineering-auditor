"""DET-10 / DET-03: JS/TS import resolution against real-world project layouts."""

from pathlib import Path

from app.analysis.graph import analyze_graph, build_graph
from app.analysis.parsing import parse_file


def _project(root: Path, files: dict[str, str]):
    parsed = {}
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        pf = parse_file(rel, text.encode())
        if pf:
            parsed[rel] = pf
    graph = build_graph(root, parsed)
    return graph, {spec for _, spec, _ in graph.unresolved}


TEMPLATE_TSCONFIG = """{
  "compilerOptions": {
    "target": "ES2020",
    /* Bundler mode */
    "moduleResolution": "bundler",
    // line comment
    "paths": { "@/*": ["./src/*"] },
  },
  "references": [{ "path": "./tsconfig.node.json" }]
}"""


def test_nested_tsconfig_with_block_comments_and_paths_without_baseurl(tmp_path):
    """The layout that produced 208 false positives on fastapi/full-stack-fastapi-template."""
    graph, unresolved = _project(tmp_path, {
        "frontend/package.json": "{}",
        "frontend/tsconfig.json": TEMPLATE_TSCONFIG,
        "frontend/src/components/ui/dialog.tsx": "export const Dialog = () => null;",
        "frontend/src/routes/items.tsx": 'import { Dialog } from "@/components/ui/dialog";',
    })
    assert not unresolved
    assert ("frontend/src/routes/items.tsx", "frontend/src/components/ui/dialog.tsx") in graph.edges


def test_tsconfig_extends_and_baseurl(tmp_path):
    graph, unresolved = _project(tmp_path, {
        "web/tsconfig.base.json": '{"compilerOptions": {"baseUrl": ".", "paths": {"#lib/*": ["lib/*"]}}}',
        "web/tsconfig.json": '{"extends": "./tsconfig.base.json", "compilerOptions": {"strict": true}}',
        "web/lib/math.ts": "export const add = (a: number, b: number) => a + b;",
        "web/app/main.ts": 'import { add } from "#lib/math";',
    })
    assert not unresolved
    assert ("web/app/main.ts", "web/lib/math.ts") in graph.edges


def test_assets_css_and_root_absolute_imports_resolve_on_disk(tmp_path):
    _, unresolved = _project(tmp_path, {
        "frontend/package.json": "{}",
        "frontend/public/assets/logo.svg": "<svg/>",
        "frontend/src/index.css": "body {}",
        "frontend/src/data.json": "{}",
        "frontend/src/raw.txt": "x",
        "frontend/src/main.tsx": (
            'import "./index.css";\nimport logo from "/assets/logo.svg";\n'
            'import data from "./data.json";\nimport raw from "./raw.txt?raw";\n'),
    })
    assert not unresolved


def test_genuinely_missing_imports_are_still_reported(tmp_path):
    _, unresolved = _project(tmp_path, {
        "frontend/package.json": "{}",
        "frontend/tsconfig.json": TEMPLATE_TSCONFIG,
        "frontend/src/main.tsx": (
            'import "./missing.css";\nimport x from "/assets/missing.svg";\n'
            'import { y } from "@/gone/module";\nimport { z } from "./nope";\n'),
    })
    assert unresolved == {"./missing.css", "/assets/missing.svg", "@/gone/module", "./nope"}


def test_configured_alias_with_missing_target_is_internal_not_npm(tmp_path):
    """DET-03: a prefix from the project's own tsconfig `paths` must not be treated as a package."""
    graph, unresolved = _project(tmp_path, {
        "tsconfig.json": '{"compilerOptions": {"baseUrl": ".", "paths": {"@lib/*": ["src/lib/*"]}}}',
        "src/index.ts": 'import { a } from "@lib/absent";\nimport React from "react";',
    })
    assert unresolved == {"@lib/absent"}
    assert "react" in graph.external and "@lib" not in graph.external


def test_unresolved_findings_only_for_real_breaks(tmp_path):
    graph, _ = _project(tmp_path, {
        "frontend/package.json": "{}",
        "frontend/tsconfig.json": TEMPLATE_TSCONFIG,
        "frontend/src/a.ts": "export const a = 1;",
        "frontend/src/b.ts": 'import { a } from "@/a";\nimport { q } from "./q";',
    })
    _, findings = analyze_graph(graph, set())
    broken = [f for f in findings if f.rule_id == "unresolved-import"]
    assert [f.title for f in broken] == ["Import './q' does not resolve to a file"]
