"""The audit log (PRD AUD-01/02, SECURITY_AND_ACCESS.md § 5.6, § 10)."""

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.models import AuditLog
from app.audit.service import diff, record
from app.auth.models import AuthToken, RefreshToken
from app.auth.service import MAX_FAILED_LOGINS
from app.db.session import SessionFactory, create_session_factory, system_session, tenant_session
from app.main import create_app
from app.notifications.emails import Email
from app.platform.models import Institution
from app.users.models import User
from cli import commands
from tests.db.api_helpers import PASSWORD, make_settings


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def factory(app_engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    # Audit rows can't be deleted by the app user (that's the point); they stay until the next
    # test run resets the test database. Everything else is cleaned up as usual.
    async with system_session(factory) as s:
        ids = select(Institution.id).where(Institution.name.like("Audit test%"))
        for model in (AuthToken, RefreshToken, User):
            await s.execute(delete(model).where(model.institution_id.in_(ids)))
        await s.execute(delete(Institution).where(Institution.name.like("Audit test%")))
        await s.commit()


@pytest.fixture
async def college(factory: SessionFactory) -> Institution:
    return await commands.create_institution(factory, f"Audit test {uuid.uuid4().hex[:8]}")


async def entries(factory: SessionFactory, institution: Institution) -> list[AuditLog]:
    async with tenant_session(factory, institution.id) as s:
        return list(await s.scalars(select(AuditLog).order_by(AuditLog.created_at, AuditLog.id)))


def actions(rows: list[AuditLog]) -> list[str]:
    return [row.action for row in rows]


# ----------------------------------------------------------------------------- append-only


async def test_app_user_can_add_and_read_entries(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_log (id, institution_id, action) "
                "VALUES (gen_random_uuid(), gen_random_uuid(), 'test.insert')"
            )
        )
        assert (await conn.execute(text("SELECT count(*) FROM audit_log"))).scalar()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET action = 'tampered'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ],
)
async def test_app_user_cannot_change_or_remove_entries(
    app_engine: AsyncEngine, statement: str
) -> None:
    async with app_engine.connect() as conn:
        with pytest.raises(ProgrammingError, match="permission denied"):
            await conn.execute(text(statement))


async def test_entry_is_saved_only_with_its_change(
    factory: SessionFactory, college: Institution
) -> None:
    async with tenant_session(factory, college.id) as s:
        record(s, "test.should_vanish", institution_id=college.id)
        s.add(User(email="dup@x.edu", full_name="One", role="STUDENT"))
        s.add(User(email="dup@x.edu", full_name="Two", role="STUDENT"))  # breaks the commit
        with pytest.raises(IntegrityError):
            await s.commit()
    assert "test.should_vanish" not in actions(await entries(factory, college))


async def test_entries_are_filtered_by_institution(
    factory: SessionFactory, college: Institution
) -> None:
    other = await commands.create_institution(factory, f"Audit test {uuid.uuid4().hex[:8]}")
    mine = await entries(factory, college)
    assert mine and all(row.institution_id == college.id for row in mine)
    assert not {row.id for row in mine} & {row.id for row in await entries(factory, other)}


# ----------------------------------------------------------------------------- what is stored


def test_diff_keeps_changed_fields_only_and_never_secrets() -> None:
    old = {"role": "STUDENT", "status": "ACTIVE", "password_hash": "old-hash"}
    new = {"role": "TEACHER", "status": "ACTIVE", "password_hash": "new-hash"}
    assert diff(old, new) == {"role": {"old": "STUDENT", "new": "TEACHER"}}


async def test_record_drops_secret_fields(factory: SessionFactory, college: Institution) -> None:
    async with tenant_session(factory, college.id) as s:
        record(
            s,
            "test.secrets",
            institution_id=college.id,
            changes={"password": "x", "token": "y", "name": {"old": "a", "new": "b"}},
        )
        await s.commit()
    row = next(r for r in await entries(factory, college) if r.action == "test.secrets")
    assert row.changes == {"name": {"old": "a", "new": "b"}}


# ----------------------------------------------------------------------------- flows write entries


async def test_platform_commands_are_recorded(
    factory: SessionFactory, college: Institution, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[Email] = []
    monkeypatch.setattr(commands, "queue_email", sent.append)
    await commands.create_admin(factory, college.name, "a@x.edu", "Asha Rao", PASSWORD)
    await commands.invite_user(factory, college.name, "s@x.edu", "Ravi K", "STUDENT", "http://x")
    await commands.invite_user(factory, college.name, "s@x.edu", "Ravi K", "STUDENT", "http://x")
    rows = await entries(factory, college)
    assert actions(rows) == [
        "institution.created",
        "user.created",
        "user.invited",
        "user.invitation_resent",
    ]
    assert {row.actor_role for row in rows} == {"PLATFORM"}
    assert rows[1].changes == {
        "role": {"old": None, "new": "ADMIN"},
        "status": {"old": None, "new": "ACTIVE"},
    }


async def test_login_lockout_and_logout_are_recorded(
    client: TestClient, factory: SessionFactory, college: Institution
) -> None:
    admin = await commands.create_admin(factory, college.name, "a@x.edu", "Asha Rao", PASSWORD)
    login = {"email": "a@x.edu", "password": PASSWORD}

    token = client.post("/api/v1/auth/login", json=login, headers={"X-Request-ID": "req-1"}).json()[
        "access_token"
    ]
    client.post("/api/v1/auth/logout-all", headers={"Authorization": f"Bearer {token}"})
    for _ in range(MAX_FAILED_LOGINS):
        client.post("/api/v1/auth/login", json={**login, "password": "wrong-password-123"})

    rows = await entries(factory, college)
    assert actions(rows)[:2] == ["institution.created", "user.created"]
    assert actions(rows)[2:] == [
        "auth.login",
        "auth.logout_all",
        *["auth.login_failed"] * (MAX_FAILED_LOGINS - 1),
        "auth.account_locked",
    ]
    login_row = rows[2]
    assert login_row.actor_id == admin.id
    assert login_row.actor_role == "ADMIN"
    assert login_row.target_id == admin.id
    assert login_row.request_id == "req-1"
    assert login_row.ip == "testclient" and login_row.user_agent == "testclient"
    assert rows[-1].actor_id is None  # nobody is logged in when a guess fails
    assert rows[-1].target_id == admin.id
