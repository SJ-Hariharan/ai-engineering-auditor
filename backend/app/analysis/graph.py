"""Internal import graph: resolution, cycles, coupling metrics and broken imports."""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app.analysis.common import RawFinding
from app.analysis.parsing import ParsedFile

JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
NODE_BUILTINS = {
    "fs", "path", "os", "http", "https", "crypto", "url", "util", "events", "stream", "child_process",
    "buffer", "zlib", "net", "tls", "dns", "assert", "querystring", "readline", "worker_threads",
    "cluster", "process", "timers", "perf_hooks", "module", "vm",
}


@dataclass
class Graph:
    nodes: list[str]
    edges: set[tuple[str, str]] = field(default_factory=set)
    edge_lines: dict[tuple[str, str], int] = field(default_factory=dict)
    external: Counter = field(default_factory=Counter)
    unresolved: list[tuple[str, str, int]] = field(default_factory=list)  # (file, spec, line)

    def fan_out(self) -> Counter:
        return Counter(a for a, _ in self.edges)

    def fan_in(self) -> Counter:
        return Counter(b for _, b in self.edges)


# ------------------------------------------------------------------ resolution
def _python_index(paths: list[str]) -> dict[str, list[str]]:
    """Map every dotted suffix of each module path to the files that provide it."""
    index: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        if not p.endswith(".py"):
            continue
        parts = list(PurePosixPath(p).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        for i in range(len(parts)):
            index[".".join(parts[i:])].append(p)
    return index


def _resolve_python(spec: str, file: str, index: dict[str, list[str]], files: set[str]) -> str | None:
    if spec.startswith("."):
        level = len(spec) - len(spec.lstrip("."))
        base = PurePosixPath(file).parent
        for _ in range(level - 1):
            base = base.parent
        rest = spec.lstrip(".")
        for attempt in (rest, rest.rpartition(".")[0]) if "." in rest else (rest,):
            target = base / attempt.replace(".", "/") if attempt else base
            for cand in (f"{target}.py", f"{target}/__init__.py"):
                cand = cand.removeprefix("./")
                if cand in files:
                    return cand
        return None
    probe = spec
    while probe:
        hits = index.get(probe)
        if hits:
            # Prefer the candidate sharing the longest directory prefix with the importer.
            return max(hits, key=lambda h: (_common_prefix(h, file), -len(h)))
        probe = probe.rpartition(".")[0]
    return None


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(PurePosixPath(a).parts, PurePosixPath(b).parts, strict=False):
        if x != y:
            break
        n += 1
    return n


# ------------------------------------------------------------------ JS/TS module resolution
CONFIG_FILE = re.compile(r"^(tsconfig|jsconfig)(\.[\w-]+)?\.json$")
_JSONC_TOKENS = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.S)


def _load_jsonc(path: Path) -> dict:
    """tsconfig files are JSON with comments and trailing commas."""
    text = path.read_text("utf-8", "replace")
    text = _JSONC_TOKENS.sub(lambda m: m.group(0) if m.group(0).startswith('"') else "", text)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _paths_config(path: Path, root: Path, depth: int = 0) -> tuple[dict, str] | None:
    """(paths, base dir relative to root) for one config, following relative `extends`.

    `paths` resolve against `baseUrl` when set, otherwise against the folder of the config file
    that declares them (TypeScript semantics).
    """
    try:
        data = _load_jsonc(path)
    except (OSError, ValueError):
        return None
    inherited: tuple[dict, str] | None = None
    ext = data.get("extends")
    if isinstance(ext, str) and ext.startswith(".") and depth < 5:
        parent = (path.parent / ext).resolve()
        if parent.suffix != ".json":
            parent = parent.with_name(parent.name + ".json")
        if parent.is_file() and root in parent.parents:
            inherited = _paths_config(parent, root, depth + 1)
    opts = data.get("compilerOptions") or {}
    here = path.parent.relative_to(root).as_posix()
    here = "" if here == "." else here
    paths = opts.get("paths")
    if isinstance(paths, dict):
        base_url = opts.get("baseUrl")
        base = _normalize(f"{here}/{base_url}") if isinstance(base_url, str) else here
        return paths, base
    if isinstance(opts.get("baseUrl"), str) and inherited:
        return inherited[0], _normalize(f"{here}/{opts['baseUrl']}")
    return inherited


