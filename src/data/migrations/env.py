"""Alembic environment — wired to async engine + Base metadata."""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Ensure src/ is importable when alembic runs from the project root
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config.settings import settings  # noqa: E402
from src.data.models.postgres import Base  # noqa: E402  — triggers all model imports

config = context.config

# Use DATABASE_URL from settings (overrides sqlalchemy.url from alembic.ini)
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        # Cloud Run starts several instances of a new revision at once and the
        # entrypoint migrates before serving, so without a lock they would race
        # each other through the same DDL. A transaction-level advisory lock
        # serialises them: the first instance migrates, the rest block here and
        # then find there is nothing left to apply. The lock is released
        # automatically when this transaction ends, including on failure.
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})
        context.run_migrations()


# Arbitrary but STABLE 64-bit key — every deploy must pick the same number for
# the lock to mean anything.
_LOCK_KEY = 4_812_003_117_549_001


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        # Cloud Run starts several instances of a new revision at once and the
        # entrypoint migrates before serving, so without a lock they would race
        # each other through the same DDL. A transaction-level advisory lock
        # serialises them: the first instance migrates, the rest block here and
        # then find there is nothing left to apply. The lock is released
        # automatically when this transaction ends, including on failure.
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
