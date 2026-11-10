"""SQLAlchemy engine and session factory."""

import os
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def _discard_inherited_pool() -> None:
    """After fork, never reuse the parent's pooled connections.

    RQ forks a child process per job. Without this, the child reuses the parent's PostgreSQL
    socket, and the second job fails (e.g. psycopg DuplicatePreparedStatement). `close=False`
    leaves the parent's connections alone and gives the child a fresh pool.
    """
    if get_engine.cache_info().currsize:
        get_engine().dispose(close=False)


os.register_at_fork(after_in_child=_discard_inherited_pool)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


BASELINE_REVISION = "0001_initial"
_MIGRATION_LOCK_ID = 727274
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "migrations"))
    return cfg


def _upgrade(conn: Connection) -> None:
    cfg = alembic_config()
    cfg.attributes["connection"] = conn
    tables = set(inspect(conn).get_table_names())
    if "alembic_version" not in tables and "users" in tables:
        # Database created by the pre-Alembic create_all(): adopt it at the baseline revision.
        command.stamp(cfg, BASELINE_REVISION)
    command.upgrade(cfg, "head")


def init_db() -> None:
    """Upgrade the schema to the latest Alembic revision.

    Safe to call concurrently from the API and workers: on PostgreSQL a session-level
    advisory lock serialises the upgrade. Databases created by the old ``create_all`` (tables
    but no ``alembic_version``) are stamped at the baseline revision instead of failing.
    """
    from app import models  # noqa: F401  (register models)

    engine = get_engine()
    with engine.connect() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": _MIGRATION_LOCK_ID})
            conn.commit()
            try:
                _upgrade(conn)
                conn.commit()
            finally:
                conn.rollback()
                conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": _MIGRATION_LOCK_ID})
                conn.commit()
        else:
            _upgrade(conn)
            conn.commit()
