"""The teacher's preview attempt through the real HTTP API (PRD EX-07)."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import ExamAttempt
from app.auth.tokens import Principal, create_access_token
from app.db.session import tenant_session
from app.main import create_app
from app.users.models import User
from tests.db.api_helpers import SECRET, make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_start_attempt_api import World, build


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    """A published exam; tests make their own draft when they need one."""
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False)
        yield w
    await purge_institutions(migrator_engine, [college.id])


def preview(world: World, exam_id: str):  # type: ignore[no-untyped-def]
    return world.client.post(f"/api/v1/exams/{exam_id}/preview-attempt", headers=world.teacher)


def draft(
    world: World, title: str = "Draft quiz", body: str = "What is a stack?"
) -> tuple[str, str]:
    """A draft exam with one descriptive question. Returns (exam id, question id)."""
    question = world.client.post(
        "/api/v1/questions",
        json={"type": "DESCRIPTIVE", "body": body, "points": "4", "rubric": "LIFO"},
        headers=world.teacher,
    ).json()["id"]
    exam = world.client.post("/api/v1/exams", json={"title": title}, headers=world.teacher).json()
    world.client.put(
        f"/api/v1/exams/{exam['id']}/questions",
        json={"questions": [{"question_id": question}]},
        headers=world.teacher,
    )
    return exam["id"], question


async def attempts_of(world: World, exam_id: str) -> list[ExamAttempt]:
    async with tenant_session(world.factory, world.college.id) as s:
        rows = await s.scalars(select(ExamAttempt).where(ExamAttempt.exam_id == uuid.UUID(exam_id)))
        return list(rows)


async def test_preview_a_draft_and_continue_it_like_a_student(world: World) -> None:
    exam_id, _ = draft(world)
    response = preview(world, exam_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Draft quiz" and body["status"] == "IN_PROGRESS"
    assert [q["question"]["body"] for q in body["questions"]] == ["What is a stack?"]
    assert "LIFO" not in response.text and "rubric" not in response.text  # still the student view
    assert 3500 <= body["seconds_left"] <= 3600  # no duration set yet: 60 minutes

    (attempt,) = await attempts_of(world, exam_id)
    assert attempt.is_preview and attempt.exam_version_id is None and attempt.preview_snapshot

    # The rest of the exam works through the usual endpoints, as the teacher.
    eq = body["questions"][0]["exam_question_id"]
    saved = world.client.put(
        f"/api/v1/attempts/{body['id']}/answers",
        json={
            "answers": [
                {"exam_question_id": eq, "text_answer": "Last in, first out", "client_revision": 1}
            ]
        },
        headers=world.teacher,
    )
    assert saved.status_code == 200 and saved.json()["saved"] == [eq]
    assert (
        world.client.get(f"/api/v1/attempts/{body['id']}", headers=world.teacher).status_code == 200
    )
    receipt = world.client.post(f"/api/v1/attempts/{body['id']}/submit", headers=world.teacher)
    assert receipt.status_code == 200 and receipt.json()["answered"] == 1


async def test_each_preview_replaces_the_last_and_shows_edits(world: World) -> None:
    exam_id, question_id = draft(world, body="Version one")
    first = preview(world, exam_id).json()
    world.client.patch(
        f"/api/v1/questions/{question_id}", json={"body": "Version two"}, headers=world.teacher
    )
    second = preview(world, exam_id).json()
    assert second["id"] != first["id"]
    assert second["questions"][0]["question"]["body"] == "Version two"
    statuses = {str(a.id): a.status for a in await attempts_of(world, exam_id)}
    assert statuses == {first["id"]: "VOIDED", second["id"]: "IN_PROGRESS"}
    # The draft's question wasn't locked by previewing: it can still be edited in place.
    edited = world.client.patch(
        f"/api/v1/questions/{question_id}", json={"body": "Version three"}, headers=world.teacher
    )
    assert "X-New-Version" not in edited.headers


async def test_preview_a_published_exam_uses_the_published_version(world: World) -> None:
    response = preview(world, world.exam_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [q["exam_question_id"] for q in body["questions"]] == world.question_order
    teacher_attempt = next(a for a in await attempts_of(world, world.exam_id) if a.is_preview)
    assert teacher_attempt.exam_version_id is not None and teacher_attempt.preview_snapshot is None

    # The student's own attempt is unaffected, and the preview never shows in the student's list.
    student = world.client.post(world.start_url, headers=world.me)
    assert student.status_code == 200
    listed = world.client.get("/api/v1/student/exams", headers=world.me).json()
    assert [e["state"] for e in listed["available"]] == ["IN_PROGRESS"]


async def test_nothing_to_preview(world: World) -> None:
    empty = world.client.post(
        "/api/v1/exams", json={"title": "Empty"}, headers=world.teacher
    ).json()
    refused = preview(world, empty["id"])
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "NO_QUESTIONS"
    world.client.post(f"/api/v1/exams/{empty['id']}/archive", headers=world.teacher)
    assert preview(world, empty["id"]).json()["error"]["code"] == "EXAM_ARCHIVED"


async def test_only_the_owner_previews(world: World) -> None:
    exam_id, _ = draft(world)
    async with tenant_session(world.factory, world.college.id) as s:
        colleague = User(email=f"c{uuid.uuid4().hex[:8]}@abc.edu", full_name="C", role="TEACHER")
        s.add(colleague)
        await s.commit()
    token = create_access_token(Principal(colleague.id, world.college.id, "TEACHER"), SECRET, 15)
    response = world.client.post(
        f"/api/v1/exams/{exam_id}/preview-attempt", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404
    student: dict[str, Any] = world.client.post(
        f"/api/v1/exams/{exam_id}/preview-attempt", headers=world.me
    ).json()
    assert student["error"]["code"] == "FORBIDDEN"
