import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_migrations_round_trip(alembic_config: Config, app_engine: AsyncEngine) -> None:
    # Alembic's env.py runs its own event loop, so call it from a worker thread.
    await asyncio.to_thread(command.downgrade, alembic_config, "base")
    await asyncio.to_thread(command.upgrade, alembic_config, "head")
    async with app_engine.connect() as conn:
        version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    assert version is not None


async def test_tables_are_owned_by_migrator(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        owner = (
            await conn.execute(
                text("SELECT tableowner FROM pg_tables WHERE tablename='institution'")
            )
        ).scalar()
    assert owner == "migrator"


async def test_app_user_can_write_rows(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO institution (id, name) VALUES (gen_random_uuid(), 'Role test')")
        )
        await conn.execute(text("DELETE FROM institution WHERE name = 'Role test'"))


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE sneaky (id int)",
        "DROP TABLE institution",
        "ALTER TABLE institution ADD COLUMN sneaky int",
        "TRUNCATE institution",
    ],
)
async def test_app_user_cannot_change_schema(app_engine: AsyncEngine, statement: str) -> None:
    async with app_engine.connect() as conn:
        with pytest.raises(ProgrammingError, match=r"permission denied|must be owner"):
            await conn.execute(text(statement))
