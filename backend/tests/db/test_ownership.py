"""get_owned(): load-then-check, 404 for anything that isn't the caller's (SECURITY § 4.1)."""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.tokens import Principal
from app.authz.ownership import get_owned
from app.core.errors import AppError
from app.db.session import SessionFactory, create_session_factory, system_session, tenant_session
from app.platform.models import Institution
from app.users.models import User
from cli import commands


@pytest.fixture
async def factory(app_engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    async with system_session(factory) as s:
        ids = select(Institution.id).where(Institution.name.like("Ownership test%"))
        await s.execute(delete(User).where(User.institution_id.in_(ids)))
        await s.execute(delete(Institution).where(Institution.name.like("Ownership test%")))
        await s.commit()


async def make_user(factory: SessionFactory, institution: Institution) -> User:
    async with tenant_session(factory, institution.id) as s:
        user = User(email=f"{uuid.uuid4().hex[:8]}@x.edu", full_name="Some One", role="STUDENT")
        s.add(user)
        await s.commit()
        return user


@pytest.fixture
async def setup(factory: SessionFactory) -> tuple[Institution, Institution, User]:
    a = await commands.create_institution(factory, f"Ownership test {uuid.uuid4().hex[:8]}")
    b = await commands.create_institution(factory, f"Ownership test {uuid.uuid4().hex[:8]}")
    return a, b, await make_user(factory, a)


def principal(institution: Institution, user_id: uuid.UUID | None = None) -> Principal:
    return Principal(user_id or uuid.uuid4(), institution.id, "TEACHER")


async def expect_404(coro: object) -> None:
    with pytest.raises(AppError) as caught:
        await coro  # type: ignore[misc]
    assert caught.value.status_code == 404
    assert caught.value.code == "NOT_FOUND"


async def test_owner_gets_the_item(
    factory: SessionFactory, setup: tuple[Institution, Institution, User]
) -> None:
    a, _, item = setup
    caller = principal(a, item.id)
    async with tenant_session(factory, a.id) as s:
        found = await get_owned(s, User, item.id, caller, owned=lambda u: u.id == caller.user_id)
    assert found.id == item.id


async def test_someone_else_in_the_same_institution_gets_404(
    factory: SessionFactory, setup: tuple[Institution, Institution, User]
) -> None:
    a, _, item = setup
    caller = principal(a)  # same institution, different person
    async with tenant_session(factory, a.id) as s:
        await expect_404(
            get_owned(s, User, item.id, caller, owned=lambda u: u.id == caller.user_id)
        )


async def test_another_institution_gets_404(
    factory: SessionFactory, setup: tuple[Institution, Institution, User]
) -> None:
    _, b, item = setup
    async with tenant_session(factory, b.id) as s:
        await expect_404(get_owned(s, User, item.id, principal(b)))


async def test_item_already_in_session_memory_is_still_checked(
    factory: SessionFactory, setup: tuple[Institution, Institution, User]
) -> None:
    # A system session loads the item, so session.get() can answer from memory with no query
    # (and no automatic institution filter). The helper must still refuse another institution.
    _, b, item = setup
    async with system_session(factory) as s:
        await s.get(User, item.id)
        await expect_404(get_owned(s, User, item.id, principal(b)))


async def test_missing_id_gets_the_same_404(
    factory: SessionFactory, setup: tuple[Institution, Institution, User]
) -> None:
    a, _, _ = setup
    async with tenant_session(factory, a.id) as s:
        await expect_404(get_owned(s, User, uuid.uuid4(), principal(a)))
