"""Tree-sitter based structural extraction for Python, JavaScript and TypeScript."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import tree_sitter_javascript as ts_js
import tree_sitter_python as ts_py
import tree_sitter_typescript as ts_ts
from tree_sitter import Language, Node, Parser


@lru_cache
def _language(key: str) -> Language:
    return {
        "python": lambda: Language(ts_py.language()),
        "javascript": lambda: Language(ts_js.language()),
        "typescript": lambda: Language(ts_ts.language_typescript()),
        "tsx": lambda: Language(ts_ts.language_tsx()),
    }[key]()


def grammar_for(path: str) -> str | None:
    p = path.lower()
    if p.endswith(".py"):
        return "python"
    if p.endswith((".tsx",)):
        return "tsx"
    if p.endswith((".ts", ".mts", ".cts")):
        return "typescript"
    if p.endswith((".js", ".jsx", ".mjs", ".cjs")):
        return "javascript" if not p.endswith(".jsx") else "tsx"  # tsx grammar handles JSX well
    return None


@dataclass
class Function:
    name: str
    kind: str  # function | method | arrow
    line: int
    end_line: int
    params: int
    complexity: int
    max_nesting: int
    parent: str | None = None

    @property
    def length(self) -> int:
        return self.end_line - self.line + 1


@dataclass
class ClassInfo:
    name: str
    line: int
    end_line: int
    methods: int


@dataclass
class ErrorHandlingIssue:
    rule: str  # bare-except | swallowed-exception | empty-catch | broad-except
    line: int
    snippet: str


@dataclass
class Route:
    method: str
    path: str
    line: int
    handler: str | None


@dataclass
class ParsedFile:
    path: str
    grammar: str
    imports: list[tuple[str, int]] = field(default_factory=list)  # (specifier, line)
    functions: list[Function] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    error_issues: list[ErrorHandlingIssue] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    syntax_errors: list[int] = field(default_factory=list)
    calls: set[str] = field(default_factory=set)  # notable called names (for data-flow hints)

    def symbols(self) -> list[dict]:
        out = [{"name": c.name, "kind": "class", "line": c.line, "end_line": c.end_line,
                "methods": c.methods} for c in self.classes]
        out += [{"name": f.name, "kind": f.kind, "line": f.line, "end_line": f.end_line,
                 "params": f.params, "complexity": f.complexity, "parent": f.parent}
                for f in self.functions]
        return sorted(out, key=lambda s: s["line"])


PY_BRANCH = {"if_statement", "elif_clause", "for_statement", "while_statement", "except_clause",
             "conditional_expression", "boolean_operator", "for_in_clause", "if_clause",
             "case_clause", "with_statement"}
PY_NEST = {"if_statement", "for_statement", "while_statement", "try_statement", "with_statement",
           "match_statement"}
JS_BRANCH = {"if_statement", "for_statement", "for_in_statement", "while_statement", "do_statement",
             "catch_clause", "ternary_expression", "switch_case"}
JS_NEST = {"if_statement", "for_statement", "for_in_statement", "while_statement", "do_statement",
           "try_statement", "switch_statement"}
JS_FUNCS = {"function_declaration", "function_expression", "arrow_function", "method_definition",
            "generator_function_declaration", "function"}
JS_SERVER_HINT = re.compile(rb"express|fastify|koa|hono|restify|Router\(")
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "all", "route",
                "api_route", "websocket"}
NOTABLE_CALLS = re.compile(
    r"^(fetch|axios|requests|httpx|execute|query|raw|cursor|findMany|findUnique|create|insert|"
    r"update|delete|save|send|emit|publish|open|readFile|writeFile|subprocess|exec|spawn|eval)$"
)


def _text(src: bytes, node: Node | None) -> str:
    if node is None:
        return ""
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _note_call(name: str, pf: ParsedFile) -> None:
    parts = name.split(".")
    for part in (parts[0], parts[-1]):
        if NOTABLE_CALLS.match(part):
            pf.calls.add(part)


def _line(node: Node) -> int:
    return node.start_point[0] + 1


def parse_file(path: str, source: bytes) -> ParsedFile | None:
    grammar = grammar_for(path)
    if grammar is None:
        return None
    tree = Parser(_language(grammar)).parse(source)
    pf = ParsedFile(path=path, grammar=grammar)
    if grammar == "python":
        _walk_python(tree.root_node, source, pf, None)
    else:
        _walk_js(tree.root_node, source, pf, None)
    if grammar != "python" and pf.routes and not JS_SERVER_HINT.search(source):
        pf.routes = []  # e.g. an axios client named `api` in frontend code is not a server route
    if tree.root_node.has_error:
        pf.syntax_errors = _error_lines(tree.root_node)
    return pf


def _error_lines(root: Node, limit: int = 5) -> list[int]:
    out: list[int] = []
    stack = [root]
    while stack and len(out) < limit:
        n = stack.pop()
        if n.type == "ERROR" or n.is_missing:
            out.append(_line(n))
            continue
        if n.has_error:
            stack.extend(reversed(n.children))
    return sorted(set(out))


# ---------------------------------------------------------------- complexity
def _complexity(node: Node, branch_types: set[str], func_types: set[str], src: bytes) -> int:
    count = 1
    stack = list(node.children)
    while stack:
        n = stack.pop()
        if n.type in func_types:
            continue  # nested functions are measured separately
        if n.type in branch_types:
            count += 1
        elif n.type == "binary_expression":
            op = n.child_by_field_name("operator")
            if op is not None and _text(src, op) in ("&&", "||", "??"):
                count += 1
        stack.extend(n.children)
    return count


def _nesting(node: Node, nest_types: set[str], func_types: set[str]) -> int:
    best = 0
    stack: list[tuple[Node, int]] = [(c, 0) for c in node.children]
    while stack:
        n, depth = stack.pop()
        if n.type in func_types:
            continue
        d = depth + 1 if n.type in nest_types else depth
        best = max(best, d)
        stack.extend((c, d) for c in n.children)
    return best


# ---------------------------------------------------------------- python
PY_FUNCS = {"function_definition", "lambda"}


def _walk_python(node: Node, src: bytes, pf: ParsedFile, cls: str | None) -> None:
    for child in node.children:
        t = child.type
        if t == "import_statement":
            for name in child.children_by_field_name("name"):
                target = name.child_by_field_name("name") if name.type == "aliased_import" else name
                pf.imports.append((_text(src, target), _line(child)))
        elif t == "import_from_statement":
            mod = child.child_by_field_name("module_name")
            spec = _text(src, mod)
            if mod is not None and mod.type == "relative_import" and spec.strip(".") == "":
                # `from . import a, b` -> each name is a sibling module candidate
                for name in child.children_by_field_name("name"):
                    target = name.child_by_field_name("name") if name.type == "aliased_import" else name
                    pf.imports.append((spec + _text(src, target), _line(child)))
            else:
                # `from a.b import c` may import submodule a.b.c; emit the most specific form and
                # let the resolver fall back to `a.b` when `c` is just a name inside the module.
                names = [n.child_by_field_name("name") if n.type == "aliased_import" else n
                         for n in child.children_by_field_name("name")]
                for name in names or [None]:
                    leaf = _text(src, name) if name is not None else ""
                    pf.imports.append((f"{spec}.{leaf}" if leaf else spec, _line(child)))
        elif t == "decorated_definition":
            _py_routes(child, src, pf)
            _walk_python(child, src, pf, cls)
        elif t == "function_definition":
            name = _text(src, child.child_by_field_name("name"))
            params = child.child_by_field_name("parameters")
            n_params = len([p for p in (params.named_children if params else [])
                            if _text(src, p) not in ("self", "cls")])
            body = child.child_by_field_name("body") or child
            pf.functions.append(Function(
                name=name, kind="method" if cls else "function", line=_line(child),
                end_line=child.end_point[0] + 1, params=n_params,
                complexity=_complexity(body, PY_BRANCH, PY_FUNCS, src),
                max_nesting=_nesting(body, PY_NEST, PY_FUNCS), parent=cls))
            _walk_python(body, src, pf, None)
        elif t == "class_definition":
            name = _text(src, child.child_by_field_name("name"))
            body = child.child_by_field_name("body")
            methods = 0
            if body is not None:
                for c in body.named_children:
                    inner = c.child_by_field_name("definition") if c.type == "decorated_definition" else c
                    if inner is not None and inner.type == "function_definition":
                        methods += 1
            pf.classes.append(ClassInfo(name, _line(child), child.end_point[0] + 1, methods))
            if body is not None:
                _walk_python(body, src, pf, name)
        elif t == "except_clause":
            _py_except(child, src, pf)
            _walk_python(child, src, pf, cls)
        elif t == "call":
            fn = child.child_by_field_name("function")
            _note_call(_text(src, fn) if fn is not None else "", pf)
            _walk_python(child, src, pf, cls)
        else:
            _walk_python(child, src, pf, cls)


def _py_except(node: Node, src: bytes, pf: ParsedFile) -> None:
    named = [c for c in node.named_children if c.type != "block"]
    block = next((c for c in node.named_children if c.type == "block"), None)
    body_stmts = [c for c in (block.named_children if block else []) if c.type != "comment"]
    only_pass = bool(body_stmts) and all(
        c.type in ("pass_statement", "continue_statement")
        or (c.type == "expression_statement" and _text(src, c).strip() in ("...",))
        for c in body_stmts)
    header = _text(src, node).splitlines()[0][:120]
    if not named:
        pf.error_issues.append(ErrorHandlingIssue("bare-except", _line(node), header))
    if only_pass:
        pf.error_issues.append(ErrorHandlingIssue("swallowed-exception", _line(node),
                                                  _text(src, node)[:200]))
    elif named and re.match(r"except\s+\(?\s*(Exception|BaseException)\s*\)?\s*(as\s+\w+)?\s*:",
                            header):
        pf.error_issues.append(ErrorHandlingIssue("broad-except", _line(node), header))


def _py_routes(node: Node, src: bytes, pf: ParsedFile) -> None:
    definition = node.child_by_field_name("definition")
    handler = _text(src, definition.child_by_field_name("name")) if definition else None
    for dec in node.children:
        if dec.type != "decorator":
            continue
        text = _text(src, dec)
        m = re.match(r"@\s*[\w.]+\.(\w+)\(\s*[rfu]?['\"]([^'\"]*)['\"]", text)
        if m and m.group(1).lower() in HTTP_METHODS:
            method = m.group(1).upper()
            if method in ("ROUTE", "API_ROUTE"):
                mm = re.search(r"methods\s*=\s*\[([^\]]*)\]", text)
                method = ",".join(re.findall(r"['\"](\w+)['\"]", mm.group(1))) if mm else "GET"
            pf.routes.append(Route(method, m.group(2), _line(dec), handler))


# ---------------------------------------------------------------- javascript / typescript
def _js_func_name(node: Node, src: bytes) -> str:
    name = node.child_by_field_name("name")
    if name is not None:
        return _text(src, name)
    parent = node.parent
    if parent is not None:
        if parent.type == "variable_declarator":
            return _text(src, parent.child_by_field_name("name"))
        if parent.type in ("pair", "public_field_definition", "field_definition"):
            key = parent.child_by_field_name("key") or parent.child_by_field_name("name")
            return _text(src, key)
        if parent.type == "assignment_expression":
            return _text(src, parent.child_by_field_name("left"))
        if parent.type == "arguments":
            call = parent.parent
            fn = call.child_by_field_name("function") if call is not None else None
            return f"<callback:{_text(src, fn)[:40]}>" if fn is not None else "<anonymous>"
        if parent.type == "export_statement":
            return "default"
    return "<anonymous>"


def _walk_js(node: Node, src: bytes, pf: ParsedFile, cls: str | None) -> None:
    for child in node.children:
        t = child.type
        if t in ("import_statement", "export_statement"):
            source = child.child_by_field_name("source")
            if source is not None:
                pf.imports.append((_text(src, source).strip("'\"`"), _line(child)))
            _walk_js(child, src, pf, cls)
        elif t == "call_expression":
            fn = child.child_by_field_name("function")
            fn_text = _text(src, fn)
            args = child.child_by_field_name("arguments")
            first = args.named_children[0] if args is not None and args.named_children else None
            if fn_text in ("require", "import") and first is not None and first.type == "string":
                pf.imports.append((_text(src, first).strip("'\"`"), _line(child)))
            _note_call(fn_text, pf)
            m = re.match(r"^(app|router|server|api|fastify)\.(\w+)$", fn_text)
            if m and m.group(2).lower() in HTTP_METHODS and first is not None and first.type in (
                    "string", "template_string"):
                pf.routes.append(Route(m.group(2).upper(), _text(src, first).strip("'\"`"),
                                       _line(child), None))
            _walk_js(child, src, pf, cls)
        elif t in JS_FUNCS:
            name = _js_func_name(child, src)
            params = child.child_by_field_name("parameters") or child.child_by_field_name("parameter")
            n_params = len(params.named_children) if params is not None and params.type != "identifier" else (
                1 if params is not None else 0)
            body = child.child_by_field_name("body") or child
            length = child.end_point[0] - child.start_point[0] + 1
            kind = "method" if t == "method_definition" else ("arrow" if t == "arrow_function" else "function")
            # Skip trivial inline callbacks to keep the symbol list meaningful.
            if not (name.startswith("<") and length < 4):
                pf.functions.append(Function(
                    name=name, kind=kind, line=_line(child), end_line=child.end_point[0] + 1,
                    params=n_params, complexity=_complexity(body, JS_BRANCH, JS_FUNCS, src),
                    max_nesting=_nesting(body, JS_NEST, JS_FUNCS),
                    parent=cls if t == "method_definition" else None))
            _walk_js(body, src, pf, None)
        elif t in ("class_declaration", "class", "abstract_class_declaration"):
            name = _text(src, child.child_by_field_name("name")) or "<anonymous>"
            body = child.child_by_field_name("body")
            methods = len([c for c in (body.named_children if body is not None else [])
                           if c.type == "method_definition"])
            pf.classes.append(ClassInfo(name, _line(child), child.end_point[0] + 1, methods))
            if body is not None:
                _walk_js(body, src, pf, name)
        elif t == "catch_clause":
            body = child.child_by_field_name("body")
            stmts = [c for c in (body.named_children if body is not None else []) if c.type != "comment"]
            if not stmts:
                pf.error_issues.append(ErrorHandlingIssue("empty-catch", _line(child),
                                                          _text(src, child)[:160]))
            _walk_js(child, src, pf, cls)
        else:
            _walk_js(child, src, pf, cls)
