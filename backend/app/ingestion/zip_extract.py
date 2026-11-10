"""Defensive ZIP extraction.

Protects against: path traversal (`../`, absolute paths, drive letters),
symlinks, device files, zip bombs (total size, file count, compression ratio),
and oversized individual members. Extraction streams with a hard byte cap
because header sizes can lie.
"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path, PurePosixPath

from app.core.config import get_settings
from app.ingestion.workspace import IngestionError

MAX_RATIO = 200  # per-member compression ratio limit
SKIP_DIRS = {"__MACOSX"}


def _member_path(name: str) -> PurePosixPath | None:
    name = name.replace("\\", "/")
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or (p.parts and ":" in p.parts[0]):
        raise IngestionError(f"Archive contains an unsafe path: {name!r}")
    if not p.parts or p.parts[0] in SKIP_DIRS:
        return None
    return p


def extract_zip(archive: Path, dest: Path) -> None:
    s = get_settings()
    if not zipfile.is_zipfile(archive):
        raise IngestionError("Upload is not a valid ZIP archive")
    dest = dest.resolve()
    total = 0
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        if len(members) > s.max_files:
            raise IngestionError(f"Archive has more than {s.max_files} entries")
        declared = sum(m.file_size for m in members)
        if declared > s.max_extracted_bytes:
            raise IngestionError("Archive expands beyond the size limit")
        for m in members:
            rel = _member_path(m.filename)
            if rel is None:
                continue
            mode = (m.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise IngestionError(f"Archive contains a symlink: {m.filename!r}")
            if stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise IngestionError(f"Archive contains a special file: {m.filename!r}")
            if m.compress_size and m.file_size / max(m.compress_size, 1) > MAX_RATIO:
                raise IngestionError("Archive compression ratio is suspicious (possible zip bomb)")
            target = (dest / rel).resolve()
            if dest not in target.parents and target != dest:
                raise IngestionError(f"Archive entry escapes destination: {m.filename!r}")
            if m.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(m) as src, open(target, "wb") as out:
                while chunk := src.read(64 * 1024):
                    total += len(chunk)
                    if total > s.max_extracted_bytes:
                        raise IngestionError("Archive expands beyond the size limit")
                    out.write(chunk)
            target.chmod(0o600)
    _flatten_single_root(dest)


def _flatten_single_root(dest: Path) -> None:
    """GitHub-style ZIPs wrap everything in one top folder; unwrap it."""
    entries = [e for e in dest.iterdir() if not e.name.startswith(".")]
    if len(entries) == 1 and entries[0].is_dir() and not any(dest.glob(".*")):
        inner = entries[0]
        tmp = dest / ".__unwrap__"
        inner.rename(tmp)
        for child in tmp.iterdir():
            child.rename(dest / child.name)
        tmp.rmdir()
