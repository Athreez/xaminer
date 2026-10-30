"""`seed-demo-users` (TCK-1407): Demo College with active accounts sharing one password and a
group of the students; running it again changes nothing."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.passwords import verify_password
from app.db.session import SessionFactory, create_session_factory, tenant_session
from app.users.models import User, UserGroup, UserGroupMember
from cli import commands
from tests.db.question_helpers import purge_institutions

PASSWORD = "violet-tram-42-lantern"


@pytest.fixture
async def factory(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    found = [
        i.id
        for i in await commands.list_institutions(factory)
        if i.name == commands.DEMO_INSTITUTION
    ]
    await purge_institutions(migrator_engine, found)


async def test_demo_accounts_and_group(factory: SessionFactory) -> None:
    first = await commands.seed_demo_users(factory, PASSWORD)
    assert len(first) == 13 and all(created for _, created in first)
    assert all(not created for _, created in await commands.seed_demo_users(factory, PASSWORD))

    college = await commands.find_institution(factory, commands.DEMO_INSTITUTION)
    async with tenant_session(factory, college.id) as s:
        users = list(await s.scalars(select(User)))
        group = await s.scalar(select(UserGroup).where(UserGroup.name == commands.DEMO_GROUP))
        assert group is not None
        members = list(
            await s.scalars(select(UserGroupMember).where(UserGroupMember.group_id == group.id))
        )
    roles = sorted(u.role for u in users)
    assert (
        roles.count("ADMIN") == 1 and roles.count("TEACHER") == 2 and roles.count("STUDENT") == 10
    )
    assert all(
        u.status == "ACTIVE" and verify_password(u.password_hash or "", PASSWORD) for u in users
    )
    assert len(members) == 10


async def test_a_weak_password_is_refused(factory: SessionFactory) -> None:
    with pytest.raises(commands.CommandError):
        await commands.seed_demo_users(factory, "short")
