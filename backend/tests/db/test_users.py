import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.passwords import verify_password
from app.db.session import SessionFactory, create_session_factory, system_session, tenant_session
from app.platform.models import Institution
from app.users.models import User
from cli import commands

GOOD_PASSWORD = "violet-tram-42-lantern"


@pytest.fixture
async def factory(app_engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    async with system_session(factory) as s:
        ids = select(Institution.id).where(Institution.name.like("Users test%"))
        await s.execute(delete(User).where(User.institution_id.in_(ids)))
        await s.execute(delete(Institution).where(Institution.name.like("Users test%")))
        await s.commit()


@pytest.fixture
async def college(factory: SessionFactory) -> Institution:
    return await commands.create_institution(factory, f"Users test {uuid.uuid4().hex[:6]}")


async def test_create_admin(factory: SessionFactory, college: Institution) -> None:
    admin = await commands.create_admin(
        factory, college.name, "Asha.Rao@ABC.edu", "Asha Rao", GOOD_PASSWORD
    )
    assert admin.institution_id == college.id
    assert (admin.role, admin.status) == ("ADMIN", "ACTIVE")
    assert admin.email == "Asha.Rao@abc.edu"  # domain lower-cased; local part kept
    assert admin.password_hash is not None
    assert verify_password(admin.password_hash, GOOD_PASSWORD)
    assert GOOD_PASSWORD not in admin.password_hash


async def test_institution_by_id_works_too(factory: SessionFactory, college: Institution) -> None:
    admin = await commands.create_admin(
        factory, str(college.id), "a@abc.edu", "Asha Rao", GOOD_PASSWORD
    )
    assert admin.institution_id == college.id


async def test_duplicate_email_any_case_refused(
    factory: SessionFactory, college: Institution
) -> None:
    await commands.create_admin(factory, college.name, "a@abc.edu", "Asha Rao", GOOD_PASSWORD)
    with pytest.raises(commands.CommandError, match="already has an account"):
        await commands.create_admin(factory, college.name, "A@ABC.EDU", "Other", GOOD_PASSWORD)


async def test_same_email_allowed_in_another_institution(
    factory: SessionFactory, college: Institution
) -> None:
    other = await commands.create_institution(factory, f"Users test other {uuid.uuid4().hex[:6]}")
    await commands.create_admin(factory, college.name, "a@abc.edu", "Asha Rao", GOOD_PASSWORD)
    await commands.create_admin(factory, other.name, "a@abc.edu", "Asha Rao", GOOD_PASSWORD)


@pytest.mark.parametrize(
    ("email", "name", "password", "message"),
    [
        ("not-an-email", "Asha Rao", GOOD_PASSWORD, "Invalid email"),
        ("a@abc.edu", "   ", GOOD_PASSWORD, "Name"),
        ("a@abc.edu", "Asha Rao", "password123", "too common"),
        ("a@abc.edu", "Asha Rao", "short", "at least 10"),
    ],
)
async def test_bad_input_refused(
    factory: SessionFactory,
    college: Institution,
    email: str,
    name: str,
    password: str,
    message: str,
) -> None:
    with pytest.raises(commands.CommandError, match=message):
        await commands.create_admin(factory, college.name, email, name, password)


async def test_unknown_institution_refused(factory: SessionFactory) -> None:
    with pytest.raises(commands.CommandError, match="No institution"):
        await commands.create_admin(factory, "Nowhere U", "a@abc.edu", "Asha Rao", GOOD_PASSWORD)


async def test_database_enforces_case_insensitive_unique_email(
    factory: SessionFactory, college: Institution
) -> None:
    async with tenant_session(factory, college.id) as s:
        s.add(User(email="dup@abc.edu", full_name="One", role="STUDENT"))
        s.add(User(email="DUP@abc.edu", full_name="Two", role="STUDENT"))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_active_user_must_have_password(
    factory: SessionFactory, college: Institution
) -> None:
    async with tenant_session(factory, college.id) as s:
        s.add(User(email="np@abc.edu", full_name="No Password", role="STUDENT", status="ACTIVE"))
        with pytest.raises(IntegrityError, match="active_has_password"):
            await s.commit()


async def test_invited_user_needs_no_password(
    factory: SessionFactory, college: Institution
) -> None:
    async with tenant_session(factory, college.id) as s:
        s.add(User(email="inv@abc.edu", full_name="Invited", role="STUDENT"))
        await s.commit()