@dataclass
class JsResolver:
    root: Path
    code_files: set[str]
    all_files: set[str]
    # directory -> list of (alias prefix, [target dirs relative to root], configured?)
    aliases_by_dir: dict[str, list[tuple[str, list[str], bool]]]
    package_dirs: set[str]

    @classmethod
    def build(cls, root: Path, code_files: set[str]) -> JsResolver:
        from app.analysis.inventory import IGNORED_DIRS

        all_files: set[str] = set()
        configs: dict[str, list[Path]] = defaultdict(list)
        package_dirs: set[str] = set()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
            rel_dir = Path(dirpath).relative_to(root).as_posix()
            rel_dir = "" if rel_dir == "." else rel_dir
            for name in filenames:
                all_files.add(f"{rel_dir}/{name}" if rel_dir else name)
                if CONFIG_FILE.match(name):
                    configs[rel_dir].append(Path(dirpath) / name)
                if name == "package.json":
                    package_dirs.add(rel_dir)
        aliases_by_dir: dict[str, list[tuple[str, list[str], bool]]] = {}
        real_root = root.resolve()
        for d, paths in configs.items():
            entries: list[tuple[str, list[str], bool]] = []
            for cfg in sorted(paths):
                loaded = _paths_config(cfg.resolve(), real_root)
                if not loaded:
                    continue
                mapping, base = loaded
                for key, targets in mapping.items():
                    if not isinstance(targets, list):
                        continue
                    prefix = key.removesuffix("*")
                    dirs = [_normalize(f"{base}/{t.removesuffix('*')}") for t in targets if isinstance(t, str)]
                    entries.append((prefix, dirs, True))
            if entries:
                aliases_by_dir[d] = entries
        return cls(root, code_files, all_files, aliases_by_dir, package_dirs)

    def _nearest(self, file: str, candidates) -> str | None:
        d = str(PurePosixPath(file).parent)
        d = "" if d == "." else d
        while True:
            if d in candidates:
                return d
            if not d:
                return None
            d = str(PurePosixPath(d).parent)
            d = "" if d == "." else d

    def _aliases_for(self, file: str) -> list[tuple[str, list[str], bool]]:
        d = self._nearest(file, self.aliases_by_dir)
        if d is not None:
            return self.aliases_by_dir[d]
        pkg = self._nearest(file, self.package_dirs) or ""
        pre = f"{pkg}/" if pkg else ""
        return [("@/", [f"{pre}src", pkg], False), ("~/", [f"{pre}src", pkg], False)]

    def _lookup(self, target: str) -> tuple[str | None, bool]:
        """(code file to link, exists). Non-code files (css, svg, json...) exist but get no edge."""
        target = _normalize(target)
        for c in _js_candidates(target):
            if c in self.code_files:
                return c, True
        return None, target in self.all_files

    def resolve(self, spec: str, file: str) -> tuple[str | None, bool, bool]:
        """Returns (code file, resolved, is_internal_spec)."""
        spec = spec.split("?", 1)[0]  # Vite query suffixes: ?raw, ?url, ?worker
        if spec.startswith("."):
            hit, ok = self._lookup(str(PurePosixPath(file).parent / spec))
            return hit, ok, True
        if spec.startswith("/"):
            # Bundler root-absolute import: project root or its public/ folder.
            pkg = self._nearest(file, self.package_dirs) or ""
            for base in (f"{pkg}/public", pkg, "public", ""):
                hit, ok = self._lookup(f"{base}/{spec.lstrip('/')}")
                if ok:
                    return hit, True, True
            return None, False, True
        for prefix, dirs, configured in self._aliases_for(file):
            if prefix and spec.startswith(prefix):
                rest = spec[len(prefix):]
                for d in dirs:
                    hit, ok = self._lookup(f"{d}/{rest}")
                    if ok:
                        return hit, True, True
                # A prefix declared in the project's own tsconfig is internal by definition.
                return None, False, configured or prefix in ("@/", "~/")
        return None, False, False


def _js_candidates(target: str) -> list[str]:
    target = target.rstrip("/")
    stem = re.sub(r"\.(js|jsx|mjs|cjs)$", "", target)
    cands = [target] + [stem + e for e in JS_EXTS] + [f"{target}/index{e}" for e in JS_EXTS]
    return [str(PurePosixPath(c)).removeprefix("./") for c in cands]


