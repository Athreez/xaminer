"""Searching the audit log through the real HTTP API (PRD AUD-03)."""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.models import AuditLog
from app.auth.tokens import Principal, create_access_token
from app.db.session import SessionFactory, create_session_factory, system_session, tenant_session
from app.main import create_app
from app.platform.models import Institution
from app.users.models import User
from cli import commands
from tests.db.api_helpers import SECRET, make_settings

URL = "/api/v1/audit-logs"
DAY = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def factory(app_engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    # Audit rows are append-only for the app user; they stay until the test database is reset.
    async with system_session(factory) as s:
        ids = select(Institution.id).where(Institution.name.like("Audit API test%"))
        await s.execute(delete(User).where(User.institution_id.in_(ids)))
        await s.execute(delete(Institution).where(Institution.name.like("Audit API test%")))
        await s.commit()


async def new_college(factory: SessionFactory) -> Institution:
    return await commands.create_institution(factory, f"Audit API test {uuid.uuid4().hex[:8]}")


async def add_user(factory: SessionFactory, college: Institution, role: str) -> User:
    async with tenant_session(factory, college.id) as s:
        user = User(email=f"u{uuid.uuid4().hex[:8]}@abc.edu", full_name=f"{role} One", role=role)
        s.add(user)
        await s.commit()
        return user


def as_user(user: User) -> dict[str, str]:
    principal = Principal(user.id, user.institution_id, user.role)
    return {"Authorization": f"Bearer {create_access_token(principal, SECRET, 15)}"}


async def log(factory: SessionFactory, college: Institution, **fields: object) -> AuditLog:
    async with tenant_session(factory, college.id) as s:
        row = AuditLog(**fields)
        s.add(row)
        await s.commit()
        return row


def actions(response) -> list[str]:  # type: ignore[no-untyped-def]
    assert response.status_code == 200, response.text
    return [entry["action"] for entry in response.json()["data"]]


async def test_only_admins(client: TestClient, factory: SessionFactory) -> None:
    college = await new_college(factory)
    for role in ("TEACHER", "STUDENT"):
        user = await add_user(factory, college, role)
        assert client.get(URL, headers=as_user(user)).status_code == 403
        assert client.get(f"{URL}/actions", headers=as_user(user)).status_code == 403
    assert client.get(URL).status_code == 401


async def test_search(client: TestClient, factory: SessionFactory) -> None:
    college, other = await new_college(factory), await new_college(factory)
    admin = await add_user(factory, college, "ADMIN")
    teacher = await add_user(factory, college, "TEACHER")
    target = uuid.uuid4()
    await log(factory, college, action="auth.login_failed", created_at=DAY - timedelta(days=2))
    await log(
        factory,
        college,
        action="user.updated",
        actor_id=admin.id,
        actor_role="ADMIN",
        target_type="user",
        target_id=target,
        changes={"role": {"old": "STUDENT", "new": "TEACHER"}},
        created_at=DAY,
    )
    await log(factory, college, action="user.invited", actor_id=admin.id, created_at=DAY)
    await log(factory, college, action="exam.published", actor_id=teacher.id, created_at=DAY)
    await log(factory, other, action="user.updated", created_at=DAY)  # other college: never shown
    headers = as_user(admin)

    everything = client.get(URL, headers=headers)
    assert actions(everything) == [
        "exam.published",
        "user.invited",
        "user.updated",
        "auth.login_failed",
        "institution.created",  # written by create_institution, first of all
    ]  # newest first
    updated = everything.json()["data"][2]
    assert updated["actor"] == {"id": str(admin.id), "full_name": "ADMIN One", "email": admin.email}
    assert updated["changes"] == {"role": {"old": "STUDENT", "new": "TEACHER"}}
    assert everything.json()["data"][3]["actor"] is None  # nobody logged in

    def search(**params: str) -> list[str]:
        return actions(client.get(URL, params=params, headers=headers))

    assert search(actor_id=str(admin.id)) == ["user.invited", "user.updated"]
    assert search(action="user.updated") == ["user.updated"]
    assert search(action="user.") == ["user.invited", "user.updated"]
    assert search(action="user") == []  # no prefix match without the dot
    assert search(target_type="user", target_id=str(target)) == ["user.updated"]
    since = (DAY - timedelta(hours=1)).isoformat()
    until = (DAY + timedelta(hours=1)).isoformat()
    assert search(**{"from": since, "to": until}) == [
        "exam.published",
        "user.invited",
        "user.updated",
    ]
    assert search(to=since) == ["auth.login_failed"]

    bad_range = client.get(URL, params={"from": until, "to": since}, headers=headers)
    assert bad_range.status_code == 422

    names = client.get(f"{URL}/actions", headers=headers).json()
    assert names == [
        "auth.login_failed",
        "exam.published",
        "institution.created",
        "user.invited",
        "user.updated",
    ]


async def test_pages(client: TestClient, factory: SessionFactory) -> None:
    college = await new_college(factory)
    admin = await add_user(factory, college, "ADMIN")
    for i in range(5):
        await log(factory, college, action=f"demo.step_{i}")
    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": "2", **({"cursor": cursor} if cursor else {})}
        page = client.get(URL, params=params, headers=as_user(admin)).json()
        seen += [e["action"] for e in page["data"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == [*(f"demo.step_{i}" for i in reversed(range(5))), "institution.created"]
