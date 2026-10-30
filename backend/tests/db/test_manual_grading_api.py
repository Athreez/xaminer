"""Marking descriptive answers (PRD GRD-03; TCK-0904): the queue is anonymous by default, a mark
outside 0 to points is refused, each mark is audited and moves the grading status on."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import ExamAttempt
from app.audit.models import AuditLog
from app.db.session import system_session
from app.grading.objective import grade
from app.main import create_app
from tests.db.api_helpers import make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_start_attempt_api import World, build


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False)
        yield w
    await purge_institutions(migrator_engine, [college.id])


async def ended_attempt(world: World, essay: str) -> dict[str, Any]:
    attempt = world.client.post(world.start_url, headers=world.me).json()
    question = attempt["questions"][3]["exam_question_id"]
    world.client.put(
        f"/api/v1/attempts/{attempt['id']}/answers",
        json={
            "answers": [{"exam_question_id": question, "text_answer": essay, "client_revision": 1}]
        },
        headers=world.me,
    )
    assert world.client.post(
        f"/api/v1/attempts/{attempt['id']}/submit", headers=world.me
    ).is_success
    await grade(world.factory, uuid.UUID(attempt["id"]))
    return {"id": attempt["id"], "question": question}


def mark(world: World, attempt: dict[str, Any], body: dict[str, Any], headers=None):  # type: ignore[no-untyped-def]
    return world.client.put(
        f"/api/v1/attempts/{attempt['id']}/answers/{attempt['question']}/mark",
        json=body,
        headers=headers or world.teacher,
    )


async def test_queue_is_anonymous_and_marking_completes_grading(world: World) -> None:
    attempt = await ended_attempt(world, "Recursion needs a base case.")
    url = f"/api/v1/exams/{world.exam_id}/grading"

    queue = world.client.get(url, headers=world.teacher).json()
    (question,) = queue["questions"]
    assert (question["points"], question["marked"], queue["total"]) == ("5.00", 0, 1)
    (answer,) = question["answers"]
    assert answer["student_label"] == "Student 1"
    assert answer["student_name"] is None  # hidden unless asked
    assert answer["text_answer"] == "Recursion needs a base case."
    named = world.client.get(url, params={"show_names": True}, headers=world.teacher).json()
    assert named["questions"][0]["answers"][0]["student_name"] == "S"

    done = mark(world, attempt, {"score": "4.5", "feedback": "Good, name the stack too."})
    assert done.status_code == 200, done.text
    assert (done.json()["score"], done.json()["grading_status"]) == ("4.50", "COMPLETE")
    again = world.client.get(url, headers=world.teacher).json()
    assert (again["marked"], again["questions"][0]["answers"][0]["score"]) == (1, "4.50")

    remark = mark(world, attempt, {"score": "3"})
    assert remark.status_code == 200, remark.text
    async with system_session(world.factory) as s:
        logs = list(
            await s.scalars(
                select(AuditLog)
                .where(
                    AuditLog.action == "answer.marked",
                    AuditLog.target_id == uuid.UUID(attempt["id"]),
                )
                .order_by(AuditLog.created_at)
            )
        )
        attempt_row = await s.get_one(ExamAttempt, uuid.UUID(attempt["id"]))
    assert [log.changes["score"] for log in logs] == [
        {"old": None, "new": "4.50"},
        {"old": "4.50", "new": "3.00"},
    ]
    assert attempt_row.grading_status == "COMPLETE"


async def test_marks_outside_the_range_are_refused(world: World) -> None:
    attempt = await ended_attempt(world, "Some answer")
    for score in ("5.01", "-1", "2.555"):
        response = mark(world, attempt, {"score": score})
        assert response.status_code == 422, (score, response.text)
    assert mark(world, attempt, {"score": "5"}).status_code == 200  # the full points are fine


async def test_only_the_owner_marks_and_only_written_answers(world: World) -> None:
    attempt = await ended_attempt(world, "   ")  # blank: scored 0 automatically
    assert mark(world, attempt, {"score": "1"}).status_code == 409
    assert (
        world.client.get(f"/api/v1/exams/{world.exam_id}/grading", headers=world.teacher).json()[
            "total"
        ]
        == 0
    )
    assert mark(world, attempt, {"score": "1"}, headers=world.me).status_code == 403  # a student
    other = {**attempt, "id": str(uuid.uuid4())}
    assert mark(world, other, {"score": "1"}).status_code == 404
