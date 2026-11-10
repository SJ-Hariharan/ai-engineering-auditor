"""Remove credentials from text before it is sent to an external LLM."""

from __future__ import annotations

import re

PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-(?:ant-|proj-|live_|test_)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    # key = "value" style assignments of secret-looking names
    re.compile(r"(?i)((?:secret|password|passwd|token|api[_-]?key|private[_-]?key|client[_-]?secret)"
               r"[\w-]*\s*[:=]\s*)(['\"])([^'\"\n]{6,})\2"),
    re.compile(r"(?i)(postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s/]+:[^@\s]+@"),
]


def redact(text: str, extra_lines: set[int] | None = None) -> str:
    """Redact known secret shapes; also blank whole lines flagged by Gitleaks."""
    if extra_lines:
        lines = text.splitlines()
        for n in extra_lines:
            if 0 < n <= len(lines):
                lines[n - 1] = "[line redacted: contains a detected secret]"
        text = "\n".join(lines)
    for p in PATTERNS:
        if p.groups >= 3:
            text = p.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]{m.group(2)}", text)
        elif p.groups == 1:
            text = p.sub(lambda m: f"{m.group(1)}://[REDACTED]@", text)
        else:
            text = p.sub("[REDACTED]", text)
    return text
