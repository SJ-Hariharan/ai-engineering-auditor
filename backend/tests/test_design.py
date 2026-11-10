from pathlib import Path

from app.analysis import inventory as inv_mod
from app.analysis.design import analyze_design
from app.analysis.parsing import parse_file
from app.analysis.pipeline import run_analysis
from app.core.config import Settings


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, "utf-8")
    return root


def design(root: Path):
    inv = inv_mod.walk(root, 1_000_000)
    parsed = {f.path: parse_file(f.path, (root / f.path).read_bytes()) for f in inv.files}
    tests = {f.path for f in inv.files if f.is_test}
    summary, findings = analyze_design(root, {k: v for k, v in parsed.items() if v}, inv, tests)
    return summary, findings


def rules(findings, rule_id):
    return [f for f in findings if f.rule_id == rule_id]


# ------------------------------------------------------------------ database
def test_sqlalchemy_models_and_fk_index(tmp_path):
    write(tmp_path, {"app/models.py": '''
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    editor_id = Column(Integer, ForeignKey("users.id"), index=True)
    author = relationship("User")


class NotAModel:
    x = 1
'''})
    summary, findings = design(tmp_path)
    names = {m["name"]: m for m in summary["models"]}
    assert set(names) == {"User", "Post"}
    assert names["Post"]["orm"] == "sqlalchemy"
    assert names["Post"]["fields"] == ["id", "user_id", "editor_id", "author"]
    assert {r["kind"] for r in names["Post"]["relations"]} == {"foreign_key", "relationship"}
    fk = rules(findings, "db-missing-index-on-fk")
    assert len(fk) == 1 and "Post.user_id" in fk[0].title
    assert fk[0].kind == "subjective" and fk[0].severity == "low"
    assert rules(findings, "db-raw-sql-no-migrations")


def test_no_migration_finding_when_alembic_present(tmp_path):
    write(tmp_path, {
        "models.py": "class A(Base):\n    __tablename__ = 'a'\n    id = Column(Integer, primary_key=True)\n",
        "alembic/env.py": "x = 1\n"})
    summary, findings = design(tmp_path)
    assert summary["models"] and not rules(findings, "db-raw-sql-no-migrations")


def test_django_prisma_and_sql_models(tmp_path):
    write(tmp_path, {
        "shop/models.py": "from django.db import models\n\nclass Item(models.Model):\n"
                          "    name = models.CharField(max_length=10)\n"
                          "    owner = models.ForeignKey('User', on_delete=models.CASCADE)\n",
        "prisma/schema.prisma": "model User {\n  id Int @id\n  posts Post[]\n}\n"
                                "model Post {\n  id Int @id\n  author User @relation(fields: [authorId])\n"
                                "  authorId Int\n}\n",
        "db/schema.sql": "CREATE TABLE IF NOT EXISTS orders (\n  id INTEGER PRIMARY KEY,\n"
                         "  user_id INTEGER REFERENCES users(id),\n  total NUMERIC(10, 2),\n"
                         "  PRIMARY KEY (id)\n);\n"})
    summary, _ = design(tmp_path)
    by = {m["name"]: m for m in summary["models"]}
    assert by["Item"]["orm"] == "django" and by["Item"]["relations"][0]["target"] == "User"
    assert by["User"]["orm"] == "prisma" and by["Post"]["relations"][0]["target"] == "User"
    assert by["orders"]["orm"] == "sql" and by["orders"]["fields"] == ["id", "user_id", "total"]
    assert by["orders"]["relations"][0]["target"] == "users"


def test_query_in_loop_python_and_js(tmp_path):
    write(tmp_path, {
        "svc.py": '''
def bad(session, ids):
    out = []
    for i in ids:
        out.append(session.query(User).filter(User.id == i).first())
    return out


def fine(ids):
    total = 0
    for i in ids:
        total += i * 2
    cache = {}
    for i in ids:
        cache.get(i)
        flask_session.get("user")
    return total


def hoisted(session, ids):
    rows = session.execute(select(User)).all()
    for r in rows:
        print(r)
''',
        "api.ts": '''
export async function f(ids: number[]) {
  for (const id of ids) {
    await prisma.user.findUnique({ where: { id } });
  }
  const names = ids.map((i) => String(i)).filter((n) => n);
  for (const n of names) { console.log(n.length); }
}
'''})
    _, findings = design(tmp_path)
    hits = rules(findings, "db-query-in-loop")
    assert {(f.file, f.line) for f in hits} == {("svc.py", 4), ("api.ts", 3)}
    py = next(f for f in hits if f.file == "svc.py")
    assert py.kind == "objective" and py.severity == "medium" and py.confidence == "medium"
    assert py.end_line == 5 and "session.query" in py.evidence and "for i in ids" in py.evidence


def test_loop_without_db_calls_not_flagged(tmp_path):
    write(tmp_path, {"util.py": "def f(xs):\n    for x in xs:\n        print(x.get('a'), x.filter)\n",
                     "util.js": "for (const x of xs) { items.filter((y) => y); map.get(x); }\n"})
    _, findings = design(tmp_path)
    assert not rules(findings, "db-query-in-loop")


def test_select_star(tmp_path):
    write(tmp_path, {"q.py": 'def f(cur):\n    cur.execute("SELECT * FROM users")\n    # SELECT * FROM x\n'
                             'def g(cur):\n    cur.execute("SELECT id FROM users")\n',
                     "tests/test_q.py": 'X = "SELECT * FROM users"\n'})
    _, findings = design(tmp_path)
    star = rules(findings, "db-select-star")
    assert [(f.file, f.line) for f in star] == [("q.py", 2)]
    assert star[0].kind == "subjective" and star[0].severity == "low"


