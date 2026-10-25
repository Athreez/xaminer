from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import SessionFactory, create_session_factory, system_session
from app.platform.models import Institution
from cli import commands


@pytest.fixture
async def factory(app_engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    async with system_session(factory) as s:
        await s.execute(delete(Institution).where(Institution.name.like("CLI test%")))
        await s.commit()


async def test_languages_are_seeded(factory: SessionFactory) -> None:
    languages = {lang.key: lang for lang in await commands.list_languages(factory)}
    assert set(languages) == {"cpp17", "java21", "python312", "node22"}
    assert languages["cpp17"].compile_cmd is not None
    assert languages["python312"].compile_cmd is None
    assert all(lang.enabled for lang in languages.values())


async def test_create_institution_defaults_to_india_time(factory: SessionFactory) -> None:
    created = await commands.create_institution(factory, "  CLI test College  ")
    assert created.name == "CLI test College"
    assert created.timezone == "Asia/Kolkata"
    assert created.status == "ACTIVE"
    assert created.evidence_retention_days == 30
    assert created.id in {i.id for i in await commands.list_institutions(factory)}


async def test_duplicate_name_refused(factory: SessionFactory) -> None:
    await commands.create_institution(factory, "CLI test Dup")
    with pytest.raises(commands.CommandError, match="already exists"):
        await commands.create_institution(factory, "cli TEST dup")


@pytest.mark.parametrize("bad", ["", "   ", "x" * 201])
async def test_bad_name_refused(factory: SessionFactory, bad: str) -> None:
    with pytest.raises(commands.CommandError, match="Name"):
        await commands.create_institution(factory, bad)


async def test_unknown_timezone_refused(factory: SessionFactory) -> None:
    with pytest.raises(commands.CommandError, match="Unknown timezone"):
        await commands.create_institution(factory, "CLI test TZ", "Mars/Olympus")
