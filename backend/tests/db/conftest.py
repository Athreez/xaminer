"""Database test setup.

Uses the `<POSTGRES_DB>_test` database of the running Docker stack (`make up`), with the same two
users as production: `migrator` runs migrations, `app` runs the tests' queries.

If Postgres isn't reachable these tests are skipped, unless REQUIRE_DB=1 (CI), where they fail.
"""

import os
import socket
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

BACKEND = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND.parent / "deploy" / ".env"


def _env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    values.update(os.environ)
    return values


ENV = _env()
HOST = ENV.get("TEST_POSTGRES_HOST", "127.0.0.1")
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


def _reachable() -> bool:
    try:
        socket.create_connection((HOST, PORT), timeout=2).close()
        return True
    except OSError:
        return False


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    if not _reachable():
        message = f"Postgres not reachable at {HOST}:{PORT}; start the stack with `make up`."
        if ENV.get("REQUIRE_DB") == "1":
            pytest.fail(message)
        pytest.skip(message)
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["url"] = db_url("migrator").render_as_string(hide_password=False)
    config.attributes["configure_logger"] = False
    command.downgrade(config, "base")  # start clean, whatever a previous run left behind
    command.upgrade(config, "head")
    yield


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
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["url"] = db_url("migrator").render_as_string(hide_password=False)
    config.attributes["configure_logger"] = False
    return config
