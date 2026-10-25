"""Database test setup.

Uses the `<POSTGRES_DB>_test` database of the running Docker stack (`make up`), with the same two
users as production: `migrator` runs migrations, `app` runs the tests' queries.
Skipped if Postgres isn't reachable (fails instead when REQUIRE_SERVICES=1, as in CI).
"""

from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

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


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    require(PORT, "Postgres")
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
