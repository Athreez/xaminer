"""Admin user management through the real HTTP API (PRD USR-01, USR-04)."""

import re
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.models import AuditLog
from app.auth.models import AuthToken, RefreshToken
from app.auth.passwords import hash_password
from app.auth.tokens import Principal, create_access_token
from app.core.errors import AppError
from app.db.session import SessionFactory, create_session_factory, system_session, tenant_session
from app.main import create_app
from app.notifications.emails import Email
from app.platform.models import Institution
from app.users import service as users_service
from app.users.models import User
from app.users.schemas import UpdateUserRequest
from cli import commands
from tests.db.api_helpers import PASSWORD, SECRET, make_settings

USERS = "/api/v1/users"


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[Email]:
    sent: list[Email] = []
    monkeypatch.setattr(users_service, "queue_email", sent.append)
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
        ids = select(Institution.id).where(Institution.name.like("Users API test%"))
        for model in (AuthToken, RefreshToken, User):
            await s.execute(delete(model).where(model.institution_id.in_(ids)))
        await s.execute(delete(Institution).where(Institution.name.like("Users API test%")))
        await s.commit()


@dataclass
class World:
    factory: SessionFactory
    college: Institution
    admin: User
    student: User

    async def add(self, role: str = "STUDENT", status: str = "ACTIVE", **fields: object) -> User:
        async with tenant_session(self.factory, self.college.id) as s:
            user = User(
                email=fields.pop("email", f"u{uuid.uuid4().hex[:10]}@abc.edu"),
                full_name=fields.pop("full_name", "Some One"),
                role=role,
                status=status,
                password_hash=hash_password(PASSWORD) if status != "INVITED" else None,
                **fields,
            )
            s.add(user)
            await s.commit()
            return user

    async def reload(self, user: User) -> User:
        async with tenant_session(self.factory, self.college.id) as s:
            fresh = await s.get(User, user.id)
            assert fresh is not None
            return fresh

    async def audit(self, action: str) -> list[AuditLog]:
        async with tenant_session(self.factory, self.college.id) as s:
            return list(await s.scalars(select(AuditLog).where(AuditLog.action == action)))


@pytest.fixture
async def world(factory: SessionFactory) -> World:
    college = await commands.create_institution(factory, f"Users API test {uuid.uuid4().hex[:8]}")
    w = World(factory, college, admin=None, student=None)  # type: ignore[arg-type]
    w.admin = await w.add("ADMIN")
    w.student = await w.add("STUDENT", full_name="Ravi Kumar", roll_no="CSE-042")
    return w


def as_user(user: User) -> dict[str, str]:
    principal = Principal(user.id, user.institution_id, user.role)
    return {"Authorization": f"Bearer {create_access_token(principal, SECRET, 15)}"}


def error_code(response) -> str:  # type: ignore[no-untyped-def]
    return response.json()["error"]["code"]  # type: ignore[no-any-return]


def logged_in_refresh_cookie(client: TestClient, user: User) -> str:
    response = client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    raw = client.cookies["xaminer_refresh"]
    client.cookies.clear()
    return raw


def refresh_works(client: TestClient, raw: str) -> bool:
    response = client.post("/api/v1/auth/refresh", headers={"Cookie": f"xaminer_refresh={raw}"})
    client.cookies.clear()
    return response.status_code == 200


# ----------------------------------------------------------------------------- access


async def test_only_admins_can_manage_users(client: TestClient, world: World) -> None:
    teacher = await world.add("TEACHER")
    assert client.get(USERS, headers=as_user(teacher)).status_code == 403
    assert client.get(USERS, headers=as_user(world.student)).status_code == 403
    assert client.get(USERS).status_code == 401
    assert client.get(USERS, headers=as_user(world.admin)).status_code == 200


# ----------------------------------------------------------------------------- list


