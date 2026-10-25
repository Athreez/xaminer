"""Invitations and password reset through the real HTTP API (PRD AUTH-02, AUTH-05)."""

import re
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth import accounts
from app.auth.models import AuthToken, RefreshToken
from app.db.session import SessionFactory, create_session_factory, system_session
from app.main import create_app
from app.notifications.emails import Email
from app.platform.models import Institution
from app.users.models import User
from cli import commands
from tests.db.api_helpers import PASSWORD, make_settings

NEW_PASSWORD = "copper-kettle-77-river"
BASE = "http://xaminer.test"


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[Email]:
    """Capture emails instead of queueing them."""
    sent: list[Email] = []
    monkeypatch.setattr(accounts, "queue_email", sent.append)
    monkeypatch.setattr(commands, "queue_email", sent.append)
    return sent


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def factory(app_engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    async with system_session(factory) as s:
        ids = select(Institution.id).where(Institution.name.like("Accounts test%"))
        for model in (AuthToken, RefreshToken, User):
            await s.execute(delete(model).where(model.institution_id.in_(ids)))
        await s.execute(delete(Institution).where(Institution.name.like("Accounts test%")))
        await s.commit()


@pytest.fixture
async def college(factory: SessionFactory) -> Institution:
    return await commands.create_institution(factory, f"Accounts test {uuid.uuid4().hex[:8]}")


def unique_email() -> str:
    return f"u{uuid.uuid4().hex[:10]}@abc.edu"  # fresh per test, so rate limits don't collide


def token_from(email: Email) -> str:
    match = re.search(r"#token=([\w-]+)", email.text)
    assert match, email.text
    return match.group(1)


def login(client: TestClient, email: str, password: str):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def invite(factory: SessionFactory, college: Institution, email: str) -> None:
    await commands.invite_user(factory, college.name, email, "Ravi Kumar", "STUDENT", BASE)


# ----------------------------------------------------------------------------- invitations


async def test_invite_activate_then_login(
    client: TestClient, factory: SessionFactory, college: Institution, outbox: list[Email]
) -> None:
    email = unique_email()
    await invite(factory, college, email)
    assert len(outbox) == 1 and outbox[0].to == email
    token = token_from(outbox[0])

    info = client.post("/api/v1/auth/invite/inspect", json={"token": token})
    assert info.json() == {
        "email": email,
        "full_name": "Ravi Kumar",
        "institution_name": college.name,
    }

    assert login(client, email, PASSWORD).status_code == 401  # not active yet
    accepted = client.post(
        "/api/v1/auth/invite/accept", json={"token": token, "password": PASSWORD}
    )
    assert accepted.status_code == 204
    assert login(client, email, PASSWORD).status_code == 200

    again = client.post("/api/v1/auth/invite/accept", json={"token": token, "password": PASSWORD})
    assert again.json()["error"]["code"] == "INVALID_TOKEN"  # single use
    assert client.post("/api/v1/auth/invite/inspect", json={"token": token}).status_code == 400


async def test_weak_password_keeps_the_link_usable(
    client: TestClient, factory: SessionFactory, college: Institution, outbox: list[Email]
) -> None:
    await invite(factory, college, unique_email())
    token = token_from(outbox[0])
    weak = client.post(
        "/api/v1/auth/invite/accept", json={"token": token, "password": "password123"}
    )
    assert weak.status_code == 422
    assert weak.json()["error"]["details"][0]["field"] == "password"
    ok = client.post("/api/v1/auth/invite/accept", json={"token": token, "password": PASSWORD})
    assert ok.status_code == 204


async def test_reinvite_cancels_the_old_link(
    client: TestClient, factory: SessionFactory, college: Institution, outbox: list[Email]
) -> None:
    email = unique_email()
    await invite(factory, college, email)
    await invite(factory, college, email)  # re-send
    old, new = token_from(outbox[0]), token_from(outbox[1])
    assert client.post("/api/v1/auth/invite/inspect", json={"token": old}).status_code == 400
    assert client.post("/api/v1/auth/invite/inspect", json={"token": new}).status_code == 200


async def test_expired_invitation(
    client: TestClient, factory: SessionFactory, college: Institution, outbox: list[Email]
) -> None:
    await invite(factory, college, unique_email())
    async with system_session(factory) as s:
        await s.execute(
            update(AuthToken)
            .where(AuthToken.institution_id == college.id)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await s.commit()
    response = client.post(
        "/api/v1/auth/invite/accept", json={"token": token_from(outbox[0]), "password": PASSWORD}
    )
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_cannot_invite_an_active_user(
    factory: SessionFactory, college: Institution, outbox: list[Email]
) -> None:
    email = unique_email()
    await commands.create_admin(factory, college.name, email, "Asha Rao", PASSWORD)
    with pytest.raises(commands.CommandError, match="already ACTIVE"):
        await invite(factory, college, email)
    assert outbox == []


def test_garbage_token(client: TestClient) -> None:
    response = client.post("/api/v1/auth/invite/inspect", json={"token": "x" * 40})
    assert response.status_code == 400
    assert response.json()["error"] == {
        "code": "INVALID_TOKEN",
        "message": "This link is invalid or has expired.",
        "request_id": response.json()["error"]["request_id"],
    }


# ----------------------------------------------------------------------------- password reset


async def test_reset_flow(
    client: TestClient, factory: SessionFactory, college: Institution, outbox: list[Email]
) -> None:
    email = unique_email()
    await commands.create_admin(factory, college.name, email, "Asha Rao", PASSWORD)
    login(client, email, PASSWORD)  # an existing session that must end

    response = client.post("/api/v1/auth/password-reset/request", json={"email": email.upper()})
    assert response.status_code == 202
    token = token_from(outbox[-1])

    done = client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "password": NEW_PASSWORD}
    )
    assert done.status_code == 204
    assert login(client, email, PASSWORD).status_code == 401
    assert login(client, email, NEW_PASSWORD).status_code == 200

    async with system_session(factory) as s:
        sessions = list(await s.scalars(select(RefreshToken).join(User).where(User.email == email)))
    assert sessions[0].revoked_at is not None  # the session from before the reset was ended
    reuse = client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "password": NEW_PASSWORD}
    )
    assert reuse.json()["error"]["code"] == "INVALID_TOKEN"


