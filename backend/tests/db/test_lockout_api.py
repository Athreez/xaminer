"""Account lockout and login rate limiting (PRD AUTH-06, SECURITY_AND_ACCESS.md § 2.1, § 5.3)."""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.models import RefreshToken
from app.auth.service import MAX_FAILED_LOGINS
from app.db.session import SessionFactory, create_session_factory, system_session
from app.main import create_app
from app.platform.models import Institution
from app.users.models import User
from cli import commands
from tests.db.api_helpers import PASSWORD, make_settings

WRONG = "wrong-password-123"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def factory(app_engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    async with system_session(factory) as s:
        ids = select(Institution.id).where(Institution.name.like("Lockout test%"))
        await s.execute(delete(RefreshToken).where(RefreshToken.institution_id.in_(ids)))
        await s.execute(delete(User).where(User.institution_id.in_(ids)))
        await s.execute(delete(Institution).where(Institution.name.like("Lockout test%")))
        await s.commit()


@pytest.fixture
async def college(factory: SessionFactory) -> Institution:
    return await commands.create_institution(factory, f"Lockout test {uuid.uuid4().hex[:8]}")


@pytest.fixture
async def email(factory: SessionFactory, college: Institution) -> str:
    address = f"u{uuid.uuid4().hex[:10]}@abc.edu"
    await commands.create_admin(factory, college.name, address, "Asha Rao", PASSWORD)
    return address


def login(client: TestClient, email: str, password: str):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


async def state(factory: SessionFactory, email: str) -> User:
    async with system_session(factory) as s:
        return (await s.scalars(select(User).where(User.email == email))).one()


async def test_five_wrong_passwords_lock_the_account(
    client: TestClient, factory: SessionFactory, email: str
) -> None:
    for _ in range(MAX_FAILED_LOGINS):
        assert code(login(client, email, WRONG)) == "INVALID_CREDENTIALS"
    user = await state(factory, email)
    assert user.locked_until is not None
    remaining = user.locked_until - datetime.now(UTC)
    assert timedelta(minutes=14) < remaining <= timedelta(minutes=15)

    # Even the right password is refused now, and only the right password learns why.
    assert code(login(client, email, PASSWORD)) == "ACCOUNT_LOCKED"
    assert code(login(client, email, WRONG)) == "INVALID_CREDENTIALS"


async def test_success_before_the_limit_resets_the_count(
    client: TestClient, factory: SessionFactory, email: str
) -> None:
    for _ in range(MAX_FAILED_LOGINS - 1):
        login(client, email, WRONG)
    assert (await state(factory, email)).failed_logins == MAX_FAILED_LOGINS - 1
    assert login(client, email, PASSWORD).status_code == 200
    assert (await state(factory, email)).failed_logins == 0


async def test_wrong_guesses_while_locked_dont_extend_the_lock(
    client: TestClient, factory: SessionFactory, email: str
) -> None:
    for _ in range(MAX_FAILED_LOGINS):
        login(client, email, WRONG)
    locked_until = (await state(factory, email)).locked_until
    for _ in range(3):
        login(client, email, WRONG)
    assert (await state(factory, email)).locked_until == locked_until


async def test_lock_ends_after_its_time(
    client: TestClient, factory: SessionFactory, email: str
) -> None:
    for _ in range(MAX_FAILED_LOGINS):
        login(client, email, WRONG)
    async with system_session(factory) as s:
        await s.execute(
            update(User)
            .where(User.email == email)
            .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    assert login(client, email, PASSWORD).status_code == 200
    # The count restarted when it locked, so one later typo doesn't lock it again straight away.
    assert code(login(client, email, WRONG)) == "INVALID_CREDENTIALS"
    assert (await state(factory, email)).locked_until is None


async def test_matching_one_institution_does_not_count_against_the_other(
    client: TestClient, factory: SessionFactory, college: Institution, email: str
) -> None:
    other = await commands.create_institution(factory, f"Lockout test {uuid.uuid4().hex[:8]}")
    await commands.create_admin(factory, other.name, email, "Asha Rao", "different-pass-99-zebra")
    for _ in range(MAX_FAILED_LOGINS + 1):
        assert login(client, email, PASSWORD).status_code == 200  # matches the first college only
    async with system_session(factory) as s:
        twin = (
            await s.scalars(
                select(User).where(User.email == email, User.institution_id == other.id)
            )
        ).one()
    assert twin.failed_logins == 0 and twin.locked_until is None


@pytest.fixture
async def strict_client() -> AsyncIterator[TestClient]:
    settings = make_settings(login_rate_per_minute=3)
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    await redis.delete("ratelimit:login-ip:testclient")
    with TestClient(create_app(settings)) as test_client:
        yield test_client
    await redis.delete("ratelimit:login-ip:testclient")
    await redis.aclose()


def test_login_rate_limit_per_ip(strict_client: TestClient) -> None:
    for _ in range(3):
        assert login(strict_client, "nobody@abc.edu", WRONG).status_code == 401
    blocked = login(strict_client, "nobody@abc.edu", WRONG)
    assert blocked.status_code == 429
    assert code(blocked) == "RATE_LIMITED"
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60