async def test_list_filters_searches_and_pages(client: TestClient, world: World) -> None:
    for i in range(3):
        await world.add("TEACHER", full_name=f"Teacher {i}")
    headers = as_user(world.admin)

    everyone = client.get(USERS, headers=headers).json()
    assert len(everyone["data"]) == 5 and everyone["next_cursor"] is None
    assert "password_hash" not in everyone["data"][0]

    teachers = client.get(USERS, params={"role": "TEACHER"}, headers=headers).json()["data"]
    assert {u["full_name"] for u in teachers} == {"Teacher 0", "Teacher 1", "Teacher 2"}

    for q in ("ravi", "CSE-04", world.student.email.upper()):
        found = client.get(USERS, params={"q": q}, headers=headers).json()["data"]
        assert [u["id"] for u in found] == [str(world.student.id)], q
    assert client.get(USERS, params={"q": "%"}, headers=headers).json()["data"] == []

    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = client.get(USERS, params=params, headers=headers).json()
        seen += [u["id"] for u in page["data"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == [u["id"] for u in everyone["data"]]  # same order, nothing missed or repeated

    assert client.get(USERS, params={"cursor": "!!"}, headers=headers).status_code == 422
    assert client.get(USERS, params={"role": "KING"}, headers=headers).status_code == 422


async def test_list_shows_only_own_institution(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    other = await commands.create_institution(factory, f"Users API test {uuid.uuid4().hex[:8]}")
    async with tenant_session(factory, other.id) as s:
        s.add(User(email="elsewhere@xyz.edu", full_name="Else Where", role="STUDENT"))
        await s.commit()
    emails = [u["email"] for u in client.get(USERS, headers=as_user(world.admin)).json()["data"]]
    assert "elsewhere@xyz.edu" not in emails


# ----------------------------------------------------------------------------- create


async def test_create_invites_the_user(
    client: TestClient, world: World, outbox: list[Email]
) -> None:
    body = {"email": " Asha@ABC.edu ", "full_name": " Asha Rao ", "role": "TEACHER"}
    response = client.post(USERS, json=body, headers=as_user(world.admin))
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["email"] == "Asha@abc.edu"  # domain lower-cased, spaces trimmed
    assert created["full_name"] == "Asha Rao" and created["status"] == "INVITED"
    assert len(outbox) == 1 and outbox[0].to == "Asha@abc.edu"
    assert re.search(r"/activate#token=[\w-]+", outbox[0].text)

    (row,) = await world.audit("user.invited")
    assert row.actor_id == world.admin.id and str(row.target_id) == created["id"]

    again = client.post(USERS, json=body, headers=as_user(world.admin))
    assert again.status_code == 409 and error_code(again) == "EMAIL_TAKEN"
    assert len(outbox) == 1


async def test_create_rejects_bad_input(client: TestClient, world: World) -> None:
    headers = as_user(world.admin)
    bad_email = {"email": "not-an-email", "full_name": "X", "role": "STUDENT"}
    assert client.post(USERS, json=bad_email, headers=headers).status_code == 422
    blank = {"email": "a@abc.edu", "full_name": "   ", "role": "STUDENT"}
    assert client.post(USERS, json=blank, headers=headers).status_code == 422
    extra = {"email": "a@abc.edu", "full_name": "X", "role": "STUDENT", "password": "x"}
    assert client.post(USERS, json=extra, headers=headers).status_code == 422
    taken_roll = {"email": "b@abc.edu", "full_name": "X", "role": "STUDENT", "roll_no": "CSE-042"}
    response = client.post(USERS, json=taken_roll, headers=headers)
    assert response.status_code == 409 and error_code(response) == "ROLL_NO_TAKEN"
    other = await world.add()
    clash = client.patch(f"{USERS}/{other.id}", json={"roll_no": "CSE-042"}, headers=headers)
    assert clash.status_code == 409 and error_code(clash) == "ROLL_NO_TAKEN"


# ----------------------------------------------------------------------------- edit


async def test_rename_keeps_sessions(client: TestClient, world: World) -> None:
    raw = logged_in_refresh_cookie(client, world.student)
    url = f"{USERS}/{world.student.id}"
    response = client.patch(url, json={"full_name": "Ravi K."}, headers=as_user(world.admin))
    assert response.status_code == 200 and response.json()["full_name"] == "Ravi K."
    assert refresh_works(client, raw)
    (row,) = await world.audit("user.updated")
    assert row.changes == {"full_name": {"old": "Ravi Kumar", "new": "Ravi K."}}


@pytest.mark.parametrize(
    "change", [{"role": "TEACHER"}, {"email": "ravi.new@abc.edu"}], ids=["role", "email"]
)
async def test_role_or_email_change_ends_sessions(
    client: TestClient, world: World, change: dict[str, str]
) -> None:
    raw = logged_in_refresh_cookie(client, world.student)
    url = f"{USERS}/{world.student.id}"
    response = client.patch(url, json=change, headers=as_user(world.admin))
    assert response.status_code == 200, response.text
    assert not refresh_works(client, raw)


async def test_edit_rules(client: TestClient, world: World) -> None:
    headers = as_user(world.admin)
    own = client.patch(f"{USERS}/{world.admin.id}", json={"role": "TEACHER"}, headers=headers)
    assert own.status_code == 409 and error_code(own) == "CANNOT_CHANGE_OWN_ROLE"

    other = await world.add("TEACHER")
    url = f"{USERS}/{world.student.id}"
    taken = client.patch(url, json={"email": other.email}, headers=headers)
    assert taken.status_code == 409 and error_code(taken) == "EMAIL_TAKEN"

    cleared = client.patch(url, json={"roll_no": None}, headers=headers)
    assert cleared.status_code == 200 and cleared.json()["roll_no"] is None

    nothing = client.patch(url, json={}, headers=headers)
    assert nothing.status_code == 200
    assert len(await world.audit("user.updated")) == 1  # only the roll number change


async def test_admin_self_protection(client: TestClient, world: World) -> None:
    second = await world.add("ADMIN")
    off = client.post(f"{USERS}/{world.admin.id}/deactivate", headers=as_user(world.admin))
    assert off.status_code == 409 and error_code(off) == "CANNOT_DEACTIVATE_SELF"
    # Another admin can demote or deactivate an admin while one remains.
    demote = client.patch(
        f"{USERS}/{world.admin.id}", json={"role": "TEACHER"}, headers=as_user(second)
    )
    assert demote.status_code == 200


async def test_last_active_admin_cannot_be_removed(world: World) -> None:
    """Two admins removing each other at once: the second one must be refused."""
    second = await world.add("ADMIN")
    actor_a = Principal(world.admin.id, world.college.id, "ADMIN")
    actor_b = Principal(second.id, world.college.id, "ADMIN")
    async with tenant_session(world.factory, world.college.id) as s:
        await users_service.deactivate_user(s, actor_a, second.id)
    async with tenant_session(world.factory, world.college.id) as s:
        with pytest.raises(AppError) as caught:  # B's token is still valid for a few minutes
            await users_service.deactivate_user(s, actor_b, world.admin.id)
    assert caught.value.code == "LAST_ADMIN"
    async with tenant_session(world.factory, world.college.id) as s:
        with pytest.raises(AppError) as caught:
            await users_service.update_user(
                s, actor_b, world.admin.id, UpdateUserRequest(role="TEACHER")
            )
    assert caught.value.code == "LAST_ADMIN"
    assert (await world.reload(world.admin)).status == "ACTIVE"


# ----------------------------------------------------------------------------- status


async def test_deactivate_and_reactivate(client: TestClient, world: World) -> None:
    raw = logged_in_refresh_cookie(client, world.student)
    headers = as_user(world.admin)
    off = client.post(f"{USERS}/{world.student.id}/deactivate", headers=headers)
    assert off.status_code == 200 and off.json()["status"] == "DEACTIVATED"
    assert not refresh_works(client, raw)
    login = client.post(
        "/api/v1/auth/login", json={"email": world.student.email, "password": PASSWORD}
    )
    assert login.status_code == 401
    again = client.post(f"{USERS}/{world.student.id}/deactivate", headers=headers)
    assert again.status_code == 200  # already off: no-op
    assert len(await world.audit("user.deactivated")) == 1

    on = client.post(f"{USERS}/{world.student.id}/reactivate", headers=headers)
    assert on.status_code == 200 and on.json()["status"] == "ACTIVE"
    invited = await world.add(status="INVITED")
    client.post(f"{USERS}/{invited.id}/deactivate", headers=headers)
    back = client.post(f"{USERS}/{invited.id}/reactivate", headers=headers)
    assert back.json()["status"] == "INVITED"  # never set a password
    assert len(await world.audit("user.reactivated")) == 2


# ----------------------------------------------------------------------------- emails, unlock


async def test_resend_invite(client: TestClient, world: World, outbox: list[Email]) -> None:
    headers = as_user(world.admin)
    invited = await world.add(status="INVITED")
    assert client.post(f"{USERS}/{invited.id}/resend-invite", headers=headers).status_code == 200
    assert client.post(f"{USERS}/{invited.id}/resend-invite", headers=headers).status_code == 200
    assert [e.to for e in outbox] == [invited.email, invited.email]
    async with tenant_session(world.factory, world.college.id) as s:
        open_links = await s.scalars(
            select(AuthToken).where(AuthToken.user_id == invited.id, AuthToken.used_at.is_(None))
        )
        assert len(list(open_links)) == 1  # the older link was cancelled

    active = client.post(f"{USERS}/{world.student.id}/resend-invite", headers=headers)
    assert active.status_code == 409 and error_code(active) == "NOT_INVITED"


async def test_send_password_reset(client: TestClient, world: World, outbox: list[Email]) -> None:
    headers = as_user(world.admin)
    response = client.post(f"{USERS}/{world.student.id}/password-reset", headers=headers)
    assert response.status_code == 200
    assert len(outbox) == 1 and "#token=" in outbox[0].text
    assert len(await world.audit("user.password_reset_sent")) == 1

    invited = await world.add(status="INVITED")
    refused = client.post(f"{USERS}/{invited.id}/password-reset", headers=headers)
    assert refused.status_code == 409 and error_code(refused) == "NOT_ACTIVE"


async def test_unlock(client: TestClient, world: World) -> None:
    locked = await world.add(
        locked_until=datetime.now(UTC) + timedelta(minutes=10), failed_logins=5
    )
    headers = as_user(world.admin)
    assert client.get(f"{USERS}/{locked.id}", headers=headers).json()["locked"] is True
    response = client.post(f"{USERS}/{locked.id}/unlock", headers=headers)
    assert response.status_code == 200 and response.json()["locked"] is False
    fresh = await world.reload(locked)
    assert fresh.failed_logins == 0 and fresh.locked_until is None
    login = client.post("/api/v1/auth/login", json={"email": locked.email, "password": PASSWORD})
    assert login.status_code == 200
    assert len(await world.audit("user.unlocked")) == 1
