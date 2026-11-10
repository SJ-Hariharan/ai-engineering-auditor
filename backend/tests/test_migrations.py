"""Alembic migrations: no drift from the models, idempotent startup, legacy databases."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from app.core import database
from app.core.database import BASELINE_REVISION, Base, get_engine


def _version(engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def _diff(engine):
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn, opts={"compare_type": True, "render_as_batch": True}
        )
        return compare_metadata(ctx, Base.metadata)


def test_head_matches_models():
    # conftest already ran init_db() (i.e. upgrade to head) on a fresh SQLite database.
    engine = get_engine()
    assert _version(engine) == BASELINE_REVISION
    assert _diff(engine) == []


def test_init_db_is_idempotent():
    database.init_db()
    database.init_db()
    assert _version(get_engine()) == BASELINE_REVISION


def test_legacy_create_all_database_is_stamped():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)  # what the pre-Alembic init_db() did
    assert "alembic_version" not in inspect(engine).get_table_names()

    database.init_db()

    assert _version(engine) == BASELINE_REVISION
    assert _diff(engine) == []
