"""Alembic environment. Connects as the `migrator` database user (SECURITY_AND_ACCESS.md § 5.6).

The URL comes from settings, or from `-x url=...` / config attribute `url` (used by tests).
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL, Connection, make_url, pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.models import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> URL:
    override = config.attributes.get("url") or context.get_x_argument(as_dictionary=True).get("url")
    if override:
        return make_url(override)
    return get_settings().database_url("migrator")


def run_migrations_offline() -> None:
    context.configure(
        url=_url().render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
