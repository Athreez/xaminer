"""Login, logout and /me through the real HTTP API and the test database (PRD AUTH-01, AUTH-04)."""

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.models import RefreshToken
from app.auth.passwords import hash_password
from app.auth.tokens import Principal, create_access_token, hash_token
from app.core.config import Settings
from app.db.session import SessionFactory, create_session_factory, system_session, tenant_session
from app.main import create_app
from app.platform.models import Institution
from app.users.models import User
from cli import commands
from tests.db.conftest import PORT, TEST_DB
from tests.services import ENV, HOST

PASSWORD = "violet-tram-42-lantern"
SECRET = "test-signing-secret-that-is-long-enough-123"
LOGIN = "/api/v1/auth/login"


@dataclass
class World:
    college: Institution
    admin: User


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "postgres_host": HOST,
        "postgres_port": PORT,
        "postgres_db": TEST_DB,
        "db_app_password": ENV.get("DB_APP_PASSWORD", ""),
        "jwt_secret": SECRET,
        "cookie_secure": False,  # the test client talks plain http
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def factory(app_engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    async with system_session(factory) as s:
        ids = select(Institution.id).where(Institution.name.like("Auth test%"))
        await s.execute(delete(RefreshToken).where(RefreshToken.institution_id.in_(ids)))
        await s.execute(delete(User).where(User.institution_id.in_(ids)))
        await s.execute(delete(Institution).where(Institution.name.like("Auth test%")))
        await s.commit()


async def new_college(factory: SessionFactory) -> Institution:
    return await commands.create_institution(factory, f"Auth test {uuid.uuid4().hex[:8]}")


@pytest.fixture
async def world(factory: SessionFactory) -> World:
    college = await new_college(factory)
    admin = await commands.create_admin(factory, college.name, "a@abc.edu", "Asha Rao", PASSWORD)
    return World(college, admin)


async def add_user(factory: SessionFactory, college: Institution, **fields: object) -> User:
    async with tenant_session(factory, college.id) as s:
        user = User(full_name="Some One", role="STUDENT", **fields)
        s.add(user)
        await s.commit()
        return user


def login(client: TestClient, email: str, password: str = PASSWORD, **extra: object):  # type: ignore[no-untyped-def]
    return client.post(LOGIN, json={"email": email, "password": password, **extra})


def error_code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


# ----------------------------------------------------------------------------- login


async def test_login_success(client: TestClient, world: World, factory: SessionFactory) -> None:
    response = login(client, "A@ABC.edu")  # email match is case-insensitive
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60
    assert body["user"] == {
        "id": str(world.admin.id),
        "email": "a@abc.edu",
        "full_name": "Asha Rao",
        "role": "ADMIN",
        "institution_id": str(world.college.id),
        "institution_name": world.college.name,
    }
    assert "password" not in response.text

    cookie = response.headers["set-cookie"]
    assert "xaminer_refresh=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api/v1/auth" in cookie

    raw = client.cookies["xaminer_refresh"]
    async with system_session(factory) as s:
        stored = (
            await s.scalars(select(RefreshToken).where(RefreshToken.user_id == world.admin.id))
        ).one()
        user = await s.get(User, world.admin.id)
    assert stored.token_hash == hash_token(raw) != raw  # only the hash is stored
    assert user is not None and user.last_login_at is not None


def test_cookie_is_secure_when_configured(world: World) -> None:
    with TestClient(create_app(make_settings(cookie_secure=True))) as secure_client:
        response = login(secure_client, "a@abc.edu")
    assert "Secure" in response.headers["set-cookie"]


async def test_failures_all_look_the_same(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    await add_user(factory, world.college, email="invited@abc.edu")  # no password yet
    await add_user(
        factory,
        world.college,
        email="gone@abc.edu",
        status="DEACTIVATED",
        password_hash=hash_password(PASSWORD),
    )
    attempts = [
        login(client, "a@abc.edu", "wrong-password-123"),
        login(client, "nobody@abc.edu"),
        login(client, "invited@abc.edu"),
        login(client, "gone@abc.edu"),
    ]
    bodies = []
    for response in attempts:
        assert response.status_code == 401
        error = response.json()["error"]
        error.pop("request_id")
        bodies.append(error)
    assert all(
        b == {"code": "INVALID_CREDENTIALS", "message": "Email or password is incorrect."}
        for b in bodies
    )


async def test_locked_account_only_revealed_with_correct_password(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    async with system_session(factory) as s:
        await s.execute(
            update(User)
            .where(User.id == world.admin.id)
            .values(locked_until=datetime.now(UTC) + timedelta(minutes=10))
        )
        await s.commit()
    assert error_code(login(client, "a@abc.edu", "wrong-password-123")) == "INVALID_CREDENTIALS"
    locked = login(client, "a@abc.edu")
    assert locked.status_code == 401
    assert error_code(locked) == "ACCOUNT_LOCKED"


async def test_same_account_in_two_institutions(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    other = await new_college(factory)
    await commands.create_admin(factory, other.name, "a@abc.edu", "Asha Rao", PASSWORD)

    ambiguous = login(client, "a@abc.edu")
    assert ambiguous.status_code == 409
    assert error_code(ambiguous) == "INSTITUTION_REQUIRED"
    choices = {c["id"] for c in ambiguous.json()["error"]["details"]}
    assert choices == {str(world.college.id), str(other.id)}

    chosen = login(client, "a@abc.edu", institution_id=str(other.id))
    assert chosen.status_code == 200
    assert chosen.json()["user"]["institution_id"] == str(other.id)


def test_unknown_fields_rejected(client: TestClient, world: World) -> None:
    response = login(client, "a@abc.edu", role="ADMIN")
    assert response.status_code == 422


# ----------------------------------------------------------------------------- /me and tokens


def test_me_with_token(client: TestClient, world: World) -> None:
    token = login(client, "a@abc.edu").json()["access_token"]
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "a@abc.edu"


def _bad_tokens(world: World) -> list[str]:
    principal = Principal(world.admin.id, world.college.id, "ADMIN")
    expired = create_access_token(principal, SECRET, 15, now=datetime.now(UTC) - timedelta(hours=1))
    other_secret = create_access_token(principal, "another-secret-another-secret-12345", 15)
    unsigned = jwt.encode(
        {
            "sub": str(world.admin.id),
            "inst": str(world.college.id),
            "role": "ADMIN",
            "typ": "access",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        key="",
        algorithm="none",
    )
    return ["garbage", expired, other_secret, unsigned]


def test_me_rejects_missing_and_bad_tokens(client: TestClient, world: World) -> None:
    missing = client.get("/api/v1/auth/me")
    assert missing.status_code == 401
    assert error_code(missing) == "UNAUTHENTICATED"
    for token in _bad_tokens(world):
        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401, token
        assert error_code(response) == "UNAUTHENTICATED"


async def test_me_stops_working_after_deactivation(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    token = login(client, "a@abc.edu").json()["access_token"]
    async with system_session(factory) as s:
        await s.execute(update(User).where(User.id == world.admin.id).values(status="DEACTIVATED"))
        await s.commit()
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


# ----------------------------------------------------------------------------- logout


async def _tokens(factory: SessionFactory, user_id: uuid.UUID) -> list[RefreshToken]:
    async with system_session(factory) as s:
        return list(await s.scalars(select(RefreshToken).where(RefreshToken.user_id == user_id)))


async def test_logout_revokes_this_session(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    login(client, "a@abc.edu")
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert 'xaminer_refresh=""' in response.headers["set-cookie"]  # cookie cleared
    assert all(t.revoked_at is not None for t in await _tokens(factory, world.admin.id))
    assert client.post("/api/v1/auth/logout").status_code == 204  # repeating is harmless


async def test_logout_all_revokes_every_session_of_that_user_only(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    other = await add_user(
        factory,
        world.college,
        email="b@abc.edu",
        status="ACTIVE",
        password_hash=hash_password(PASSWORD),
    )
    token = login(client, "a@abc.edu").json()["access_token"]  # e.g. laptop
    login(client, "a@abc.edu")  # e.g. phone: a second session of the same user
    login(client, "b@abc.edu")  # someone else
    response = client.post("/api/v1/auth/logout-all", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 204
    mine = await _tokens(factory, world.admin.id)
    assert len(mine) == 2 and all(t.revoked_at is not None for t in mine)
    assert all(t.revoked_at is None for t in await _tokens(factory, other.id))


def test_logout_all_needs_login(client: TestClient) -> None:
    assert client.post("/api/v1/auth/logout-all").status_code == 401


# ----------------------------------------------------------------------------- startup


@pytest.mark.parametrize("secret", ["", "too-short", "change-me-to-a-long-random-value"])
def test_refuses_to_start_without_proper_signing_secret(secret: str) -> None:
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        with TestClient(create_app(make_settings(jwt_secret=secret))):
            pass
