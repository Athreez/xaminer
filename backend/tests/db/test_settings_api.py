"""Institution settings through the real HTTP API (PRD PRC-13)."""

import uuid
from collections.abc import AsyncIterator, Iterator

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

URL = "/api/v1/institution/settings"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def factory(app_engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    async with system_session(factory) as s:
        ids = select(Institution.id).where(Institution.name.like("Settings test%"))
        await s.execute(delete(User).where(User.institution_id.in_(ids)))
        await s.execute(delete(Institution).where(Institution.name.like("Settings test%")))
        await s.commit()


async def new_college(factory: SessionFactory) -> Institution:
    return await commands.create_institution(factory, f"Settings test {uuid.uuid4().hex[:8]}")


async def member(factory: SessionFactory, college: Institution, role: str) -> dict[str, str]:
    async with tenant_session(factory, college.id) as s:
        user = User(email=f"u{uuid.uuid4().hex[:8]}@abc.edu", full_name="Some One", role=role)
        s.add(user)
        await s.commit()
    principal = Principal(user.id, college.id, role)
    return {"Authorization": f"Bearer {create_access_token(principal, SECRET, 15)}"}


async def test_only_admins(client: TestClient, factory: SessionFactory) -> None:
    college = await new_college(factory)
    for role in ("TEACHER", "STUDENT"):
        headers = await member(factory, college, role)
        assert client.get(URL, headers=headers).status_code == 403
        assert client.patch(URL, json={}, headers=headers).status_code == 403
    assert client.get(URL).status_code == 401


async def test_read_and_change(client: TestClient, factory: SessionFactory) -> None:
    college, other = await new_college(factory), await new_college(factory)
    headers = await member(factory, college, "ADMIN")

    current = client.get(URL, headers=headers).json()
    assert current["name"] == college.name
    assert current["evidence_retention_days"] == 30 and current["default_consent_text"] is None

    body = {"evidence_retention_days": 14, "default_consent_text": "  We record your webcam.  "}
    changed = client.patch(URL, json=body, headers=headers)
    assert changed.status_code == 200, changed.text
    assert changed.json()["evidence_retention_days"] == 14
    assert changed.json()["default_consent_text"] == "We record your webcam."

    assert client.patch(URL, json={}, headers=headers).status_code == 200  # nothing: no audit row
    cleared = client.patch(URL, json={"default_consent_text": None}, headers=headers)
    assert cleared.json()["default_consent_text"] is None
    assert cleared.json()["evidence_retention_days"] == 14  # untouched

    async with tenant_session(factory, college.id) as s:
        rows = list(
            await s.scalars(
                select(AuditLog)
                .where(AuditLog.action == "institution.settings_updated")
                .order_by(AuditLog.created_at)
            )
        )
    assert len(rows) == 2
    assert rows[0].changes is not None
    assert rows[0].changes["evidence_retention_days"] == {"old": 30, "new": 14}

    other_headers = await member(factory, other, "ADMIN")
    assert client.get(URL, headers=other_headers).json()["evidence_retention_days"] == 30


@pytest.mark.parametrize(
    "body",
    [
        {"evidence_retention_days": 6},
        {"evidence_retention_days": 91},
        {"default_consent_text": "   "},
        {"default_consent_text": "x" * 5001},
        {"name": "Renamed College"},  # only the platform CLI renames
    ],
    ids=["too-short", "too-long", "blank-text", "huge-text", "name"],
)
async def test_rejects_bad_values(
    client: TestClient, factory: SessionFactory, body: dict[str, object]
) -> None:
    headers = await member(factory, await new_college(factory), "ADMIN")
    assert client.patch(URL, json=body, headers=headers).status_code == 422
