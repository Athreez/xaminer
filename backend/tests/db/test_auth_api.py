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
from app.db.session import SessionFactory, create_session_factory, system_session, tenant_session
from app.main import create_app
from app.platform.models import Institution
from app.users.models import User
from cli import commands
from tests.db.api_helpers import PASSWORD, SECRET, make_settings

LOGIN = "/api/v1/auth/login"
# Login looks across every institution, so this file's addresses must be its own: other files
# running in parallel make users like a@abc.edu too.
DOMAIN = f"auth-{uuid.uuid4().hex[:8]}.edu"


@dataclass
class World:
    college: Institution
    admin: User


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
    admin = await commands.create_admin(factory, college.name, f"a@{DOMAIN}", "Asha Rao", PASSWORD)
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
    response = login(client, f"A@{DOMAIN.upper()}")  # email match is case-insensitive
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60
    assert body["user"] == {
        "id": str(world.admin.id),
        "email": f"a@{DOMAIN}",
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
        response = login(secure_client, f"a@{DOMAIN}")
    assert "Secure" in response.headers["set-cookie"]


async def test_failures_all_look_the_same(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    await add_user(factory, world.college, email=f"invited@{DOMAIN}")  # no password yet
    await add_user(
        factory,
        world.college,
        email=f"gone@{DOMAIN}",
        status="DEACTIVATED",
        password_hash=hash_password(PASSWORD),
    )
    attempts = [
        login(client, f"a@{DOMAIN}", "wrong-password-123"),
        login(client, f"nobody@{DOMAIN}"),
        login(client, f"invited@{DOMAIN}"),
        login(client, f"gone@{DOMAIN}"),
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
    assert error_code(login(client, f"a@{DOMAIN}", "wrong-password-123")) == "INVALID_CREDENTIALS"
    locked = login(client, f"a@{DOMAIN}")
    assert locked.status_code == 401
    assert error_code(locked) == "ACCOUNT_LOCKED"


async def test_same_account_in_two_institutions(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    email = f"both@{DOMAIN}"
    other = await new_college(factory)
    for college in (world.college, other):
        await commands.create_admin(factory, college.name, email, "Asha Rao", PASSWORD)

    ambiguous = login(client, email)
    assert ambiguous.status_code == 409
    assert error_code(ambiguous) == "INSTITUTION_REQUIRED"
    choices = {c["id"] for c in ambiguous.json()["error"]["details"]}
    assert choices == {str(world.college.id), str(other.id)}

    chosen = login(client, email, institution_id=str(other.id))
    assert chosen.status_code == 200
    assert chosen.json()["user"]["institution_id"] == str(other.id)


def test_unknown_fields_rejected(client: TestClient, world: World) -> None:
    response = login(client, f"a@{DOMAIN}", role="ADMIN")
    assert response.status_code == 422


# ----------------------------------------------------------------------------- /me and tokens


def test_me_with_token(client: TestClient, world: World) -> None:
    token = login(client, f"a@{DOMAIN}").json()["access_token"]
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == f"a@{DOMAIN}"


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
    token = login(client, f"a@{DOMAIN}").json()["access_token"]
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
    login(client, f"a@{DOMAIN}")
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
        email=f"b@{DOMAIN}",
        status="ACTIVE",
        password_hash=hash_password(PASSWORD),
    )
    token = login(client, f"a@{DOMAIN}").json()["access_token"]  # e.g. laptop
    login(client, f"a@{DOMAIN}")  # e.g. phone: a second session of the same user
    login(client, f"b@{DOMAIN}")  # someone else
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


# ----------------------------------------------------------------------------- refresh (AUTH-03)

REFRESH = "/api/v1/auth/refresh"


def refresh_with(client: TestClient, raw: str):  # type: ignore[no-untyped-def]
    """Refresh using a specific cookie value (as a copied/stolen cookie would be used)."""
    client.cookies.clear()
    return client.post(REFRESH, headers={"Cookie": f"xaminer_refresh={raw}"})


async def _family(factory: SessionFactory, raw: str) -> list[RefreshToken]:
    async with system_session(factory) as s:
        token = (
            await s.scalars(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw)))
        ).one()
        return list(
            await s.scalars(
                select(RefreshToken)
                .where(RefreshToken.family_id == token.family_id)
                .order_by(RefreshToken.created_at)
            )
        )


async def _age_use(factory: SessionFactory, raw: str, seconds: int) -> None:
    """Pretend the token was rotated `seconds` ago (to step outside the grace window)."""
    async with system_session(factory) as s:
        await s.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(raw))
            .values(used_at=datetime.now(UTC) - timedelta(seconds=seconds))
        )
        await s.commit()


