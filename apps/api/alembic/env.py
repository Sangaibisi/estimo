"""Alembic async environment. Reads the database URL from ESTIMO_DATABASE_URL."""

from __future__ import annotations

import asyncio
import os

import estimo_connectors.db  # noqa: F401 - registers connector tables on KnowledgeBase
from alembic import context
from estimo_knowledge.db import Base as KnowledgeBase
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import estimo_api.estimates_models  # noqa: F401 - registers workflow tables on ApiBase
from estimo_api.models import Base as ApiBase

config = context.config

database_url = os.environ.get("ESTIMO_DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

target_metadata = [ApiBase.metadata, KnowledgeBase.metadata]


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# Arbitrary but fixed: every Estimo migration runner contends for this one lock id.
_MIGRATION_LOCK_KEY = 0x_E571_E070


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        # Every API replica runs `alembic upgrade head` on start (the bundled Postgres
        # does not exist yet when Helm hooks fire, so migrations live in an init
        # container). Without this, two replicas starting together race on the same
        # DDL. The transaction-scoped advisory lock serialises them — the loser waits,
        # then finds head already applied and no-ops. Released on commit or rollback.
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql(f"SELECT pg_advisory_xact_lock({_MIGRATION_LOCK_KEY})")
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
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
