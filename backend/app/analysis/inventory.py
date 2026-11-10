"""File inventory, language/stack detection and entry-point discovery.

Pure file reading; nothing in the repository is executed.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

IGNORED_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".next", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "coverage", ".turbo", ".cache", "out",
    "site-packages", ".tox", ".idea", ".vscode", "vendor", ".yarn",
}
LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".cjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript",
    ".cts": "TypeScript",
}
OTHER_LANGS = {
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".rb": "Ruby", ".php": "PHP", ".cs": "C#",
    ".kt": "Kotlin", ".swift": "Swift", ".c": "C", ".cpp": "C++", ".html": "HTML",
    ".css": "CSS", ".scss": "CSS", ".sql": "SQL", ".sh": "Shell", ".vue": "Vue", ".svelte": "Svelte",
}
TEST_PATTERNS = [
    re.compile(r"(^|/)tests?/"), re.compile(r"(^|/)__tests__/"), re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"_test\.py$"), re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$"), re.compile(r"(^|/)e2e/"),
    re.compile(r"(^|/)conftest\.py$"),
]

PY_FRAMEWORKS = {
    "fastapi": "FastAPI", "flask": "Flask", "django": "Django", "starlette": "Starlette",
    "sqlalchemy": "SQLAlchemy", "pydantic": "Pydantic", "celery": "Celery", "pytest": "pytest",
    "streamlit": "Streamlit", "langchain": "LangChain", "openai": "OpenAI SDK",
    "anthropic": "Anthropic SDK", "psycopg": "PostgreSQL (psycopg)", "psycopg2": "PostgreSQL (psycopg)",
    "pymongo": "MongoDB", "redis": "Redis", "boto3": "AWS SDK",
}
JS_FRAMEWORKS = {
    "next": "Next.js", "react": "React", "vue": "Vue", "svelte": "Svelte", "@angular/core": "Angular",
    "express": "Express", "fastify": "Fastify", "@nestjs/core": "NestJS", "koa": "Koa",
    "hono": "Hono", "prisma": "Prisma", "@prisma/client": "Prisma", "drizzle-orm": "Drizzle",
    "mongoose": "MongoDB (Mongoose)", "pg": "PostgreSQL (pg)", "mysql2": "MySQL", "sequelize": "Sequelize",
    "typeorm": "TypeORM", "jest": "Jest", "vitest": "Vitest", "mocha": "Mocha",
    "@playwright/test": "Playwright", "cypress": "Cypress", "tailwindcss": "Tailwind CSS",
    "@supabase/supabase-js": "Supabase", "firebase": "Firebase", "openai": "OpenAI SDK",
    "@anthropic-ai/sdk": "Anthropic SDK", "electron": "Electron", "vite": "Vite",
}
TEST_FRAMEWORKS = {"pytest", "Jest", "Vitest", "Mocha", "Playwright", "Cypress"}
DATABASES = ("PostgreSQL", "MongoDB", "MySQL", "Redis", "Prisma", "Drizzle", "Sequelize",
             "TypeORM", "SQLAlchemy", "Supabase", "Firebase")


@dataclass
class SourceFile:
    path: str  # posix, relative to repo root
    language: str
    lines: int
    size: int
    is_test: bool


@dataclass
class Inventory:
    root: Path
    files: list[SourceFile] = field(default_factory=list)
    other_files: Counter = field(default_factory=Counter)
    total_files: int = 0
    skipped_large: int = 0
    manifests: list[str] = field(default_factory=list)
    js_deps: dict[str, str] = field(default_factory=dict)
    py_deps: set[str] = field(default_factory=set)
    package_json: dict = field(default_factory=dict)
    # Normalised names declared directly: runtime vs development/test-only.
    runtime_deps: set[str] = field(default_factory=set)
    dev_deps: set[str] = field(default_factory=set)

    def source(self, include_tests: bool = True) -> list[SourceFile]:
        return [f for f in self.files if include_tests or not f.is_test]


def is_test_path(path: str) -> bool:
    return any(p.search(path) for p in TEST_PATTERNS)


def walk(root: Path, max_file_bytes: int) -> Inventory:
    inv = Inventory(root=root)
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in IGNORED_DIRS for part in rel.parts[:-1]) or p.is_symlink() or not p.is_file():
            continue
        inv.total_files += 1
        posix = rel.as_posix()
        if p.name in {"package.json", "requirements.txt", "pyproject.toml", "Pipfile", "setup.py",
                      "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock",
                      "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "tsconfig.json"}:
            inv.manifests.append(posix)
        ext = p.suffix.lower()
        lang = LANG_BY_EXT.get(ext)
        if not lang:
            other = OTHER_LANGS.get(ext)
            if other:
                inv.other_files[other] += 1
            continue
        if p.name.endswith((".min.js", ".d.ts")):
            continue
        size = p.stat().st_size
        if size > max_file_bytes:
            inv.skipped_large += 1
            continue
        try:
            lines = p.read_bytes().count(b"\n") + 1
        except OSError:
            continue
        inv.files.append(SourceFile(posix, lang, lines, size, is_test_path(posix)))
    _read_manifests(inv)
    return inv


def norm_pkg(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def _py_name(spec: str) -> str:
    return re.split(r"[<>=!~\[; ]", spec.strip(), maxsplit=1)[0].lower()


DEV_GROUP = re.compile(r"(?i)^(dev|test|tests|testing|lint|docs?|typing|tests?-.*|dev-.*)$")


def _read_manifests(inv: Inventory) -> None:
    for m in inv.manifests:
        p = inv.root / m
        try:
            if p.name == "package.json" and "node_modules" not in m:
                data = json.loads(p.read_text("utf-8", "replace"))
                if m == "package.json":
                    inv.package_json = data
                for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                    deps = {k: str(v) for k, v in (data.get(key) or {}).items()}
                    inv.js_deps.update(deps)
                    (inv.dev_deps if key == "devDependencies" else inv.runtime_deps).update(
                        norm_pkg(k) for k in deps)
            elif p.name == "requirements.txt":
                for line in p.read_text("utf-8", "replace").splitlines():
                    name = _py_name(line)
                    if name and not name.startswith(("#", "-")):
                        inv.py_deps.add(name)
                        inv.runtime_deps.add(norm_pkg(name))
            elif p.name == "pyproject.toml":
                data = tomllib.loads(p.read_text("utf-8", "replace"))
                project = data.get("project") or {}
                runtime = list(project.get("dependencies") or [])
                dev: list[str] = []
                for gname, group in (project.get("optional-dependencies") or {}).items():
                    (dev if DEV_GROUP.match(gname) else runtime).extend(group)
                for group in (data.get("dependency-groups") or {}).values():
                    dev += [d for d in group if isinstance(d, str)]
                poetry = (data.get("tool") or {}).get("poetry") or {}
                runtime += [k for k in (poetry.get("dependencies") or {}) if k != "python"]
                for g in (poetry.get("group") or {}).values():
                    dev += list((g or {}).get("dependencies") or {})
                for d in runtime + dev:
                    if _py_name(d):
                        inv.py_deps.add(_py_name(d))
                inv.runtime_deps.update(norm_pkg(_py_name(d)) for d in runtime if _py_name(d))
                inv.dev_deps.update(norm_pkg(_py_name(d)) for d in dev if _py_name(d))
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            continue


def detect_stack(inv: Inventory) -> dict:
    by_lang: dict[str, dict[str, int]] = {}
    for f in inv.files:
        d = by_lang.setdefault(f.language, {"files": 0, "lines": 0})
        d["files"] += 1
        d["lines"] += f.lines
    languages = [{"name": k, **v} for k, v in sorted(by_lang.items(), key=lambda x: -x[1]["lines"])]
    languages += [{"name": k, "files": v, "lines": None} for k, v in inv.other_files.most_common(6)]

    frameworks: list[str] = []
    for dep in inv.py_deps:
        base = dep.replace("_", "-")
        if base in PY_FRAMEWORKS:
            frameworks.append(PY_FRAMEWORKS[base])
    for dep in inv.js_deps:
        if dep in JS_FRAMEWORKS:
            frameworks.append(JS_FRAMEWORKS[dep])
    frameworks = sorted(set(frameworks))
    pm = []
    names = {Path(m).name for m in inv.manifests}
    for fname, label in (("package-lock.json", "npm"), ("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"),
                         ("poetry.lock", "Poetry"), ("uv.lock", "uv"), ("requirements.txt", "pip"),
                         ("Pipfile", "Pipenv")):
        if fname in names:
            pm.append(label)
    return {
        "languages": languages,
        "frameworks": [f for f in frameworks if f not in TEST_FRAMEWORKS],
        "test_frameworks": [f for f in frameworks if f in TEST_FRAMEWORKS],
        "databases": [f for f in frameworks if f.startswith(DATABASES)],
        "package_managers": pm,
        "manifests": inv.manifests[:50],
        "containerized": "Dockerfile" in names,
    }


ENTRY_NAMES = {
    "main.py": "Python entry module", "app.py": "Application module", "manage.py": "Django management",
    "wsgi.py": "WSGI entry", "asgi.py": "ASGI entry", "__main__.py": "Python package entry",
    "server.js": "Node server", "server.ts": "Node server", "index.js": "Package/app entry",
    "index.ts": "Package/app entry", "main.ts": "Application entry", "main.tsx": "Frontend entry",
    "App.tsx": "React root component", "App.jsx": "React root component", "cli.py": "CLI entry",
}


def entry_points(inv: Inventory) -> list[dict]:
    found: list[dict] = []
    paths = {f.path for f in inv.files}
    pkg = inv.package_json
    for key in ("main", "module"):
        if isinstance(pkg.get(key), str):
            found.append({"file": pkg[key].lstrip("./"), "kind": f"package.json `{key}`",
                          "reason": "Declared in package.json"})
    for name, cmd in (pkg.get("scripts") or {}).items():
        if name in {"start", "dev", "serve"} and isinstance(cmd, str):
            found.append({"file": None, "kind": f"npm script `{name}`", "reason": cmd[:200]})
    if isinstance(pkg.get("bin"), dict):
        for name, target in pkg["bin"].items():
            found.append({"file": str(target).lstrip("./"), "kind": "CLI binary", "reason": f"bin `{name}`"})
    for p in sorted(paths):
        if any(seg in p for seg in ("test", "spec")):
            continue
        name = p.rsplit("/", 1)[-1]
        depth = p.count("/")
        if name in ENTRY_NAMES and depth <= 2:
            found.append({"file": p, "kind": ENTRY_NAMES[name], "reason": "Conventional entry filename"})
        if re.search(r"(^|/)(app|pages)/(page|layout|_app|index)\.(t|j)sx?$", p) and depth <= 3:
            found.append({"file": p, "kind": "Next.js route", "reason": "App/pages router file"})
    seen, unique = set(), []
    for e in found:
        key = (e["file"], e["kind"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique[:25]


def directory_tree(inv: Inventory, max_depth: int = 2) -> list[dict]:
    """Aggregate source files by top-level directories for the structure view."""
    agg: dict[str, dict] = {}
    for f in inv.files:
        parts = f.path.split("/")
        key = "/".join(parts[:max_depth]) if len(parts) > max_depth else (
            "/".join(parts[:-1]) or ".")
        d = agg.setdefault(key, {"path": key, "files": 0, "lines": 0, "tests": 0})
        d["files"] += 1
        d["lines"] += f.lines
        d["tests"] += int(f.is_test)
    return sorted(agg.values(), key=lambda d: d["path"])
