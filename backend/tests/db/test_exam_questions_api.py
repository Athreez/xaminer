"""Putting questions into an exam through the real HTTP API (PRD EX-02, ACC-04)."""

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
from app.users.models import User
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

    async def teacher(self, college: Institution | None = None) -> dict[str, str]:
        college = college or self.college
        async with tenant_session(self.factory, college.id) as s:
            user = User(
                email=f"t{uuid.uuid4().hex[:8]}@abc.edu", full_name="Tea Cher", role="TEACHER"
            )
            s.add(user)
            await s.commit()
        token = create_access_token(Principal(user.id, college.id, "TEACHER"), SECRET, 15)
        return {"Authorization": f"Bearer {token}"}

    async def other_college(self) -> Institution:
        college = await commands.create_institution(
            self.factory, f"Exam questions test {uuid.uuid4().hex[:8]}"
        )
        self.ids.append(college.id)
        return college

    async def changes(self) -> list[dict[str, Any] | None]:
        async with tenant_session(self.factory, self.college.id) as s:
            rows = await s.scalars(
                select(AuditLog)
                .where(AuditLog.action == "exam.questions_changed")
                .order_by(AuditLog.id)
            )
            return [row.changes for row in rows]


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(
        factory, f"Exam questions test {uuid.uuid4().hex[:8]}"
    )
    w = World(factory, college, [college.id])
    yield w
    await purge_institutions(migrator_engine, w.ids)


def question(client: TestClient, headers: dict[str, str], points: str = "2", **extra: Any) -> str:
    body = {"type": "DESCRIPTIVE", "body": f"Q {uuid.uuid4().hex[:6]}", "points": points, **extra}
    response = client.post("/api/v1/questions", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]  # type: ignore[no-any-return]


def exam(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post("/api/v1/exams", json={"title": "Quiz"}, headers=headers)
    return response.json()["id"]  # type: ignore[no-any-return]


def put(client: TestClient, headers: dict[str, str], exam_id: str, items: list[dict[str, Any]]):  # type: ignore[no-untyped-def]
    return client.put(
        f"/api/v1/exams/{exam_id}/questions", json={"questions": items}, headers=headers
    )


def order(client: TestClient, headers: dict[str, str], exam_id: str) -> list[str]:
    listed = client.get(f"/api/v1/exams/{exam_id}/questions", headers=headers).json()
    return [q["question_id"] for q in listed["questions"]]


async def test_add_reorder_remove_and_totals(client: TestClient, world: World) -> None:
    me = await world.teacher()
    a, b, c = question(client, me, "2"), question(client, me, "3"), question(client, me, "5")
    e = exam(client, me)

    added = put(client, me, e, [{"question_id": a}, {"question_id": b}, {"question_id": c}])
    assert added.status_code == 200, added.text
    body = added.json()
    assert [q["question_id"] for q in body["questions"]] == [a, b, c]
    assert [q["position"] for q in body["questions"]] == [1, 2, 3]
    assert body["total_points"] == "10.00"

    # Reverse the order and give b its own marks in this exam: one request, applied together.
    moved = put(
        client,
        me,
        e,
        [
            {"question_id": c},
            {"question_id": b, "points": "4", "negative_marks": "1"},
            {"question_id": a},
        ],
    )
    rows = moved.json()["questions"]
    assert [q["question_id"] for q in rows] == [c, b, a]
    assert rows[1]["points"] == "4.00" and rows[1]["question_points"] == "3.00"
    assert rows[1]["points_override"] == "4.00" and rows[1]["negative_marks"] == "1.00"
    assert moved.json()["total_points"] == "11.00"

    removed = put(client, me, e, [{"question_id": a}])
    assert [q["question_id"] for q in removed.json()["questions"]] == [a]
    assert client.get(f"/api/v1/exams/{e}", headers=me).json()["question_count"] == 1
    assert put(client, me, e, []).json()["questions"] == []

    assert [set(c or {}) for c in await world.changes()] == [
        {"added"},
        {"reordered", "marks_changed"},
        {"removed"},
        {"removed"},
    ]


async def test_saving_the_same_list_changes_nothing(client: TestClient, world: World) -> None:
    me = await world.teacher()
    a = question(client, me)
    e = exam(client, me)
    put(client, me, e, [{"question_id": a}])
    put(client, me, e, [{"question_id": a}])
    assert len(await world.changes()) == 1


async def test_which_questions_can_be_used(client: TestClient, world: World) -> None:
    me, colleague = await world.teacher(), await world.teacher()
    outsider = await world.teacher(await world.other_college())
    shared = question(client, colleague, visibility="INSTITUTION")
    private = question(client, colleague)
    foreign = question(client, outsider, visibility="INSTITUTION")
    archived = question(client, me)
    client.post(f"/api/v1/questions/{archived}/archive", headers=me)
    e = exam(client, me)

    assert put(client, me, e, [{"question_id": shared}]).status_code == 200  # ACC-04
    for bad in (private, foreign, archived, str(uuid.uuid4())):
        response = put(client, me, e, [{"question_id": shared}, {"question_id": bad}])
        assert response.status_code == 422, bad
        assert response.json()["error"]["details"][0]["field"] == "questions.1.question_id"
    assert order(client, me, e) == [shared]  # nothing half-saved by the failed requests


async def test_bad_lists(client: TestClient, world: World) -> None:
    me = await world.teacher()
    a = question(client, me, "2")
    e = exam(client, me)
    twice = put(client, me, e, [{"question_id": a}, {"question_id": a}])
    assert twice.status_code == 422 and "already in the exam" in twice.json()["error"]["message"]
    over = put(client, me, e, [{"question_id": a, "negative_marks": "3"}])  # worth only 2
    assert over.status_code == 422
    assert put(client, me, e, [{"question_id": a, "points": "0"}]).status_code == 422


async def test_published_or_archived_exams_are_fixed(client: TestClient, world: World) -> None:
    me = await world.teacher()
    a = question(client, me)
    e = exam(client, me)
    put(client, me, e, [{"question_id": a}])
    async with tenant_session(world.factory, world.college.id) as s:
        await s.execute(update(Exam).where(Exam.id == uuid.UUID(e)).values(status="PUBLISHED"))
        await s.commit()
    response = put(client, me, e, [])
    assert response.status_code == 409 and response.json()["error"]["code"] == "EXAM_PUBLISHED"
    client.post(f"/api/v1/exams/{e}/archive", headers=me)
    assert put(client, me, e, []).json()["error"]["code"] == "EXAM_ARCHIVED"
    assert order(client, me, e) == [a]
