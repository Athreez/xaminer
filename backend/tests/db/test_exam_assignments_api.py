"""Assigning students to exams through the real HTTP API (PRD EX-04)."""

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.models import AuditLog
from app.auth.tokens import Principal, create_access_token
from app.db.session import SessionFactory, create_session_factory, tenant_session
from app.exams.models import Exam
from app.main import create_app
from app.platform.models import Institution
from app.users.models import User, UserGroup, UserGroupMember
from cli import commands
from tests.db.api_helpers import SECRET, make_settings
from tests.db.question_helpers import purge_institutions


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@dataclass
class World:
    factory: SessionFactory
    college: Institution
    ids: list[uuid.UUID]

    async def user(
        self,
        role: str = "STUDENT",
        status: str = "INVITED",
        college: Institution | None = None,
        **f: str,
    ) -> User:
        college = college or self.college
        async with tenant_session(self.factory, college.id) as s:
            user = User(
                email=f"u{uuid.uuid4().hex[:8]}@abc.edu",
                full_name=f.get("full_name", "Stu Dent"),
                role=role,
                status=status,
                roll_no=f.get("roll_no"),
                password_hash="x" if status == "ACTIVE" else None,
            )
            s.add(user)
            await s.commit()
            return user

    async def group(self, *members: User) -> str:
        async with tenant_session(self.factory, self.college.id) as s:
            group = UserGroup(name=f"G {uuid.uuid4().hex[:6]}")
            s.add(group)
            await s.flush()
            s.add_all(UserGroupMember(group_id=group.id, user_id=m.id) for m in members)
            await s.commit()
            return str(group.id)

    async def teacher(self) -> dict[str, str]:
        user = await self.user("TEACHER")
        token = create_access_token(Principal(user.id, self.college.id, "TEACHER"), SECRET, 15)
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(factory, f"Assignments test {uuid.uuid4().hex[:8]}")
    w = World(factory, college, [college.id])
    yield w
    await purge_institutions(migrator_engine, w.ids)


def exam(client: TestClient, headers: dict[str, str]) -> str:
    return client.post("/api/v1/exams", json={"title": "Quiz"}, headers=headers).json()["id"]  # type: ignore[no-any-return]


def assign(client: TestClient, headers: dict[str, str], exam_id: str, **body: Any):  # type: ignore[no-untyped-def]
    return client.post(f"/api/v1/exams/{exam_id}/assignments", json=body, headers=headers)


def assigned(client: TestClient, headers: dict[str, str], exam_id: str) -> list[dict[str, Any]]:
    return client.get(f"/api/v1/exams/{exam_id}/assignments", headers=headers).json()["students"]  # type: ignore[no-any-return]


async def test_assign_a_group_and_single_students(client: TestClient, world: World) -> None:
    me = await world.teacher()
    ravi = await world.user(full_name="Ravi", roll_no="CSE-002")
    asha = await world.user(full_name="Asha", roll_no="CSE-001", status="ACTIVE")
    gone = await world.user(full_name="Gone", status="DEACTIVATED")
    meena = await world.user(full_name="Meena")
    group = await world.group(ravi, asha, gone)
    e = exam(client, me)

    first = assign(client, me, e, group_ids=[group])
    assert first.status_code == 200, first.text
    assert first.json() == {"added": 2, "already_assigned": 0, "skipped_inactive": 1}
    rows = assigned(client, me, e)
    assert [(r["full_name"], r["via_group"] is not None) for r in rows] == [
        ("Asha", True),
        ("Ravi", True),
    ]

    second = assign(client, me, e, group_ids=[group], student_ids=[str(meena.id), str(ravi.id)])
    assert second.json() == {"added": 1, "already_assigned": 2, "skipped_inactive": 1}
    rows = assigned(client, me, e)
    assert [r["full_name"] for r in rows] == ["Asha", "Ravi", "Meena"]  # roll no., then name
    assert next(r for r in rows if r["full_name"] == "Meena")["via_group"] is None
    assert client.get(f"/api/v1/exams/{e}", headers=me).json()["assigned_count"] == 3

    async with tenant_session(world.factory, world.college.id) as s:
        audit = list(
            await s.scalars(select(AuditLog).where(AuditLog.action == "exam.students_assigned"))
        )
    assert [row.changes["added"] for row in audit if row.changes] == [2, 1]


async def test_who_can_be_assigned(client: TestClient, world: World) -> None:
    me = await world.teacher()
    e = exam(client, me)
    teacher = await world.user("TEACHER")
    gone = await world.user(status="DEACTIVATED")
    other = await commands.create_institution(
        world.factory, f"Assignments test {uuid.uuid4().hex[:8]}"
    )
    world.ids.append(other.id)
    outsider = await world.user(college=other)
    for bad in (teacher.id, gone.id, outsider.id, uuid.uuid4()):
        response = assign(client, me, e, student_ids=[str(bad)])
        assert response.status_code == 422, bad
        assert response.json()["error"]["details"][0]["field"] == "student_ids.0"
    assert assign(client, me, e, group_ids=[str(uuid.uuid4())]).status_code == 422
    assert assign(client, me, e).status_code == 422  # nothing chosen
    assert assigned(client, me, e) == []


async def test_unassign(client: TestClient, world: World) -> None:
    me = await world.teacher()
    ravi = await world.user()
    e = exam(client, me)
    assign(client, me, e, student_ids=[str(ravi.id)])
    url = f"/api/v1/exams/{e}/assignments/{ravi.id}"
    assert client.delete(url, headers=me).status_code == 204
    assert client.delete(url, headers=me).status_code == 404
    assert assigned(client, me, e) == []


async def test_published_yes_archived_no(client: TestClient, world: World) -> None:
    me = await world.teacher()
    ravi, asha = await world.user(), await world.user()
    e = exam(client, me)
    async with tenant_session(world.factory, world.college.id) as s:
        await s.execute(update(Exam).where(Exam.id == uuid.UUID(e)).values(status="PUBLISHED"))
        await s.commit()
    assert assign(client, me, e, student_ids=[str(ravi.id)]).json()["added"] == 1  # still allowed
    client.post(f"/api/v1/exams/{e}/archive", headers=me)
    refused = assign(client, me, e, student_ids=[str(asha.id)])
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "EXAM_ARCHIVED"
    assert client.delete(f"/api/v1/exams/{e}/assignments/{ravi.id}", headers=me).status_code == 409


async def test_student_picker(client: TestClient, world: World) -> None:
    me = await world.teacher()
    ravi = await world.user(full_name="Ravi Kumar", roll_no="CSE-042")
    await world.user(full_name="Asha Rao", roll_no="CSE-001")
    await world.user(full_name="Gone", status="DEACTIVATED")
    await world.user("TEACHER", full_name="Not A Student")
    e = exam(client, me)
    assign(client, me, e, student_ids=[str(ravi.id)])

    choices = client.get(f"/api/v1/exams/{e}/student-choices", headers=me).json()
    assert [(c["full_name"], c["assigned"]) for c in choices] == [
        ("Asha Rao", False),
        ("Ravi Kumar", True),
    ]
    assert set(choices[0]) == {"id", "full_name", "email", "roll_no", "assigned"}  # nothing more
    found = client.get(
        f"/api/v1/exams/{e}/student-choices", params={"q": "cse-04"}, headers=me
    ).json()
    assert [c["full_name"] for c in found] == ["Ravi Kumar"]
