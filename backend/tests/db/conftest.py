"""Database test setup.

Uses the `<POSTGRES_DB>_test` database of the running Docker stack (`make up`), with the same two
users as production: `migrator` runs migrations, `app` runs the tests' queries.
Skipped if Postgres isn't reachable (fails instead when REQUIRE_SERVICES=1, as in CI).
"""

import asyncio
import os
import tempfile
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from tests.services import BACKEND, ENV, HOST, require

PORT = int(ENV.get("TEST_POSTGRES_PORT", ENV.get("POSTGRES_HOST_PORT", "15432")))
TEST_DB = ENV.get("TEST_POSTGRES_DB", ENV.get("POSTGRES_DB", "xaminer") + "_test")


def db_url(role: str) -> URL:
    password = ENV.get("DB_MIGRATOR_PASSWORD" if role == "migrator" else "DB_APP_PASSWORD", "")
    return URL.create(
        "postgresql+asyncpg",
        username=role,
        password=password,
        host=HOST,
        port=PORT,
        database=TEST_DB,
    )


# Tables some tests add for themselves; they would block dropping the real schema.
TEST_TABLES = ("test_tenant_note",)


async def drop_test_tables(conn: AsyncConnection) -> None:
    for table in TEST_TABLES:
        await conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
    await conn.commit()


def migrator_config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["url"] = db_url("migrator").render_as_string(hide_password=False)
    config.attributes["configure_logger"] = False
    return config


async def migrate_once() -> None:
    """Rebuild the schema from scratch, once per run even when workers run in parallel.

    Workers queue on a Postgres lock; the first one migrates and leaves a marker named after the
    run, so the others go straight on.
    """
    run = os.environ.get("PYTEST_XDIST_TESTRUNUID")
    marker = Path(tempfile.gettempdir()) / f"xaminer-migrated-{run}" if run else None
    engine = create_async_engine(db_url("migrator"))
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT pg_advisory_lock(4242)"))
            if marker is None or not marker.exists():
                await drop_test_tables(conn)
                config = migrator_config()
                # Alembic's env.py runs its own event loop, so call it from a worker thread.
                await asyncio.to_thread(command.downgrade, config, "base")  # start clean
                await asyncio.to_thread(command.upgrade, config, "head")
                if marker is not None:
                    marker.touch()
            await conn.execute(text("SELECT pg_advisory_unlock(4242)"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    require(PORT, "Postgres")
    asyncio.run(migrate_once())
    yield
    asyncio.run(purge_at_end())


async def purge_at_end() -> None:
    from tests.db.question_helpers import purge_queued  # imports the app's models

    engine = create_async_engine(db_url("migrator"))
    try:
        await purge_queued(engine)
    finally:
        await engine.dispose()


@pytest.fixture
async def app_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_url("app"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def migrator_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_url("migrator"))
    yield engine
    await engine.dispose()


@pytest.fixture
def alembic_config() -> Config:
    return migrator_config()


@pytest.fixture(autouse=True)
def no_bundle_jobs(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Test bundle builds are queued for app-worker; tests record them instead of sending."""
    from app.questions import bundles

    queued: list[uuid.UUID] = []
    monkeypatch.setattr(bundles, "queue_build", queued.append)
    return queued
