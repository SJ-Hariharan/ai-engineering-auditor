"""Alembic environment. The URL comes from app settings; metadata from the ORM models."""

from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401  (register models on Base.metadata)
from app.core.config import get_settings
from app.core.database import Base

config = context.config
target_metadata = Base.metadata

_OPTS = {"target_metadata": target_metadata, "compare_type": True, "render_as_batch": True}


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url, literal_binds=True, dialect_opts={"paramstyle": "named"},
        **_OPTS,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # init_db() passes its own (already locked) connection; the CLI builds one from settings.
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, **_OPTS)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as conn:
            context.configure(connection=conn, **_OPTS)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
