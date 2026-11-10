"""Line-range edits: apply, validate and render as unified diffs."""

from __future__ import annotations

import difflib

from app.analysis.parsing import parse_file


class PatchError(Exception):
    pass


def apply_edits(text: str, edits: list[dict]) -> str:
    lines = text.splitlines(keepends=True)
    trailing_newline = text.endswith("\n")
    ordered = sorted(edits, key=lambda e: e["start"], reverse=True)
    last_start = None
    for e in ordered:
        start, end = e["start"], e["end"]
        if start < 1 or end < start - 1 or end > len(lines):
            raise PatchError("Edit range is outside the file")
        if last_start is not None and end >= last_start:
            raise PatchError("Two fixes modify overlapping lines; approve only one of them")
        current = "".join(lines[start - 1:end])
        if current != e["original"]:
            raise PatchError("The file no longer matches the audited version")
        repl = e["replacement"]
        if repl and not repl.endswith("\n"):
            repl += "\n"
        lines[start - 1:end] = repl.splitlines(keepends=True)
        last_start = start
    out = "".join(lines)
    if not trailing_newline and out.endswith("\n") and text:
        out = out[:-1]
    return out


def unified_diff(path: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                        fromfile=f"a/{path}", tofile=f"b/{path}", n=3))


def check_syntax(path: str, before: str, after: str) -> None:
    """Reject a change that introduces parse errors the original did not have."""
    old = parse_file(path, before.encode())
    new = parse_file(path, after.encode())
    if old is None or new is None:
        return
    if len(new.syntax_errors) > len(old.syntax_errors):
        raise PatchError("The proposed change does not parse; it was rejected")


def make_edit(lines: list[str], start: int, end: int, replacement: str) -> dict:
    """Build an edit from 1-based inclusive line numbers on keepends=True lines."""
    return {"start": start, "end": end, "original": "".join(lines[start - 1:end]),
            "replacement": replacement}
