"""Deterministic, rule-specific fixes. Each one is small, reviewable and explained.

A fixer receives the file's lines and the finding, and returns
(edits, rationale, caveats) or None when it cannot produce a safe change.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from app.models import Finding
from app.remediation.patching import make_edit

FixResult = tuple[list[dict], str, list[str]]
Fixer = Callable[[list[str], Finding], FixResult | None]
FIXERS: dict[str, Fixer] = {}


def fixer(*rule_ids: str):
    def deco(fn: Fixer) -> Fixer:
        for r in rule_ids:
            FIXERS[r] = fn
        return fn
    return deco


def _line_range(lines: list[str], f: Finding) -> range:
    end = f.end_line or f.line
    return range(f.line, min(end, len(lines)) + 1)


def _replace_in_range(lines, f, pattern, repl, count=1) -> list[dict] | None:
    edits = []
    for n in _line_range(lines, f):
        new, k = re.subn(pattern, repl, lines[n - 1], count=count)
        if k:
            edits.append(make_edit(lines, n, n, new))
            break
    return edits or None


def _ensure_python_import(lines: list[str], module: str) -> list[dict]:
    if any(re.match(rf"\s*import\s+{module}\b|\s*from\s+{module}\s+import", ln) for ln in lines):
        return []
    insert_at = 1
    for i, ln in enumerate(lines[:60], 1):
        if re.match(r"(import |from \S+ import )", ln):
            insert_at = i + 1
        elif ln.startswith(("def ", "class ", "@")):
            break
    if insert_at == 1 and lines and lines[0].startswith(("#!", '"""', "'''")):
        insert_at = 2 if lines[0].startswith("#!") else 1
    return [{"start": insert_at, "end": insert_at - 1, "original": "", "replacement": f"import {module}\n"}]


@fixer("py-unsafe-deserialization")
def _yaml_safe_load(lines, f):
    edits = _replace_in_range(lines, f, r"\byaml\.load\(", "yaml.safe_load(")
    if not edits:
        return None  # pickle/marshal need design changes, not a mechanical fix
    for e in edits:  # drop an explicit unsafe Loader argument if present
        e["replacement"] = re.sub(r",\s*Loader\s*=\s*[\w.]+", "", e["replacement"])
    return edits, ("`yaml.safe_load` only constructs plain data types, so a malicious document "
                   "cannot instantiate arbitrary Python objects."), [
        "If this YAML relies on custom tags, they will now fail to load; register them on a SafeLoader subclass."]


@fixer("py-tls-verification-disabled")
def _py_verify(lines, f):
    edits = _replace_in_range(lines, f, r",\s*verify\s*=\s*False|verify\s*=\s*False\s*,\s*", "")
    if not edits:
        return None
    return edits, "Removes `verify=False` so the HTTPS certificate is validated again (the library default).", [
        "If the target uses a private CA, pass `verify=\"/path/to/ca-bundle.pem\"` instead of disabling checks."]


@fixer("py-flask-debug-enabled")
def _flask_debug(lines, f):
    edits = _replace_in_range(lines, f, r"debug\s*=\s*True", 'debug=os.environ.get("FLASK_DEBUG") == "1"')
    if not edits:
        return None
    return edits + _ensure_python_import(lines, "os"), (
        "Debug mode (and the interactive Werkzeug debugger) is now opt-in via the FLASK_DEBUG "
        "environment variable instead of always on."), ["Set FLASK_DEBUG=1 locally to keep debugging."]


@fixer("py-hardcoded-secret-key")
def _py_secret(lines, f):
    for n in _line_range(lines, f):
        line = lines[n - 1]
        m = re.match(r"(\s*)(SECRET_KEY|JWT_SECRET)(\s*=\s*)(['\"]).*?\4(.*)$", line, re.S)
        if m:
            new = f'{m.group(1)}{m.group(2)}{m.group(3)}os.environ["{m.group(2)}"]{m.group(5)}'
        else:
            m = re.match(r"(\s*)([\w.]+\.secret_key|[\w.]+\.config\[['\"]SECRET_KEY['\"]\])(\s*=\s*)(['\"]).*?\4(.*)$",
                         line, re.S)
            if not m:
                continue
            new = f'{m.group(1)}{m.group(2)}{m.group(3)}os.environ["SECRET_KEY"]{m.group(5)}'
        return [make_edit(lines, n, n, new)] + _ensure_python_import(lines, "os"), (
            "The signing key is now read from the environment, so it is no longer in source control."), [
            "Set the environment variable in every environment before deploying, or the app will fail to start.",
            "The old key was committed and must be considered leaked: generate a new one."]
    return None


@fixer("bare-except")
def _bare_except(lines, f):
    edits = _replace_in_range(lines, f, r"\bexcept\s*:", "except Exception:")
    if not edits:
        return None
    return edits, ("`except Exception:` still catches application errors but no longer swallows "
                   "KeyboardInterrupt and SystemExit."), [
        "Narrow further to the specific exception types this block expects."]


@fixer("js-tls-verification-disabled")
def _js_tls(lines, f):
    edits = _replace_in_range(lines, f, r"rejectUnauthorized\s*:\s*false", "rejectUnauthorized: true")
    if not edits:
        return None
    return edits, "Re-enables TLS certificate validation.", [
        "For a private CA, pass it via the `ca` option instead of disabling validation."]


@fixer("js-xss-inner-html")
def _inner_html(lines, f):
    edits = _replace_in_range(lines, f, r"\.innerHTML\s*=", ".textContent =")
    if not edits:
        return None
    return edits, "`textContent` inserts the value as text, so any markup in it cannot execute.", [
        "If this value is meant to contain HTML, sanitise it with DOMPurify.sanitize() instead."]


@fixer("empty-catch")
def _empty_catch(lines, f):
    for n in _line_range(lines, f):
        m = re.search(r"catch\s*(\((\w+)\))?\s*\{\s*\}", lines[n - 1])
        if m:
            var = m.group(2) or "error"
            new = lines[n - 1][:m.start()] + f"catch ({var}) {{ console.error({var}); }}" + lines[n - 1][m.end():]
            return [make_edit(lines, n, n, new)], "The error is now logged instead of silently discarded.", [
                "Consider rethrowing or showing the user an error state if the failure matters."]
    return None


def deterministic_fix(lines: list[str], finding: Finding) -> FixResult | None:
    fn = FIXERS.get(finding.rule_id)
    if fn is None or not finding.line or not finding.file:
        return None
    return fn(lines, finding)
