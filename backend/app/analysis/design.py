"""Database and API design analysis.

Static and deterministic: files are read and parsed, never executed. Two parts:

* Database: schema extraction (SQLAlchemy / SQLModel, Django, Prisma, raw SQL ``CREATE TABLE``)
  plus a few well-evidenced design findings (N+1 style queries in loops, ``SELECT *``,
  unindexed foreign keys, ORM usage without migrations).
* API: endpoint extraction (framework decorators, Express-style calls, Next.js route handlers)
  plus heuristic findings (mutation routes without visible auth, naming, verbs in paths,
  unpaginated list endpoints).

Heuristic findings are marked ``subjective`` and say plainly what they cannot see.
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Node, Parser

from app.analysis.common import RawFinding, clip
from app.analysis.inventory import IGNORED_DIRS, Inventory
from app.analysis.parsing import ParsedFile, _language

log = logging.getLogger(__name__)

CAPS = {"models": 200, "fields": 40, "relations": 20, "endpoints": 500,
        "per_rule_findings": 20, "max_sql_bytes": 1_000_000, "max_walk_entries": 30_000}

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
NEXT_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
MIGRATION_DIRS = {"alembic", "migrations", "migrate", "drizzle"}
SKIP_DB_PATHS = re.compile(r"(^|/)(migrations?|alembic|seeds?|scripts?|fixtures?|examples?)(/|$)|seed",
                           re.I)

# ------------------------------------------------------------------ filesystem


@dataclass
class _Layout:
    sql_files: list[str] = field(default_factory=list)
    prisma_files: list[str] = field(default_factory=list)
    migration_dirs: list[str] = field(default_factory=list)
    next_middleware: list[str] = field(default_factory=list)


def _scan_layout(root: Path) -> _Layout:
    out = _Layout()
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        for d in dirnames:
            if d in MIGRATION_DIRS:
                out.migration_dirs.append(f"{rel_dir}/{d}".lstrip("/"))
        for name in sorted(filenames):
            seen += 1
            if seen > CAPS["max_walk_entries"]:
                return out
            rel = f"{rel_dir}/{name}".lstrip("/")
            low = name.lower()
            if low.endswith(".sql"):
                out.sql_files.append(rel)
            elif low.endswith(".prisma"):
                out.prisma_files.append(rel)
            elif low == "alembic.ini":
                out.migration_dirs.append(rel)
            elif re.fullmatch(r"middleware\.(ts|js|mjs)", low) and rel_dir in ("", "src"):
                out.next_middleware.append(rel)
    return out


def _read(root: Path, rel: str, limit: int | None = None) -> str:
    try:
        p = root / rel
        if limit is not None and p.stat().st_size > limit:
            return ""
        return p.read_text("utf-8", "replace")
    except OSError:
        return ""


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _snip(lines: list[str], line: int, before: int = 1, after: int = 1) -> str:
    start = max(line - 1 - before, 0)
    return clip("\n".join(lines[start:line + after]), 600)


# ------------------------------------------------------------------ tree-sitter scan
_LOOPS_PY = {"for_statement", "while_statement"}
_LOOPS_JS = {"for_statement", "for_in_statement", "while_statement", "do_statement"}
_FUNCS = {"function_definition", "lambda", "function_declaration", "function_expression",
          "arrow_function", "method_definition", "generator_function_declaration", "function"}
_STRONG_DB_METHODS = {
    "execute", "executemany", "executescript", "fetchone", "fetchall", "fetchrow", "fetchval",
    "fetch_one", "fetch_all", "findMany", "findUnique", "findFirst", "findUniqueOrThrow",
    "findFirstOrThrow", "findOne", "find_one", "filter_by", "count_documents", "scalars",
    "scalar_one", "scalar_one_or_none",
}
_RECEIVER_METHODS = {"query", "get", "filter", "first", "all", "one", "find", "raw", "count", "select"}
_DB_RECEIVER = re.compile(
    r"(?i)(\bsession\b|\bdb\b|\bconn(ection)?\b|\bcursor\b|\bcur\b|\bobjects\b|\bprisma\b|\bknex\b|"
    r"\bpool\b|\bcollection\b|\bsupabase\b|\brepo(sitory)?\b|\btrx?\b|\bdataSource\b|"
    r"\bentityManager\b|\bsequelize\b)")
_JS_ROUTER = re.compile(r"^(app|router|server|api|fastify)\.(\w+)$")
_HTTP = {"get", "post", "put", "patch", "delete", "head", "options", "all"}


@dataclass
class _LoopHit:
    loop_line: int
    call_line: int
    callee: str
    count: int = 1


@dataclass
class _TreeScan:
    loops: list[_LoopHit] = field(default_factory=list)
    # route line -> (end_line, handler name or None) for JS call-style routes
    js_routes: dict[int, tuple[int, str | None]] = field(default_factory=dict)


def _t(src: bytes, node: Node | None) -> str:
    return "" if node is None else src[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _is_db_call(callee: str, first_arg: str, python: bool) -> bool:
    if "." not in callee:
        return False
    recv, _, method = callee.rpartition(".")
    if method in _STRONG_DB_METHODS:
        return True
    if method in _RECEIVER_METHODS and _DB_RECEIVER.search(recv):
        # `session.get("key")` is a dict-style lookup (Flask/Django session), not a query.
        if python and method == "get" and first_arg[:1] in ("'", '"'):
            return False
        return True
    return False


def _scan_tree(path: str, src: bytes, grammar: str) -> _TreeScan:
    scan = _TreeScan()
    python = grammar == "python"
    loop_types = _LOOPS_PY if python else _LOOPS_JS
    call_type = "call" if python else "call_expression"
    tree = Parser(_language(grammar)).parse(src)
    hits: dict[int, _LoopHit] = {}
    # (node, innermost-loop id or None)
    stack: list[tuple[Node, int | None]] = [(tree.root_node, None)]
    while stack:
        node, loop = stack.pop()
        t = node.type
        if t in _FUNCS:
            loop = None  # a function defined inside a loop is not necessarily run per iteration
        if t == call_type:
            fn = node.child_by_field_name("function")
            callee = _t(src, fn)
            args = node.child_by_field_name("arguments")
            first = ""
            if args is not None and args.named_children:
                first = _t(src, args.named_children[0])
            if loop is not None and _is_db_call(callee, first, python):
                hit = hits.get(loop)
                if hit is None:
                    loop_line = next(n for n in _loop_nodes(node) if n.id == loop).start_point[0] + 1
                    hits[loop] = _LoopHit(loop_line, node.start_point[0] + 1, callee[:80])
                else:
                    hit.count += 1
            if not python:
                m = _JS_ROUTER.match(callee)
                if m and m.group(2).lower() in _HTTP and args is not None and args.named_children \
                        and args.named_children[0].type in ("string", "template_string"):
                    last = args.named_children[-1]
                    handler = _t(src, last) if last.type == "identifier" else None
                    scan.js_routes[node.start_point[0] + 1] = (node.end_point[0] + 1, handler)
        if t in loop_types:
            body = node.child_by_field_name("body")
            for child in node.children:
                inner = loop if body is None or child.id != body.id else node.id
                stack.append((child, inner))
            continue
        stack.extend((c, loop) for c in node.children)
    scan.loops = sorted(hits.values(), key=lambda h: h.loop_line)
    return scan


def _loop_nodes(node: Node):
    """Ancestors of `node` (used only to recover the loop node for a hit)."""
    n = node.parent
    while n is not None:
        yield n
        n = n.parent


# ------------------------------------------------------------------ schema extraction
def _py_models(path: str, src: bytes, text: str) -> list[dict]:
    tree = Parser(_language("python")).parse(src)
    out: list[dict] = []
    django_file = bool(re.search(r"^\s*(from\s+django\b|import\s+django\b)", text, re.M))
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        stack.extend(node.children)
        if node.type != "class_definition":
            continue
        bases = _t(src, node.child_by_field_name("superclasses"))
        body = node.child_by_field_name("body")
        if body is None:
            continue
        body_text = _t(src, body)
        orm = None
        if "SQLModel" in bases and "table=True" in bases:
            orm = "sqlmodel"
        elif re.search(r"__tablename__|\bMapped\[|=\s*(?:sa\.|sqlalchemy\.)?Column\(", body_text) \
                and not re.search(r"\bBaseModel\b", bases):
            orm = "sqlalchemy"
        elif django_file and re.search(r"\bmodels\.Model\b|\(\s*Model\s*[,)]", bases):
            orm = "django"
        if orm is None:
            continue
        fields: list[str] = []
        relations: list[dict] = []
        fk_unindexed: list[tuple[str, int, str]] = []
        for stmt in body.named_children:
            assign = stmt.named_children[0] if stmt.type == "expression_statement" and stmt.named_children \
                else None
            if assign is None or assign.type != "assignment":
                continue
            left = assign.child_by_field_name("left")
            if left is None or left.type != "identifier":
                continue
            name = _t(src, left)
            if name.startswith("__") or name == "Meta":
                continue
            rhs = _t(src, assign.child_by_field_name("right"))
            ann = _t(src, assign.child_by_field_name("type"))
            if orm == "django":
                is_field = bool(re.match(r"(models\.)?\w*(Field|Key)\(", rhs))
            elif orm == "sqlmodel":
                is_field = bool(ann)
            else:
                is_field = bool(re.search(r"\b(Column|mapped_column|relationship)\(", rhs)
                                or ann.startswith("Mapped["))
            if not is_field:
                continue
            fields.append(name)
            rel = re.search(r"\brelationship\(\s*['\"]?([\w.]+)", rhs)
            if rel:
                relations.append({"field": name, "target": rel.group(1), "kind": "relationship"})
            fk = re.search(r"\bForeignKey\(\s*['\"]([\w.]+)['\"]", rhs)
            if fk:
                relations.append({"field": name, "target": fk.group(1), "kind": "foreign_key"})
                if orm == "sqlalchemy" and not re.search(
                        r"index\s*=\s*True|primary_key\s*=\s*True|unique\s*=\s*True", rhs):
                    fk_unindexed.append((name, assign.start_point[0] + 1, _t(src, stmt)))
            if orm == "django":
                dj = re.match(r"(?:models\.)?(ForeignKey|OneToOneField|ManyToManyField)\(\s*['\"]?([\w.]+)", rhs)
                if dj:
                    relations.append({"field": name, "target": dj.group(2), "kind": dj.group(1)})
        # Composite indexes declared in __table_args__ / Index(...) count as indexed.
        table_args = re.findall(r"(?:Index|UniqueConstraint|PrimaryKeyConstraint)\([^)]*\)", body_text)
        fk_unindexed = [x for x in fk_unindexed
                        if not any(re.search(rf"['\"]{re.escape(x[0])}['\"]", ta) for ta in table_args)]
        out.append({
            "name": _t(src, node.child_by_field_name("name")), "file": path,
            "line": node.start_point[0] + 1, "orm": orm,
            "fields": fields[:CAPS["fields"]], "relations": relations[:CAPS["relations"]],
            "_fk_unindexed": fk_unindexed,
        })
    return out


def _prisma_models(path: str, text: str) -> list[dict]:
    out: list[dict] = []
    names = set(re.findall(r"^\s*model\s+(\w+)\s*\{", text, re.M))
    for m in re.finditer(r"^\s*model\s+(\w+)\s*\{(.*?)^\s*\}", text, re.M | re.S):
        fields: list[str] = []
        relations: list[dict] = []
        for line in m.group(2).splitlines():
            line = line.split("//")[0].strip()
            fm = re.match(r"(\w+)\s+(\w+)([?\[\]]*)", line)
            if not fm or line.startswith("@@"):
                continue
            fields.append(fm.group(1))
            if fm.group(2) in names or "@relation" in line:
                relations.append({"field": fm.group(1), "target": fm.group(2), "kind": "relation"})
        out.append({"name": m.group(1), "file": path, "line": _line_of(text, m.start()), "orm": "prisma",
                    "fields": fields[:CAPS["fields"]], "relations": relations[:CAPS["relations"]]})
    return out


_SQL_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?([\w.]+)[`\"\]]?\s*\(", re.I)
_SQL_NON_COLUMN = {"primary", "foreign", "constraint", "unique", "key", "index", "check", "exclude"}


def _sql_models(path: str, text: str) -> list[dict]:
    out: list[dict] = []
    for m in _SQL_TABLE.finditer(text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        body = text[m.end():i - 1]
        parts, buf, d = [], "", 0
        for ch in body:
            if ch == "(":
                d += 1
            elif ch == ")":
                d -= 1
            if ch == "," and d == 0:
                parts.append(buf)
                buf = ""
            else:
                buf += ch
        parts.append(buf)
        fields, relations = [], []
        for part in parts:
            tokens = part.strip().split()
            if not tokens:
                continue
            first = tokens[0].strip("`\"[]")
            ref = re.search(r"REFERENCES\s+[`\"]?([\w.]+)", part, re.I)
            if first.lower() not in _SQL_NON_COLUMN:
                fields.append(first)
            if ref:
                relations.append({"field": first if first.lower() not in _SQL_NON_COLUMN else "",
                                  "target": ref.group(1), "kind": "foreign_key"})
        out.append({"name": m.group(1), "file": path, "line": _line_of(text, m.start()), "orm": "sql",
                    "fields": fields[:CAPS["fields"]], "relations": relations[:CAPS["relations"]]})
    return out


# ------------------------------------------------------------------ API extraction
@dataclass
class _Endpoint:
    method: str
    path: str
    file: str
    line: int
    handler: str | None
    start: int  # handler line range, 1-based inclusive (decorators/params included)
    end: int
    framework: str

    def public(self) -> dict:
        return {"method": self.method, "path": self.path, "file": self.file, "line": self.line,
                "handler": self.handler}


_PARAM = [(re.compile(r"<(?:\w+:)?(\w+)>"), r"{\1}"), (re.compile(r"(?<=/):(\w+)"), r"{\1}"),
          (re.compile(r"\[\[?\.\.\.(\w+)\]?\]"), r"{\1}"), (re.compile(r"\[(\w+)\]"), r"{\1}")]


def _norm_path(p: str) -> str:
    for rx, rep in _PARAM:
        p = rx.sub(rep, p)
    p = re.sub(r"/{2,}", "/", p)
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/") or "/"


def _py_prefixes(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(r"(\w+)\s*=\s*(?:\w+\.)?(?:APIRouter|Blueprint)\(([^)]*)\)", text):
        pm = re.search(r"(?:prefix|url_prefix)\s*=\s*['\"]([^'\"]*)['\"]", m.group(2))
        if pm:
            out[m.group(1)] = pm.group(1)
    return out


def _next_path(rel: str) -> tuple[str, str] | None:
    """(route path, kind) for Next.js `app/**/route.ts` or `pages/api/**`."""
    m = re.search(r"(?:^|/)app/(.*?)/?route\.(?:ts|js|mjs)$", rel)
    if m:
        segs = [s for s in m.group(1).split("/") if s and not (s.startswith("(") and s.endswith(")"))
                and not s.startswith("@")]
        return _norm_path("/".join(segs)), "next-app"
    m = re.search(r"(?:^|/)pages/(api/.*)\.(?:ts|js|mjs|tsx|jsx)$", rel)
    if m:
        p = re.sub(r"/index$", "", m.group(1))
        return _norm_path(p), "next-pages"
    return None


def _extract_endpoints(root: Path, parsed: dict[str, ParsedFile], test_files: set[str],
                       scans: dict[str, _TreeScan], texts: dict[str, str]) -> list[_Endpoint]:
    eps: list[_Endpoint] = []
    seen: set[tuple] = set()

    def add(ep: _Endpoint) -> None:
        key = (ep.method, ep.path, ep.file, ep.line)
        if key not in seen:
            seen.add(key)
            eps.append(ep)

    for path, pf in sorted(parsed.items()):
        if path in test_files:
            continue
        text = texts.get(path, "")
        lines = text.splitlines()
        nxt = _next_path(path)
        if nxt:
            route_path, kind = nxt
            if kind == "next-app":
                for method in NEXT_METHODS:
                    fn = next((f for f in pf.functions if f.name == method and f.parent is None), None)
                    exported = re.search(rf"export\s+(?:async\s+)?(?:function|const)\s+{method}\b", text)
                    if not exported:
                        continue
                    line = _line_of(text, exported.start())
                    start, end = (fn.line, fn.end_line) if fn else (line, len(lines))
                    add(_Endpoint(method, route_path, path, line, method, min(start, line), end, "next"))
            elif re.search(r"export\s+default\b", text):
                dm = re.search(r"export\s+default\b", text)
                methods = sorted({m.upper() for m in re.findall(
                    r"req(?:uest)?\.method\s*[=!]==?\s*['\"](\w+)['\"]", text)}) or ["ANY"]
                for method in methods:
                    add(_Endpoint(method, route_path, path, _line_of(text, dm.start()), "default",
                                  1, len(lines), "next"))
            continue
        scan = scans.get(path)
        is_js = pf.grammar != "python"
        if is_js and not re.search(r"express|fastify|koa|hono|restify|Router\(", text):
            continue  # `api.get("/x")` in a frontend is an HTTP client call, not a route
        prefixes = _py_prefixes(text) if not is_js else {}
        for r in pf.routes:
            if not r.path.startswith("/") and not is_js and r.path:
                continue
            handler, start, end = r.handler, r.line, r.line
            prefix = ""
            if is_js:
                end, h = scan.js_routes.get(r.line, (r.line, None)) if scan else (r.line, None)
                handler = h or handler
            else:
                fn = min((f for f in pf.functions if f.name == r.handler and f.line >= r.line),
                         key=lambda f: f.line, default=None)
                end = fn.end_line if fn else r.line
                recv = re.match(r"\s*@\s*(\w+)\.", lines[r.line - 1] if 0 < r.line <= len(lines) else "")
                prefix = prefixes.get(recv.group(1), "") if recv else ""
            for method in [m.strip().upper() for m in r.method.split(",") if m.strip()] or ["GET"]:
                add(_Endpoint(method, _norm_path(prefix + r.path), path, r.line, handler, start, end,
                              "js" if is_js else "python"))
    return eps


# ------------------------------------------------------------------ auth heuristics
AUTH_RE = re.compile(
    r"(?i)(Depends\([^)]*(user|auth|token|permission|security|admin|verify|require|jwt|principal|"
    r"login|owner|bearer)|login_required|permission_required|jwt_required|requires?_auth|auth_required|"
    r"@auth\b|authenticat|authoriz|requireAuth|requireUser|getServerSession|getSession\b|getToken\b|"
    r"\bauth\(\)|currentUser|clerk|withAuth|isAuthenticated|verifyToken|verifyJwt|passport|jwt\.verify|"
    r"HTTPBearer|OAuth2PasswordBearer|get_current|current_user|request\.user|req\.user|req\.session|"
    r"ensureLoggedIn|\bprotect\b|UseGuards|permission_classes|IsAuthenticated|\bauthorization\b|"
    r"supabase\.auth|getUser\(\))")
GLOBAL_AUTH_RE = re.compile(
    r"(?i)(\.use\([^)]*(auth|jwt|passport|session|protect|guard)|before_request|before_app_request|"
    r"dependencies\s*=\s*[\[(][^\]\)]*Depends|include_router\([^)]*dependencies|"
    r"add_middleware\([^)]*(auth|jwt|session)|AuthenticationMiddleware)")
PUBLIC_PATH_RE = re.compile(
    r"(?i)(login|log-?in|signin|sign-in|signup|sign-up|register|logout|auth|token|webhook|callback|"
    r"forgot|reset|password|verify|oauth|session|health|ping|csrf|contact|subscribe|newsletter|"
    r"stripe|public|status)")
_VERB_RE = re.compile(
    r"^(get|create|delete|update|add|remove|set|fetch|save|edit|insert|destroy|post|put)"
    r"(?:[A-Z]|[-_][a-z])")


def _range_text(lines: list[str], ep: _Endpoint) -> str:
    return "\n".join(lines[max(ep.start - 1, 0):ep.end])


def _segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s and not s.startswith("{")]


# ------------------------------------------------------------------ findings
def _finding(**kw) -> RawFinding:
    return RawFinding(tool="design", **kw)


def _db_findings(root: Path, models: list[dict], layout: _Layout, parsed: dict[str, ParsedFile],
                 scans: dict[str, _TreeScan], texts: dict[str, str], test_files: set[str],
                 sql_texts: dict[str, str]) -> list[RawFinding]:
    out: list[RawFinding] = []
    cap = CAPS["per_rule_findings"]

    # db-query-in-loop ------------------------------------------------------
    n = 0
    for path, scan in sorted(scans.items()):
        if path in test_files or SKIP_DB_PATHS.search(path):
            continue
        lines = texts.get(path, "").splitlines()
        for hit in scan.loops:
            if n >= cap:
                break
            n += 1
            span = hit.call_line - hit.loop_line
            ev = _snip(lines, hit.loop_line, 0, min(span, 4)) if span <= 4 else \
                f"{lines[hit.loop_line - 1].strip()}\n  ...\n{lines[hit.call_line - 1].rstrip()}"
            out.append(_finding(
                rule_id="db-query-in-loop", category="architecture", severity="medium",
                confidence="medium", kind="objective", principle="Data Access Efficiency",
                title=f"Database call `{hit.callee}` inside a loop (possible N+1 query)",
                file=path, line=hit.loop_line, end_line=hit.call_line, evidence=clip(ev),
                fingerprint_key=f"{hit.callee}@{lines[hit.loop_line - 1].strip()[:80]}",
                explanation=(
                    f"A call that looks like a database operation (`{hit.callee}`) runs on line "
                    f"{hit.call_line}, inside the loop starting on line {hit.loop_line}"
                    + (f" ({hit.count} such calls in that loop)" if hit.count > 1 else "")
                    + ". This is the classic N+1 pattern: one query to get the rows, then one more "
                      "per row. The detection is by call name, so the call could also be a "
                      "deliberate batch or a non-database object."),
                impact="Latency and database load grow linearly with the number of iterations; a "
                       "page that is fast with 10 rows can time out with 10,000.",
                remediation="Fetch everything in one query (a JOIN, `IN (...)` / `WHERE id = ANY`, "
                            "`selectinload`/`prefetch_related`/`include`) before the loop, then look "
                            "rows up in memory.",
                references=["https://docs.sqlalchemy.org/en/20/orm/queryguide/relationships.html"
                            "#selectin-eager-loading"]))

    # db-select-star -------------------------------------------------------
    star = re.compile(r"(?i)\bselect\s+\*\s+from\b")
    candidates = {p: texts.get(p, "") for p in parsed if p not in test_files}
    candidates.update({p: t for p, t in sql_texts.items() if not SKIP_DB_PATHS.search(p)})
    n = 0
    for path, text in sorted(candidates.items()):
        if SKIP_DB_PATHS.search(path) and path not in parsed:
            continue
        lines = text.splitlines()
        found = [i + 1 for i, ln in enumerate(lines)
                 if star.search(ln) and not ln.lstrip().startswith(("#", "//", "*", "--", "/*"))]
        if not found or n >= cap:
            continue
        n += 1
        out.append(_finding(
            rule_id="db-select-star", category="architecture", severity="low", confidence="medium",
            kind="subjective", principle="Data Access Efficiency",
            title=f"`SELECT *` used in a query ({len(found)} place(s))", file=path, line=found[0],
            evidence=_snip(lines, found[0], 0, 0) + (
                f"\n(+{len(found) - 1} more at lines {', '.join(map(str, found[1:6]))})"
                if len(found) > 1 else ""),
            fingerprint_key=lines[found[0] - 1].strip()[:120],
            explanation="`SELECT *` returns every column, including ones added later, so the result "
                        "shape depends on the table definition rather than on what the code needs.",
            impact="Extra data over the wire, defeated covering indexes, and code that silently breaks "
                   "or leaks new sensitive columns when the schema changes.",
            remediation="List the columns the caller actually uses.",
            references=["https://use-the-index-luke.com/sql/select-list"]))

    # db-missing-index-on-fk -------------------------------------------------
    n = 0
    for m in models:
        for col, line, stmt in m.get("_fk_unindexed", []):
            if n >= cap:
                break
            n += 1
            out.append(_finding(
                rule_id="db-missing-index-on-fk", category="architecture", severity="low",
                confidence="low", kind="subjective", principle="Data Modelling",
                title=f"Foreign key `{m['name']}.{col}` has no index", file=m["file"], line=line,
                evidence=clip(stmt), fingerprint_key=f"{m['name']}.{col}",
                explanation="This column is declared as a ForeignKey without `index=True`. Some "
                            "databases (PostgreSQL, SQLite) do not index foreign keys automatically. "
                            "An index may exist in a migration or `__table_args__` that this check "
                            "cannot match, and tiny tables do not need one.",
                impact="Joins and `WHERE fk = ?` lookups on this column, and cascading deletes of the "
                       "parent row, become sequential scans as the table grows.",
                remediation="Add `index=True` to the column (or an `Index(...)` in `__table_args__`) "
                            "if you filter or join on it.",
                references=["https://www.postgresql.org/docs/current/ddl-constraints.html"
                            "#DDL-CONSTRAINTS-FK"]))

    # db-raw-sql-no-migrations -----------------------------------------------
    schema_sources = [m for m in models if not SKIP_DB_PATHS.search(m["file"])]
    if schema_sources and not layout.migration_dirs:
        first = schema_sources[0]
        orms = sorted({m["orm"] for m in schema_sources})
        out.append(_finding(
            rule_id="db-raw-sql-no-migrations", category="architecture", severity="info",
            confidence="medium", kind="subjective", principle="Data Modelling",
            title="Database schema defined in code but no migrations directory found",
            file=first["file"], line=first["line"],
            evidence=f"{len(schema_sources)} model/table definition(s) ({', '.join(orms)}); no "
                     "`alembic/`, `migrations/`, `drizzle/`, `prisma/migrations/` or `alembic.ini` found",
            fingerprint_key="no-migrations",
            explanation="Schema definitions were found, but no conventional migrations location. "
                        "Migrations may live outside this repository, or the schema may be created "
                        "with `create_all()` / `prisma db push`.",
            impact="Without versioned migrations, schema changes are hard to review, reproduce across "
                   "environments, or roll back safely.",
            remediation="Adopt a migration tool (Alembic, Django migrations, Prisma Migrate, Drizzle Kit) "
                        "and commit the migration files.",
            references=["https://alembic.sqlalchemy.org/en/latest/tutorial.html"]))
    return out


def _is_list_route(ep: _Endpoint) -> bool:
    segs = ep.path.split("/")
    if ep.method != "GET" or any(s.startswith("{") for s in segs):
        return False
    last = next((s for s in reversed(segs) if s), "")
    return len(last) > 3 and last.endswith("s") and not last.endswith(("ss", "us", "is")) \
        and last.lower() not in {"status", "address", "settings", "analytics", "news", "metrics"}


_UNBOUNDED = [
    (re.compile(r"\.all\(\)"), "`.all()` returns every row"),
    (re.compile(r"\bfindMany\((?![^)]*\b(take|first|limit)\b)"), "`findMany(...)` without `take`"),
    (re.compile(r"(?is)\bselect\b[^;`'\"]*\bfrom\b(?![^;`'\"]*\b(limit|top|fetch\s+first)\b)"),
     "`SELECT` without `LIMIT`"),
]
_PAGINATION = re.compile(r"(?i)\b(limit|offset|page|per_?page|page_?size|take|skip|cursor|paginate|"
                         r"first|after)\b")


def _api_findings(eps: list[_Endpoint], texts: dict[str, str], layout: _Layout, root: Path,
                  ) -> tuple[list[RawFinding], dict]:
    out: list[RawFinding] = []
    cap = CAPS["per_rule_findings"]
    line_cache = {p: t.splitlines() for p, t in texts.items()}

    next_global_auth = any(AUTH_RE.search(_read(root, m)) for m in layout.next_middleware)

    # api-unauthenticated-mutation ------------------------------------------
    n = 0
    candidates = 0
    for ep in eps:
        if ep.method not in MUTATING or PUBLIC_PATH_RE.search(ep.path):
            continue
        lines = line_cache.get(ep.file, [])
        if AUTH_RE.search(_range_text(lines, ep)) or GLOBAL_AUTH_RE.search(texts.get(ep.file, "")):
            continue
        if ep.framework == "next" and next_global_auth:
            continue
        candidates += 1
        if n >= cap:
            continue
        n += 1
        out.append(_finding(
            rule_id="api-unauthenticated-mutation", category="security", severity="medium",
            confidence="low", kind="subjective", principle="API Security",
            title=f"`{ep.method} {ep.path}` changes state with no visible authentication",
            file=ep.file, line=ep.line, evidence=_snip(lines, ep.line, 0, min(ep.end - ep.line, 3)),
            fingerprint_key=f"{ep.method} {ep.path}",
            explanation="This is a heuristic. Neither the handler (lines "
                        f"{ep.start}-{ep.end}) nor its file shows a recognisable authentication or "
                        "authorization check (e.g. `Depends(get_current_user)`, `@login_required`, "
                        "`getServerSession`, `requireAuth`). The app may still enforce auth elsewhere: "
                        "global middleware, an API gateway, or router-level dependencies registered in "
                        "another file.",
            impact="If no auth is enforced anywhere, anyone who can reach the server can create, "
                   "modify or delete data through this endpoint.",
            remediation="Confirm where authentication is enforced. If it is not, add an auth "
                        "dependency/middleware to this route and check that the caller may act on the "
                        "specific resource (not just that they are logged in).",
            references=["https://owasp.org/API-Security/editions/2023/en/0xa2-broken-authentication/"]))

    # naming / verbs ---------------------------------------------------------
    styles: dict[str, list[_Endpoint]] = {"camelCase": [], "kebab-case": [], "snake_case": []}
    verb_eps: list[tuple[_Endpoint, str]] = []
    for ep in eps:
        seen_styles: set[str] = set()
        for seg in _segments(ep.path):
            if re.search(r"[a-z][A-Z]", seg):
                seen_styles.add("camelCase")
            elif "-" in seg:
                seen_styles.add("kebab-case")
            elif "_" in seg:
                seen_styles.add("snake_case")
            if _VERB_RE.match(seg):
                verb_eps.append((ep, seg))
        for s in seen_styles:
            styles[s].append(ep)
    used = {k: v for k, v in styles.items() if v}
    if len(used) >= 2:
        anchor = next(iter(used.values()))[0]
        ev = "\n".join(f"{k}: " + ", ".join(sorted({f'{e.method} {e.path}' for e in v})[:3])
                       for k, v in used.items())
        out.append(_finding(
            rule_id="api-inconsistent-naming", category="architecture", severity="info",
            confidence="medium", kind="subjective", principle="API Design",
            title="Endpoint paths mix naming styles (" + ", ".join(used) + ")",
            file=anchor.file, line=anchor.line, evidence=ev, fingerprint_key="api-naming",
            explanation="Path segments use more than one convention across endpoints. No style is "
                        "wrong, but mixing them makes the API harder to guess and document.",
            impact="Minor: client developers must memorise exceptions; renames later are breaking changes.",
            remediation="Pick one style for path segments (kebab-case is the common REST convention) "
                        "and apply it to new endpoints; version or alias the old ones."))
    if verb_eps:
        uniq = sorted({(e.method, e.path) for e, _ in verb_eps})
        anchor = verb_eps[0][0]
        out.append(_finding(
            rule_id="api-verb-in-path", category="architecture", severity="low", confidence="medium",
            kind="subjective", principle="API Design",
            title=f"{len(uniq)} endpoint path(s) put an action verb in the URL",
            file=anchor.file, line=anchor.line,
            evidence="\n".join(f"{m} {p}" for m, p in uniq[:8]), fingerprint_key="api-verbs",
            explanation="REST-style APIs name resources in the path and express the action with the "
                        "HTTP method (`GET /users`, `POST /items`, `DELETE /users/{id}`). Paths like "
                        "`/getUsers` duplicate the verb the method already carries. RPC-style APIs "
                        "are a legitimate choice; this is a style judgement.",
            impact="Harder to cache and document consistently; invites one endpoint per action.",
            remediation="Rename to resource nouns and map the verb to the HTTP method."))

    # api-no-pagination -----------------------------------------------------
    n = 0
    for ep in eps:
        if not _is_list_route(ep) or n >= cap:
            continue
        lines = line_cache.get(ep.file, [])
        body = _range_text(lines, ep)
        if _PAGINATION.search(body):
            continue
        for rx, what in _UNBOUNDED:
            m = rx.search(body)
            if m:
                rel_line = ep.start + body.count("\n", 0, m.start())
                n += 1
                out.append(_finding(
                    rule_id="api-no-pagination", category="architecture", severity="low",
                    confidence="low", kind="subjective", principle="API Design",
                    title=f"`GET {ep.path}` appears to return an unbounded list",
                    file=ep.file, line=rel_line, evidence=_snip(lines, rel_line, 1, 1),
                    fingerprint_key=f"{ep.method} {ep.path}",
                    explanation=f"This looks like a list endpoint (plural path, no id) and the handler "
                                f"has {what}, with no limit/page/cursor parameter in sight. If the "
                                "table is small and bounded this is fine.",
                    impact="Response size and query time grow with the table; a single request can "
                           "exhaust memory or time out in production.",
                    remediation="Accept `limit`/`offset` (or a cursor), apply a sensible default and "
                                "maximum, and return paging metadata."))
                break

    mutating = [e for e in eps if e.method in MUTATING]
    meta = {"mutating_endpoints": len(mutating), "unauth_candidates": candidates,
            "unauth_findings_shown": min(candidates, cap),
            "global_auth_middleware_detected": bool(next_global_auth)}
    return out, meta


# ------------------------------------------------------------------ entry point
def analyze_design(root: Path, parsed: dict[str, ParsedFile], inv: Inventory,
                   test_files: set[str]) -> tuple[dict, list[RawFinding]]:
    layout = _scan_layout(root)
    texts: dict[str, str] = {}
    scans: dict[str, _TreeScan] = {}
    models: list[dict] = []

    for path, pf in sorted(parsed.items()):
        if path in test_files:
            continue
        raw = b""
        try:
            raw = (root / path).read_bytes()
        except OSError:
            continue
        text = raw.decode("utf-8", "replace")
        texts[path] = text
        try:
            scans[path] = _scan_tree(path, raw, pf.grammar)
            if pf.grammar == "python":
                models.extend(_py_models(path, raw, text))
        except Exception as exc:  # noqa: BLE001 - a grammar edge case must not abort the audit
            log.warning("design scan failed for %s: %s", path, exc)

    sql_texts: dict[str, str] = {}
    for rel in layout.sql_files:
        text = _read(root, rel, CAPS["max_sql_bytes"])
        if text:
            sql_texts[rel] = text
            models.extend(_sql_models(rel, text))
    for rel in layout.prisma_files:
        models.extend(_prisma_models(rel, _read(root, rel, CAPS["max_sql_bytes"])))

    findings = _db_findings(root, models, layout, parsed, scans, texts, test_files, sql_texts)

    eps = _extract_endpoints(root, parsed, test_files, scans, texts)
    api_findings, api_meta = _api_findings(eps, texts, layout, root)
    findings += api_findings

    by_method = Counter(e.method for e in eps)
    public_models = [{k: v for k, v in m.items() if not k.startswith("_")}
                     for m in models[:CAPS["models"]]]
    summary = {
        "models": public_models,
        "models_total": len(models),
        "orms": sorted({m["orm"] for m in models}),
        "migrations": sorted(set(layout.migration_dirs)),
        "api": {"endpoints": [e.public() for e in eps[:CAPS["endpoints"]]], "count": len(eps),
                "by_method": dict(sorted(by_method.items())), **api_meta},
        "method": "Static analysis: schema from ORM class bodies / schema.prisma / CREATE TABLE; "
                  "endpoints from framework decorators, Express-style calls and Next.js route files. "
                  "Findings marked subjective are heuristics and name what they cannot see.",
    }
    return summary, findings
