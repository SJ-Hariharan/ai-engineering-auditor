"""Per-audit private workspace directories with expiry."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import get_settings


class IngestionError(Exception):
    """Raised for user-facing ingestion problems (bad archive, clone failure...)."""


def workspace_root() -> Path:
    root = get_settings().workspace_root.resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def create_workspace(audit_id: str) -> Path:
    path = workspace_root() / audit_id
    if path.exists():
        shutil.rmtree(path)
    (path / "src").mkdir(parents=True, mode=0o700)
    return path


def source_dir(workspace: Path) -> Path:
    return workspace / "src"


def expiry() -> datetime:
    return datetime.now(UTC) + timedelta(hours=get_settings().workspace_ttl_hours)


def delete_workspace(path: str | Path | None) -> None:
    if not path:
        return
    p = Path(path).resolve()
    # Never delete anything outside the workspace root.
    if p.parent == workspace_root() and p.exists():
        shutil.rmtree(p, ignore_errors=True)


def safe_join(base: Path, relative: str) -> Path:
    """Resolve `relative` under `base`, rejecting traversal and symlink escapes."""
    if "\x00" in relative:
        raise ValueError("invalid path")
    base = base.resolve()
    target = (base / relative.lstrip("/")).resolve()
    if target != base and base not in target.parents:
        raise ValueError("path escapes workspace")
    return target