# ------------------------------------------------------------------ API
FASTAPI = '''
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/api")


@router.post("/items")
def create_item(body: dict, user=Depends(current_user)):
    return body


@router.delete("/items/{item_id}")
def remove_item(item_id: int):
    return {}


@router.get("/users")
def list_users(db=Depends(get_db)):
    return db.query(User).all()


@router.get("/orders")
def list_orders(limit: int = 10, db=Depends(get_db)):
    return db.query(Order).limit(limit).all()
'''


def test_fastapi_endpoints_and_auth(tmp_path):
    write(tmp_path, {"app/routes.py": FASTAPI})
    summary, findings = design(tmp_path)
    api = summary["api"]
    assert api["count"] == 4 and api["by_method"] == {"DELETE": 1, "GET": 2, "POST": 1}
    assert {(e["method"], e["path"]) for e in api["endpoints"]} >= {("POST", "/api/items"),
                                                                    ("DELETE", "/api/items/{item_id}")}
    unauth = rules(findings, "api-unauthenticated-mutation")
    assert [f.fingerprint_key for f in unauth] == ["DELETE /api/items/{item_id}"]  # Depends(current_user) ok
    assert unauth[0].category == "security" and unauth[0].confidence == "low"
    assert "heuristic" in unauth[0].explanation
    pag = rules(findings, "api-no-pagination")
    assert [f.fingerprint_key for f in pag] == ["GET /api/users"]  # /orders has limit


def test_router_level_auth_dependency_suppresses(tmp_path):
    write(tmp_path, {"r.py": '''
router = APIRouter(dependencies=[Depends(get_current_user)])

@router.post("/things")
def make(): ...
'''})
    _, findings = design(tmp_path)
    assert not rules(findings, "api-unauthenticated-mutation")


def test_public_paths_not_flagged(tmp_path):
    write(tmp_path, {"r.py": '''
@app.post("/login")
def login(): ...

@app.post("/webhooks/stripe")
def hook(): ...
'''})
    _, findings = design(tmp_path)
    assert not rules(findings, "api-unauthenticated-mutation")


def test_express_routes(tmp_path):
    write(tmp_path, {"server.js": '''
const express = require("express");
const app = express();
app.post("/notes", requireAuth, (req, res) => res.json({}));
app.put("/notes/:id", (req, res) => { res.json({}); });
'''})
    summary, findings = design(tmp_path)
    assert {(e["method"], e["path"]) for e in summary["api"]["endpoints"]} == {
        ("POST", "/notes"), ("PUT", "/notes/{id}")}
    assert [f.fingerprint_key for f in rules(findings, "api-unauthenticated-mutation")] == [
        "PUT /notes/{id}"]


def test_frontend_http_client_calls_are_not_routes(tmp_path):
    write(tmp_path, {"web/client.ts": 'import axios from "axios";\nconst api = axios.create();\n'
                                      'export const load = () => api.post("/things", {});\n'})
    summary, _ = design(tmp_path)
    assert summary["api"]["count"] == 0


def test_nextjs_routes(tmp_path):
    write(tmp_path, {
        "app/api/users/route.ts": '''
import { getServerSession } from "next-auth";
export async function GET() { return Response.json(await prisma.user.findMany()); }
export async function POST(req: Request) {
  const session = await getServerSession();
  return Response.json({});
}
''',
        "app/api/(admin)/posts/[id]/route.ts": '''
export async function DELETE(req: Request) { return Response.json({}); }
''',
        "pages/api/hello.ts": 'export default function handler(req, res) { res.json({}); }\n'})
    summary, findings = design(tmp_path)
    eps = {(e["method"], e["path"]) for e in summary["api"]["endpoints"]}
    assert eps == {("GET", "/api/users"), ("POST", "/api/users"), ("DELETE", "/api/posts/{id}"),
                   ("ANY", "/api/hello")}
    assert [f.fingerprint_key for f in rules(findings, "api-unauthenticated-mutation")] == [
        "DELETE /api/posts/{id}"]
    assert [f.fingerprint_key for f in rules(findings, "api-no-pagination")] == ["GET /api/users"]


def test_naming_and_verbs(tmp_path):
    write(tmp_path, {"r.py": '''
@app.get("/getUsers")
def a(): ...

@app.get("/user-profiles")
def b(): ...

@app.get("/order_items")
def c(): ...

@app.get("/health")
def d(): ...
'''})
    _, findings = design(tmp_path)
    naming = rules(findings, "api-inconsistent-naming")
    assert len(naming) == 1 and naming[0].severity == "info" and "snake_case" in naming[0].title
    verbs = rules(findings, "api-verb-in-path")
    assert len(verbs) == 1 and "/getUsers" in verbs[0].evidence and "/health" not in verbs[0].evidence


def test_consistent_api_has_no_style_findings(tmp_path):
    write(tmp_path, {"r.py": '@app.get("/users")\ndef a(): ...\n\n@app.get("/user-profiles")\ndef b(): ...\n'})
    _, findings = design(tmp_path)
    assert not rules(findings, "api-inconsistent-naming") and not rules(findings, "api-verb-in-path")


def test_findings_have_required_fields(tmp_path):
    write(tmp_path, {"app/routes.py": FASTAPI, "q.py": 'x = "SELECT * FROM t"\n'})
    _, findings = design(tmp_path)
    assert findings
    for f in findings:
        assert f.tool == "design" and f.evidence and f.explanation and f.impact and f.remediation
        assert f.file and f.line and f.principle and f.fingerprint_key


def test_run_analysis_includes_design(tmp_path):
    write(tmp_path, {"app.py": FASTAPI})
    result = run_analysis(tmp_path, Settings(), run_scanners=False)
    assert result.summary["design"]["api"]["count"] == 4
    assert any(f["rule_id"] == "api-unauthenticated-mutation" for f in result.findings)
