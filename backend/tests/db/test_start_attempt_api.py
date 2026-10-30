"""Starting and resuming attempts through the real HTTP API (PRD ATT-01..05, ATT-09)."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts import attempt as attempt_service
from app.attempts.models import AttemptQuestion, ExamAttempt
from app.auth.tokens import Principal, create_access_token
from app.core.storage import Storage
from app.db.session import SessionFactory, create_session_factory, tenant_session
from app.exams.models import Exam, ExamQuestion
from app.main import create_app
from app.platform.models import Institution
from app.users.models import User
from cli import commands
from tests.db.api_helpers import SECRET, make_settings
from tests.db.question_helpers import purge_institutions

RUBRIC = "RUBRIC-SECRET-91c2"


def bearer(user: User, college: Institution) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + create_access_token(Principal(user.id, college.id, user.role), SECRET, 15)
    }


def keys_in(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(keys_in(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(keys_in(v) for v in value))
    return set()


@dataclass
class World:
    client: TestClient
    factory: SessionFactory
    college: Institution
    student: User
    me: dict[str, str]
    teacher: dict[str, str]
    exam_id: str
    question_order: list[str]  # exam_question ids in the teacher's order

    @property
    def start_url(self) -> str:
        return f"/api/v1/student/exams/{self.exam_id}/attempts"

    async def window(self, opens: timedelta, closes: timedelta, **values: Any) -> None:
        now = datetime.now(UTC)
        async with tenant_session(self.factory, self.college.id) as s:
            await s.execute(
                update(Exam)
                .where(Exam.id == uuid.UUID(self.exam_id))
                .values(open_at=now + opens, close_at=now + closes, **values)
            )
            await s.commit()

    async def set_attempt(self, attempt_id: str, **values: Any) -> None:
        async with tenant_session(self.factory, self.college.id) as s:
            await s.execute(
                update(ExamAttempt).where(ExamAttempt.id == uuid.UUID(attempt_id)).values(**values)
            )
            await s.commit()


async def build(
    app_engine: AsyncEngine, client: TestClient, *, shuffle: bool, **settings: Any
) -> tuple[World, Institution]:
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(factory, f"Start test {uuid.uuid4().hex[:8]}")
    async with tenant_session(factory, college.id) as s:
        teacher = User(email=f"t{uuid.uuid4().hex[:8]}@abc.edu", full_name="T", role="TEACHER")
        student = User(email=f"s{uuid.uuid4().hex[:8]}@abc.edu", full_name="S", role="STUDENT")
        s.add_all([teacher, student])
        await s.commit()
    t = bearer(teacher, college)

    def question(body: dict[str, Any]) -> str:
        response = client.post("/api/v1/questions", json=body, headers=t)
        assert response.status_code == 201, response.text
        return response.json()["id"]  # type: ignore[no-any-return]

    opts = lambda *c: [{"label": f"Option {i}", "is_correct": x} for i, x in enumerate(c)]  # noqa: E731
    ids = [
        question(
            {
                "type": "MCQ",
                "body": "Pick one",
                "points": "2",
                "options": opts(True, False, False, False),
            }
        ),
        question(
            {
                "type": "MSQ",
                "body": "Pick some",
                "points": "2",
                "options": opts(True, True, False, False),
            }
        ),
        question(
            {
                "type": "TRUE_FALSE",
                "body": "True?",
                "points": "1",
                "options": [
                    {"label": "True", "is_correct": True},
                    {"label": "False", "is_correct": False},
                ],
            }
        ),
        question({"type": "DESCRIPTIVE", "body": "Explain", "points": "5", "rubric": RUBRIC}),
    ]
    future = datetime.now(UTC) + timedelta(days=3)
    exam = client.post(
        "/api/v1/exams",
        json={
            "title": "Mid-term",
            "open_at": future.isoformat(),
            "close_at": (future + timedelta(hours=3)).isoformat(),
            "duration_min": 60,
            "shuffle_questions": shuffle,
            "shuffle_options": shuffle,
        }
        | settings,
        headers=t,
    ).json()
    url = f"/api/v1/exams/{exam['id']}"
    client.put(f"{url}/questions", json={"questions": [{"question_id": q} for q in ids]}, headers=t)
    client.post(f"{url}/assignments", json={"student_ids": [str(student.id)]}, headers=t)
    assert client.post(f"{url}/publish", headers=t).status_code == 200
    async with tenant_session(factory, college.id) as s:
        eq_order = [
            str(e)
            for e in await s.scalars(
                select(ExamQuestion.id)
                .where(ExamQuestion.exam_id == uuid.UUID(exam["id"]))
                .order_by(ExamQuestion.order_index)
            )
        ]
    w = World(client, factory, college, student, bearer(student, college), t, exam["id"], eq_order)
    await w.window(-timedelta(hours=1), timedelta(hours=2))
    return w, college


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False)
        yield w
    await purge_institutions(migrator_engine, [college.id])


@pytest.fixture
async def shuffled_world(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> AsyncIterator[World]:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=True)
        yield w
    await purge_institutions(migrator_engine, [college.id])


async def test_start_gives_the_whole_exam_without_answers(world: World) -> None:
    before = datetime.now(UTC)
    response = world.client.post(world.start_url, headers=world.me)
    assert response.status_code == 200, response.text
    body = response.json()

    # Leak test: no answer key and no rubric anywhere in the payload.
    assert not keys_in(body) & {"is_correct", "rubric", "options_correct"}
    assert RUBRIC not in response.text and "is_correct" not in response.text

    assert body["title"] == "Mid-term" and body["status"] == "IN_PROGRESS"
    assert body["navigation_mode"] == "FREE" and body["total_points"] == "10.00"
    started = datetime.fromisoformat(body["started_at"])
    assert started >= before - timedelta(seconds=5)
    assert datetime.fromisoformat(body["deadline_at"]) == started + timedelta(minutes=60)
    assert 3590 <= body["seconds_left"] <= 3600
    assert abs(datetime.fromisoformat(body["server_time"]) - datetime.now(UTC)) < timedelta(
        seconds=30
    )

    items = body["questions"]
    assert [i["exam_question_id"] for i in items] == world.question_order  # not shuffled
    assert [i["position"] for i in items] == [1, 2, 3, 4]
    assert [i["question"]["type"] for i in items] == ["MCQ", "MSQ", "TRUE_FALSE", "DESCRIPTIVE"]
    assert [o["label"] for o in items[0]["question"]["options"]] == [
        f"Option {i}" for i in range(4)
    ]
    assert items[1]["question"]["multiple_answers"] is True
    assert all(i["answer"] is None and i["marked_for_review"] is False for i in items)


async def test_start_is_safe_to_repeat_and_resume_matches(world: World) -> None:
    first = world.client.post(world.start_url, headers=world.me).json()
    again = world.client.post(world.start_url, headers=world.me).json()
    assert again["id"] == first["id"] and again["deadline_at"] == first["deadline_at"]
    resumed = world.client.get(f"/api/v1/attempts/{first['id']}", headers=world.me)
    assert resumed.status_code == 200
    assert [q["exam_question_id"] for q in resumed.json()["questions"]] == [
        q["exam_question_id"] for q in first["questions"]
    ]


async def test_two_simultaneous_starts_get_one_attempt(
    world: World, app_engine: AsyncEngine
) -> None:
    factory = create_session_factory(app_engine)
    principal = Principal(world.student.id, world.college.id, "STUDENT")
    storage = Storage(make_settings())

    async def start() -> str:
        async with tenant_session(factory, world.college.id) as s:
            view = await attempt_service.start(s, principal, uuid.UUID(world.exam_id), storage)
            return str(view.id)

    a, b = await asyncio.gather(start(), start())
    assert a == b
    async with tenant_session(factory, world.college.id) as s:
        rows = list(
            await s.scalars(
                select(ExamAttempt.id).where(ExamAttempt.exam_id == uuid.UUID(world.exam_id))
            )
        )
        assert len(rows) == 1
        questions = list(
            await s.scalars(select(AttemptQuestion.id).where(AttemptQuestion.attempt_id == rows[0]))
        )
        assert len(questions) == 4  # the order was written once


async def test_deadline_is_cut_by_the_window(world: World) -> None:
    await world.window(-timedelta(hours=2), timedelta(minutes=20))
    body = world.client.post(world.start_url, headers=world.me).json()
    async with tenant_session(world.factory, world.college.id) as s:
        exam = await s.get(Exam, uuid.UUID(world.exam_id))
        assert exam is not None
        assert datetime.fromisoformat(body["deadline_at"]) == exam.close_at
    assert body["seconds_left"] <= 20 * 60


@pytest.mark.parametrize(
    ("opens", "closes", "code"),
    [
        (timedelta(hours=1), timedelta(hours=4), "EXAM_NOT_OPEN"),
        (-timedelta(hours=4), -timedelta(hours=1), "EXAM_CLOSED"),
        (-timedelta(hours=2), timedelta(minutes=4), "TOO_LATE_TO_START"),
    ],
)
async def test_refused_outside_the_window(
    world: World, opens: timedelta, closes: timedelta, code: str
) -> None:
    await world.window(opens, closes)
    response = world.client.post(world.start_url, headers=world.me)
    assert response.status_code == 409 and response.json()["error"]["code"] == code


async def test_submitted_and_voided(world: World) -> None:
    first = world.client.post(world.start_url, headers=world.me).json()
    await world.set_attempt(first["id"], status="SUBMITTED", submitted_at=datetime.now(UTC))
    refused = world.client.post(world.start_url, headers=world.me)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "ALREADY_SUBMITTED"
    assert world.client.get(f"/api/v1/attempts/{first['id']}", headers=world.me).status_code == 409

    await world.set_attempt(first["id"], status="VOIDED")
    fresh = world.client.post(world.start_url, headers=world.me)
    assert fresh.status_code == 200 and fresh.json()["id"] != first["id"]  # ATT-02: may start again
    assert world.client.get(f"/api/v1/attempts/{first['id']}", headers=world.me).status_code == 404


async def test_not_assigned_or_not_published(world: World) -> None:
    async with tenant_session(world.factory, world.college.id) as s:
        other = User(email=f"o{uuid.uuid4().hex[:8]}@abc.edu", full_name="O", role="STUDENT")
        s.add(other)
        await s.commit()
    assert (
        world.client.post(world.start_url, headers=bearer(other, world.college)).status_code == 404
    )
    await world.window(-timedelta(hours=1), timedelta(hours=2), status="ARCHIVED")
    assert world.client.post(world.start_url, headers=world.me).status_code == 404


async def test_shuffled_order_is_fixed_per_student(shuffled_world: World) -> None:
    w = shuffled_world
    body = w.client.post(w.start_url, headers=w.me).json()
    order = [q["exam_question_id"] for q in body["questions"]]
    assert sorted(order) == sorted(w.question_order)  # same questions, this student's order
    labels = {
        q["exam_question_id"]: [o["label"] for o in q["question"]["options"]]
        for q in body["questions"]
    }
    resumed = w.client.get(f"/api/v1/attempts/{body['id']}", headers=w.me).json()
    assert [q["exam_question_id"] for q in resumed["questions"]] == order  # a reload shows the same
    assert {
        q["exam_question_id"]: [o["label"] for o in q["question"]["options"]]
        for q in resumed["questions"]
    } == labels
    # True/False options are never shuffled.
    tf = next(q for q in body["questions"] if q["question"]["type"] == "TRUE_FALSE")
    assert [o["label"] for o in tf["question"]["options"]] == ["True", "False"]
    assert json.dumps(body).count("is_correct") == 0