async def test_reset_answer_is_the_same_for_unknown_and_invited(
    client: TestClient, factory: SessionFactory, college: Institution, outbox: list[Email]
) -> None:
    invited = unique_email()
    await invite(factory, college, invited)
    outbox.clear()
    answers = [
        client.post("/api/v1/auth/password-reset/request", json={"email": address})
        for address in (unique_email(), invited)
    ]
    assert {r.status_code for r in answers} == {202}
    assert answers[0].json() == answers[1].json()
    assert outbox == []  # no account to reset: nothing sent


async def test_reset_requests_are_rate_limited(
    client: TestClient, factory: SessionFactory, college: Institution, outbox: list[Email]
) -> None:
    email = unique_email()
    await commands.create_admin(factory, college.name, email, "Asha Rao", PASSWORD)
    responses = [
        client.post("/api/v1/auth/password-reset/request", json={"email": email}) for _ in range(5)
    ]
    assert {r.status_code for r in responses} == {202}  # the answer never changes...
    assert len(outbox) == 3  # ...but only 3 emails per hour go out


async def test_new_reset_link_cancels_the_previous_one(
    client: TestClient, factory: SessionFactory, college: Institution, outbox: list[Email]
) -> None:
    email = unique_email()
    await commands.create_admin(factory, college.name, email, "Asha Rao", PASSWORD)
    client.post("/api/v1/auth/password-reset/request", json={"email": email})
    client.post("/api/v1/auth/password-reset/request", json={"email": email})
    first = token_from(outbox[0])
    response = client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": first, "password": NEW_PASSWORD}
    )
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_invite_link_cannot_reset_a_password(
    client: TestClient, factory: SessionFactory, college: Institution, outbox: list[Email]
) -> None:
    await invite(factory, college, unique_email())
    response = client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token_from(outbox[0]), "password": NEW_PASSWORD},
    )
    assert response.json()["error"]["code"] == "INVALID_TOKEN"