async def test_refresh_rotates_the_token(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    login(client, f"a@{DOMAIN}")
    first = client.cookies["xaminer_refresh"]

    response = client.post(REFRESH)
    assert response.status_code == 200
    second = client.cookies["xaminer_refresh"]
    assert second != first
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
    )
    assert me.json()["email"] == f"a@{DOMAIN}"

    family = await _family(factory, first)
    assert len(family) == 2  # same login, same family
    assert family[0].used_at is not None and family[1].used_at is None


def test_refresh_can_be_repeated_down_the_chain(client: TestClient, world: World) -> None:
    login(client, f"a@{DOMAIN}")
    for _ in range(4):
        assert client.post(REFRESH).status_code == 200


async def test_reuse_of_an_old_token_logs_out_the_whole_family(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    login(client, f"a@{DOMAIN}")
    stolen = client.cookies["xaminer_refresh"]
    client.post(REFRESH)  # the real user refreshes; `stolen` is now used
    current = client.cookies["xaminer_refresh"]
    await _age_use(factory, stolen, seconds=60)  # well past the grace window

    replay = refresh_with(client, stolen)
    assert replay.status_code == 401
    assert error_code(replay) == "TOKEN_REUSE_DETECTED"
    assert 'xaminer_refresh=""' in replay.headers["set-cookie"]  # cookie cleared
    assert all(t.revoked_at is not None for t in await _family(factory, stolen))
    # The real user's newer token is gone too: everyone on that login must sign in again.
    assert error_code(refresh_with(client, current)) == "UNAUTHENTICATED"


async def test_two_tabs_refreshing_at_once_is_not_treated_as_theft(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    login(client, f"a@{DOMAIN}")
    shared = client.cookies["xaminer_refresh"]
    client.post(REFRESH)  # tab 1 wins
    current = client.cookies["xaminer_refresh"]

    late = refresh_with(client, shared)  # tab 2, a moment later, same old cookie
    assert late.status_code == 401
    assert error_code(late) == "TOKEN_ALREADY_ROTATED"
    assert "set-cookie" not in late.headers  # keeps the new cookie tab 1 received
    assert all(t.revoked_at is None for t in await _family(factory, shared))
    assert refresh_with(client, current).status_code == 200  # the retry works


def test_refresh_without_cookie(client: TestClient) -> None:
    response = client.post(REFRESH)
    assert response.status_code == 401
    assert error_code(response) == "UNAUTHENTICATED"


def test_refresh_after_logout(client: TestClient, world: World) -> None:
    login(client, f"a@{DOMAIN}")
    raw = client.cookies["xaminer_refresh"]
    client.post("/api/v1/auth/logout")
    assert error_code(refresh_with(client, raw)) == "UNAUTHENTICATED"


async def test_refresh_with_expired_token(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    login(client, f"a@{DOMAIN}")
    raw = client.cookies["xaminer_refresh"]
    async with system_session(factory) as s:
        await s.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(raw))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await s.commit()
    assert error_code(refresh_with(client, raw)) == "UNAUTHENTICATED"


async def test_refresh_after_deactivation_ends_the_session(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    login(client, f"a@{DOMAIN}")
    raw = client.cookies["xaminer_refresh"]
    async with system_session(factory) as s:
        await s.execute(update(User).where(User.id == world.admin.id).values(status="DEACTIVATED"))
        await s.commit()
    assert error_code(refresh_with(client, raw)) == "UNAUTHENTICATED"
    assert all(t.revoked_at is not None for t in await _family(factory, raw))