def _normalize(path: str) -> str:
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _package_name(spec: str) -> str:
    if spec.startswith("@"):
        return "/".join(spec.split("/")[:2])
    return spec.split("/")[0].removeprefix("node:")


def build_graph(root: Path, parsed: dict[str, ParsedFile]) -> Graph:
    files = set(parsed)
    graph = Graph(nodes=sorted(files))
    py_index = _python_index(list(files))
    js = JsResolver.build(root, files) if any(pf.grammar != "python" for pf in parsed.values()) else None
    for path, pf in parsed.items():
        seen_external: set[str] = set()
        for spec, line in pf.imports:
            if not spec:
                continue
            if pf.grammar == "python":
                target = _resolve_python(spec, path, py_index, files)
                if target is None:
                    if spec.startswith("."):
                        graph.unresolved.append((path, spec, line))
                    elif spec.split(".")[0] not in seen_external:
                        seen_external.add(spec.split(".")[0])
                        graph.external[spec.split(".")[0]] += 1
                    continue
            else:
                target, resolved, internal = js.resolve(spec, path)
                if target is None:
                    if resolved:
                        continue  # existing non-code file (css, image, json...)
                    if internal:
                        graph.unresolved.append((path, spec, line))
                    elif not spec.startswith((".", "/")):
                        name = _package_name(spec)
                        if name not in NODE_BUILTINS and name not in seen_external:
                            seen_external.add(name)
                            graph.external[name] += 1
                    continue
            if target != path:
                graph.edges.add((path, target))
                graph.edge_lines.setdefault((path, target), line)
    return graph


