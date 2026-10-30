"""The live monitor (PRD MON-01; TCK-1201): every assigned student's status, progress, time left,
connection and waiting answers; 200 students answer in under 500 ms."""

import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import ExamAttempt
from app.attempts.monitor import connection_of
from app.db.session import tenant_session
from app.exams.models import Exam, ExamAssignment
from app.main import create_app
from app.users.models import User
from tests.db.api_helpers import make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_start_attempt_api import World, build


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False)
        yield w
    await purge_institutions(migrator_engine, [college.id])


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(make_settings().redis_url.get_secret_value())
    yield client
    await client.aclose()


def monitor(world: World) -> dict:  # type: ignore[type-arg]
    response = world.client.get(f"/api/v1/exams/{world.exam_id}/monitor", headers=world.teacher)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_connection_thresholds() -> None:
    now = datetime.now(UTC)
    assert connection_of(now - timedelta(seconds=20), now) == "ONLINE"
    assert connection_of(now - timedelta(seconds=60), now) == "WEAK"
    assert connection_of(now - timedelta(minutes=5), now) == "OFFLINE"
    assert connection_of(None, now) == "OFFLINE"


async def test_a_student_through_the_exam(world: World) -> None:
    (row,) = monitor(world)["rows"]
    assert (row["status"], row["attempt_id"], row["connection"]) == ("NOT_STARTED", None, None)

    attempt = world.client.post(world.start_url, headers=world.me).json()
    mcq, essay = attempt["questions"][0], attempt["questions"][3]
    world.client.put(
        f"/api/v1/attempts/{attempt['id']}/answers",
        json={
            "answers": [
                {
                    "exam_question_id": mcq["exam_question_id"],
                    "selected_option_ids": [mcq["question"]["options"][0]["id"]],
                    "client_revision": 1,
                },
                {
                    "exam_question_id": essay["exam_question_id"],
                    "text_answer": " ",
                    "client_revision": 1,
                },
            ]
        },
        headers=world.me,
    )
    world.client.post(
        f"/api/v1/attempts/{attempt['id']}/heartbeat", json={"unsynced": 2}, headers=world.me
    )
    live = monitor(world)
    (row,) = live["rows"]
    assert (row["status"], row["answered"], row["total"]) == ("IN_PROGRESS", 1, 4)  # blank: no
    assert (row["connection"], row["unsynced"]) == ("ONLINE", 2)
    assert 3500 <= row["seconds_left"] <= 3600
    assert live["counts"] == {"IN_PROGRESS": 1}

    world.client.post(f"/api/v1/attempts/{attempt['id']}/submit", headers=world.me)
    (row,) = monitor(world)["rows"]
    assert (row["status"], row["connection"], row["seconds_left"]) == ("SUBMITTED", None, None)
    assert (
        world.client.get(f"/api/v1/exams/{world.exam_id}/monitor", headers=world.me).status_code
        == 403
    )  # students: no


async def test_two_hundred_students_in_under_half_a_second(world: World, redis: Redis) -> None:
    now = datetime.now(UTC)
    async with tenant_session(world.factory, world.college.id) as s:
        exam = await s.get_one(Exam, uuid.UUID(world.exam_id))
        version = exam.published_version_id
        students = [
            User(
                email=f"m{i}-{uuid.uuid4().hex[:6]}@abc.edu",
                full_name=f"Student {i:03d}",
                role="STUDENT",
            )
            for i in range(199)
        ]
        s.add_all(students)
        await s.flush()
        for i, u in enumerate(students):
            s.add(ExamAssignment(exam_id=exam.id, student_id=u.id, assigned_by=exam.owner_id))
            if i % 2 == 0:  # half of them have started
                s.add(
                    ExamAttempt(
                        exam_id=exam.id,
                        exam_version_id=version,
                        student_id=u.id,
                        started_at=now,
                        deadline_at=now + timedelta(minutes=60),
                        shuffle_seed=i,
                    )
                )
        await s.commit()
        ids = list(await s.scalars(select(ExamAttempt.id).where(ExamAttempt.exam_id == exam.id)))
    for attempt_id in ids:
        await redis.set(
            f"attempt:{attempt_id}:heartbeat",
            f'{{"at": "{now.isoformat()}", "unsynced": 0}}',
            ex=60,
        )

    monitor(world)  # warm up
    started = time.perf_counter()
    body = monitor(world)
    elapsed = time.perf_counter() - started
    assert len(body["rows"]) == 200 and body["counts"]["IN_PROGRESS"] == 100
    assert elapsed < 0.5, f"{elapsed:.3f} s"
