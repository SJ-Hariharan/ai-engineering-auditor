"""Shallow, locked-down clone of a public GitHub repository."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.core.config import get_settings
from app.ingestion.workspace import IngestionError
from app.sandbox.process import run_tool
from app.schemas import GITHUB_URL_RE

GIT_HARDENING = [
    "-c", "protocol.allow=never",
    "-c", "protocol.https.allow=always",
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.symlinks=false",
    "-c", "submodule.recurse=false",
    "-c", "filter.lfs.smudge=",
    "-c", "filter.lfs.process=",
    "-c", "filter.lfs.required=false",
]


def clone(url: str, branch: str | None, dest: Path) -> str:
    """Clone `url` into `dest`; returns the commit SHA. Raises IngestionError."""
    if not GITHUB_URL_RE.match(url):
        raise IngestionError("Only https://github.com/<owner>/<repo> URLs are supported")
    s = get_settings()
    argv = ["git", *GIT_HARDENING, "clone", "--depth", "1", "--no-tags", "--single-branch"]
    if branch:
        argv += ["--branch", branch]
    argv += ["--", url + ".git", str(dest)]
    res = run_tool(
        argv,
        timeout=s.clone_timeout_seconds,
        env_extra={"GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1",
                   "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
        # SEC-05: stop the clone as soon as it grows past the limit, not after it finishes.
        abort_if=lambda: _dir_size(dest) > s.max_extracted_bytes,
    )
    if res.aborted:
        shutil.rmtree(dest, ignore_errors=True)
        raise IngestionError(f"Repository exceeds the {s.max_extracted_bytes // (1024 * 1024)} MB size limit")
    if res.timed_out:
        shutil.rmtree(dest, ignore_errors=True)
        raise IngestionError("Cloning the repository timed out")
    if res.returncode != 0:
        msg = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else "git clone failed"
        raise IngestionError(f"Could not clone repository: {msg[:300]}")
    sha = run_tool(["git", "-C", str(dest), "rev-parse", "HEAD"], timeout=15).stdout.strip()
    shutil.rmtree(dest / ".git", ignore_errors=True)  # history not needed; reduces attack surface
    _enforce_limits(dest)
    return sha


def _dir_size(root: Path) -> int:
    """Bytes under root (git objects included); errors from files that vanish mid-walk are ignored."""
    total = 0
    stack = [str(root)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _enforce_limits(root: Path) -> None:
    s = get_settings()
    total = 0
    count = 0
    for p in root.rglob("*"):
        if p.is_symlink():
            p.unlink()
            continue
        if p.is_file():
            count += 1
            total += p.stat().st_size
            if count > s.max_files or total > s.max_extracted_bytes:
                raise IngestionError("Repository exceeds the size or file-count limit")
