"""Student groups through the real HTTP API (PRD USR-02)."""

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.models import AuditLog
from app.auth.tokens import Principal, create_access_token
from app.db.session import SessionFactory, create_session_factory, system_session, tenant_session
from app.main import create_app
from app.platform.models import Institution
from app.users.models import User, UserGroup, UserGroupMember
from cli import commands
from tests.db.api_helpers import SECRET, make_settings

GROUPS = "/api/v1/groups"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def factory(app_engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    factory = create_session_factory(app_engine)
    yield factory
    async with system_session(factory) as s:
        ids = select(Institution.id).where(Institution.name.like("Groups test%"))
        for model in (UserGroupMember, UserGroup, User):
            await s.execute(delete(model).where(model.institution_id.in_(ids)))
        await s.execute(delete(Institution).where(Institution.name.like("Groups test%")))
        await s.commit()


@dataclass
class World:
    factory: SessionFactory
    college: Institution

    async def add(self, role: str = "STUDENT", status: str = "INVITED", **fields: object) -> User:
        async with tenant_session(self.factory, self.college.id) as s:
            user = User(
                email=f"u{uuid.uuid4().hex[:10]}@abc.edu",
                full_name=fields.pop("full_name", "Some One"),
                role=role,
                status=status,
                password_hash="x" if status == "ACTIVE" else None,
                **fields,
            )
            s.add(user)
            await s.commit()
            return user

    async def audit(self, action: str) -> list[AuditLog]:
        async with tenant_session(self.factory, self.college.id) as s:
            return list(await s.scalars(select(AuditLog).where(AuditLog.action == action)))


@pytest.fixture
async def world(factory: SessionFactory) -> World:
    college = await commands.create_institution(factory, f"Groups test {uuid.uuid4().hex[:8]}")
    return World(factory, college)


def as_user(user: User) -> dict[str, str]:
    principal = Principal(user.id, user.institution_id, user.role)
    return {"Authorization": f"Bearer {create_access_token(principal, SECRET, 15)}"}


def error_code(response) -> str:  # type: ignore[no-untyped-def]
    return response.json()["error"]["code"]  # type: ignore[no-any-return]


async def test_who_can_do_what(client: TestClient, world: World) -> None:
    admin, teacher, student = (
        await world.add("ADMIN"),
        await world.add("TEACHER"),
        await world.add(),
    )
    created = client.post(GROUPS, json={"name": "CSE-A"}, headers=as_user(admin))
    assert created.status_code == 201
    group_id = created.json()["id"]

    assert client.get(GROUPS, headers=as_user(teacher)).status_code == 200
    assert client.get(f"{GROUPS}/{group_id}", headers=as_user(teacher)).status_code == 200
    assert client.post(GROUPS, json={"name": "X"}, headers=as_user(teacher)).status_code == 403
    assert client.delete(f"{GROUPS}/{group_id}", headers=as_user(teacher)).status_code == 403
    assert client.get(GROUPS, headers=as_user(student)).status_code == 403


async def test_group_lifecycle(client: TestClient, world: World) -> None:
    admin = await world.add("ADMIN")
    headers = as_user(admin)
    ravi = await world.add(full_name="Ravi", roll_no="CSE-002")
    asha = await world.add(full_name="Asha", roll_no="CSE-001", status="ACTIVE")

    group = client.post(GROUPS, json={"name": "  CSE-A 2026 "}, headers=headers).json()
    assert group["name"] == "CSE-A 2026" and group["members"] == []
    url = f"{GROUPS}/{group['id']}"

    body = {"user_ids": [str(ravi.id), str(asha.id), str(ravi.id)]}
    added = client.post(f"{url}/members", json=body, headers=headers)
    assert added.status_code == 200, added.text
    assert [m["full_name"] for m in added.json()["members"]] == ["Asha", "Ravi"]  # by roll no

    again = client.post(f"{url}/members", json={"user_ids": [str(ravi.id)]}, headers=headers)
    assert again.json()["member_count"] == 2  # already in: skipped
    assert len(await world.audit("group.members_added")) == 1

    listed = client.get(GROUPS, headers=headers).json()
    assert [(g["name"], g["member_count"]) for g in listed] == [("CSE-A 2026", 2)]
    assert client.get(GROUPS, params={"q": "cse-a"}, headers=headers).json()[0]["id"] == group["id"]
    assert client.get(GROUPS, params={"q": "%"}, headers=headers).json() == []

    assert client.delete(f"{url}/members/{ravi.id}", headers=headers).status_code == 204
    assert client.delete(f"{url}/members/{ravi.id}", headers=headers).status_code == 404
    assert client.get(url, headers=headers).json()["member_count"] == 1

    renamed = client.patch(url, json={"name": "CSE-A"}, headers=headers)
    assert renamed.status_code == 200 and renamed.json()["name"] == "CSE-A"

    assert client.delete(url, headers=headers).status_code == 204
    assert client.get(url, headers=headers).status_code == 404
    async with tenant_session(world.factory, world.college.id) as s:
        assert await s.get(User, asha.id) is not None  # students are untouched
    for action in ("group.created", "group.renamed", "group.member_removed", "group.deleted"):
        assert len(await world.audit(action)) == 1, action


async def test_names_are_unique_ignoring_case(client: TestClient, world: World) -> None:
    headers = as_user(await world.add("ADMIN"))
    assert client.post(GROUPS, json={"name": "CSE-A"}, headers=headers).status_code == 201
    taken = client.post(GROUPS, json={"name": "cse-a"}, headers=headers)
    assert taken.status_code == 409 and error_code(taken) == "GROUP_NAME_TAKEN"
    other = client.post(GROUPS, json={"name": "CSE-B"}, headers=headers).json()
    clash = client.patch(f"{GROUPS}/{other['id']}", json={"name": "CSE-A"}, headers=headers)
    assert clash.status_code == 409
    assert client.post(GROUPS, json={"name": "  "}, headers=headers).status_code == 422


async def test_only_eligible_students_can_be_added(
    client: TestClient, world: World, factory: SessionFactory
) -> None:
    admin = await world.add("ADMIN")
    headers = as_user(admin)
    group = client.post(GROUPS, json={"name": "G"}, headers=headers).json()
    ok = await world.add()
    teacher = await world.add("TEACHER")
    gone = await world.add(status="DEACTIVATED")
    other_college = await commands.create_institution(
        factory, f"Groups test {uuid.uuid4().hex[:8]}"
    )
    async with tenant_session(factory, other_college.id) as s:
        outsider = User(email="o@xyz.edu", full_name="Out Sider", role="STUDENT")
        s.add(outsider)
        await s.commit()

    for bad in (teacher, gone, outsider):
        body = {"user_ids": [str(ok.id), str(bad.id)]}
        response = client.post(f"{GROUPS}/{group['id']}/members", json=body, headers=headers)
        assert response.status_code == 422 and error_code(response) == "INVALID_MEMBERS"
        assert str(bad.id) in response.json()["error"]["details"][0]["message"]
    after = client.get(f"{GROUPS}/{group['id']}", headers=headers).json()
    assert after["members"] == []  # all or nothing