# ------------------------------------------------------------------ cycles
def strongly_connected(nodes: list[str], edges: set[tuple[str, str]]) -> list[list[str]]:
    """Iterative Tarjan SCC; returns components with more than one node."""
    adj: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0
    for start in nodes:
        if start in index:
            continue
        work = [(start, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on_stack.add(v)
            recurse = False
            neighbours = adj[v]
            while i < len(neighbours):
                w = neighbours[i]
                i += 1
                if w not in index:
                    work.append((v, i))
                    work.append((w, 0))
                    recurse = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if recurse:
                continue
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    result.append(sorted(comp))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
    return result


def _cycle_path(component: list[str], edges: set[tuple[str, str]]) -> list[str]:
    """Find one concrete cycle inside an SCC to show as evidence."""
    members = set(component)
    adj = defaultdict(list)
    for a, b in edges:
        if a in members and b in members:
            adj[a].append(b)
    start = component[0]
    prev: dict[str, str | None] = {start: None}
    queue = [start]
    while queue:
        v = queue.pop(0)
        for w in sorted(adj[v]):
            if w == start:
                path = [v]
                while prev[path[-1]] is not None:
                    path.append(prev[path[-1]])  # type: ignore[arg-type]
                return list(reversed(path)) + [start]
            if w not in prev:
                prev[w] = v
                queue.append(w)
    return component + [component[0]]


# ------------------------------------------------------------------ findings + summary
def analyze_graph(graph: Graph, test_files: set[str]) -> tuple[dict, list[RawFinding]]:
    findings: list[RawFinding] = []
    fan_in, fan_out = graph.fan_in(), graph.fan_out()
    cycles = strongly_connected(graph.nodes, graph.edges)

    for comp in cycles:
        path = _cycle_path(comp, graph.edges)
        first = path[0]
        line = graph.edge_lines.get((path[0], path[1])) if len(path) > 1 else None
        findings.append(RawFinding(
            tool="graph", rule_id="circular-dependency", category="architecture",
            severity="medium" if len(comp) <= 4 else "high", confidence="high", kind="objective",
            principle="Modularity",
            title=f"Circular dependency between {len(comp)} modules",
            file=first, line=line, evidence=" → ".join(path),
            explanation="These modules import each other (directly or transitively). The import "
                        "path shown was resolved from the source; it is not a guess.",
            impact="Cycles make modules impossible to understand, test or reuse in isolation, can "
                   "cause partially-initialised imports at runtime (Python) or undefined values "
                   "(ES modules), and block clean layering.",
            remediation="Extract the shared code into a lower-level module that both depend on, "
                        "or invert one dependency (pass a callback/interface instead of importing).",
            fingerprint_key="|".join(sorted(comp))))

    prod_nodes = [n for n in graph.nodes if n not in test_files]
    n_prod = max(len(prod_nodes), 1)
    for node in prod_nodes:
        fo, fi = fan_out[node], fan_in[node]
        if fo >= 15:
            findings.append(RawFinding(
                tool="graph", rule_id="high-fan-out", category="architecture", severity="low",
                confidence="medium", kind="subjective", principle="Coupling",
                title=f"Module depends on {fo} internal modules", file=node,
                evidence=f"{node} imports {fo} internal modules.",
                explanation="A high number of outgoing dependencies usually means the module "
                            "coordinates too many concerns. Thresholds are heuristic (≥15).",
                impact="Changes elsewhere frequently ripple into this file; it is harder to test.",
                remediation="Group related dependencies behind a facade or split the module by "
                            "responsibility.", fingerprint_key=node))
        if fi >= max(8, int(n_prod * 0.25)) and fo >= 6:
            findings.append(RawFinding(
                tool="graph", rule_id="coupling-hub", category="architecture", severity="medium",
                confidence="medium", kind="subjective", principle="Coupling",
                title="Highly coupled hub module", file=node,
                evidence=f"Imported by {fi} modules and imports {fo} modules itself.",
                explanation="This module is both widely depended upon and depends on many others, "
                            "so it sits on many change paths.",
                impact="Edits here have a large blast radius; it is a likely source of regressions "
                       "and merge conflicts.",
                remediation="Separate the stable, widely used parts (types, constants, interfaces) "
                            "from the parts that change often.", fingerprint_key=node))

    for file, spec, line in graph.unresolved:
        findings.append(RawFinding(
            tool="graph", rule_id="unresolved-import", category="reliability", severity="high",
            confidence="medium", kind="objective",
            title=f"Import '{spec}' does not resolve to a file", file=file, line=line,
            evidence=f"{file}:{line} imports '{spec}', but no matching file exists in the repository.",
            explanation="Local imports were resolved against the repository's files (including "
                        "tsconfig path aliases). This one has no target. It may be generated at "
                        "build time, which is why confidence is medium.",
            impact="If the file is genuinely missing the application will fail to build or crash "
                   "at import time.",
            remediation="Fix the import path, add the missing module, or document the code "
                        "generation step that creates it.", fingerprint_key=f"{file}|{spec}"))

    summary = {
        "edges": len(graph.edges),
        "cycles": [_cycle_path(c, graph.edges) for c in cycles],
        "external_dependencies": [{"name": k, "imports": v} for k, v in graph.external.most_common(40)],
        "metrics": {
            n: {"fan_in": fan_in[n], "fan_out": fan_out[n],
                "instability": round(fan_out[n] / (fan_in[n] + fan_out[n]), 2)
                if (fan_in[n] + fan_out[n]) else 0.0}
            for n in graph.nodes
        },
    }
    return summary, findings


def graph_views(graph: Graph, test_files: set[str], max_nodes: int = 250) -> dict:
    """Two renderable views: directory-level (always small) and file-level (capped)."""
    def group(path: str) -> str:
        parts = path.split("/")
        return "/".join(parts[:2]) if len(parts) > 2 else (parts[0] if len(parts) > 1 else ".")

    dir_edges: Counter = Counter()
    dir_sizes: Counter = Counter()
    for n in graph.nodes:
        dir_sizes[group(n)] += 1
    for a, b in graph.edges:
        ga, gb = group(a), group(b)
        if ga != gb:
            dir_edges[(ga, gb)] += 1
    degree = Counter()
    for a, b in graph.edges:
        degree[a] += 1
        degree[b] += 1
    keep = {n for n, _ in degree.most_common(max_nodes)} if len(graph.nodes) > max_nodes else set(graph.nodes)
    return {
        "directories": {
            "nodes": [{"id": d, "files": c} for d, c in sorted(dir_sizes.items())],
            "edges": [{"source": a, "target": b, "weight": w} for (a, b), w in dir_edges.items()],
        },
        "files": {
            "truncated": len(graph.nodes) > max_nodes,
            "nodes": [{"id": n, "group": group(n), "test": n in test_files} for n in sorted(keep)],
            "edges": [{"source": a, "target": b} for a, b in sorted(graph.edges)
                      if a in keep and b in keep],
        },
    }
