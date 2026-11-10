"""Inventory of scanner-suppression directives found in a scanned repository (SEC-01).

The scanners are configured to ignore these (see scanner_config/). This module only records
what the repository contained, so the report can say plainly that suppressions were present
and were not honoured.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from app.analysis.inventory import IGNORED_DIRS

SUPPRESSION_FILES = {
    ".semgrepignore": "semgrep",
    ".gitleaks.toml": "gitleaks",
    ".gitleaksignore": "gitleaks",
    ".trivyignore": "trivy",
    ".trivyignore.yaml": "trivy",
    "trivy.yaml": "trivy",
    "osv-scanner.toml": "osv-scanner",
}
INLINE_MARKERS = {
    "nosemgrep": re.compile(rb"\bnosem(?:grep)?\b"),
    "gitleaks:allow": re.compile(rb"gitleaks:allow"),
    "trivy:ignore": re.compile(rb"trivy:ignore"),
}
MAX_FILE_BYTES = 1024 * 1024


def find_suppressions(root: Path, limit: int = 50) -> dict:
    files: list[dict] = []
    inline: dict[str, int] = {name: 0 for name in INLINE_MARKERS}
    examples: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        rel_dir = Path(dirpath).relative_to(root)
        for name in filenames:
            path = Path(dirpath) / name
            rel = (rel_dir / name).as_posix()
            if name in SUPPRESSION_FILES and len(files) < limit:
                files.append({"file": rel, "scanner": SUPPRESSION_FILES[name]})
            if path.is_symlink():
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:4096]:
                continue  # binary
            for marker, pattern in INLINE_MARKERS.items():
                for m in pattern.finditer(data):
                    inline[marker] += 1
                    if len(examples) < limit:
                        examples.append({"file": rel, "line": data.count(b"\n", 0, m.start()) + 1,
                                         "marker": marker})
    total = len(files) + sum(inline.values())
    return {
        "honoured": False,
        "files": files,
        "inline": {k: v for k, v in inline.items() if v},
        "examples": examples,
        "total": total,
        "note": ("Scanner suppression directives in the repository were found and ignored, so "
                 "they cannot hide findings." if total else "No scanner suppression directives found."),
    }
