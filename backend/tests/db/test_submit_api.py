"""Submitting, auto-submitting and the sweeper (PRD ATT-10, ATT-11)."""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts import submit as submit_service
from app.attempts.models import ExamAttempt
from app.audit.models import AuditLog
from app.auth.tokens import Principal
from app.db.session import create_session_factory, tenant_session
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


def begin(world: World) -> dict[str, Any]:
    return world.client.post(world.start_url, headers=world.me).json()  # type: ignore[no-any-return]


def submit(world: World, attempt_id: str):  # type: ignore[no-untyped-def]
    return world.client.post(f"/api/v1/attempts/{attempt_id}/submit", headers=world.me)


def save(world: World, attempt_id: str, answers: list[dict[str, Any]]):  # type: ignore[no-untyped-def]
    return world.client.put(
        f"/api/v1/attempts/{attempt_id}/answers", json={"answers": answers}, headers=world.me
    )


async def status_of(world: World, attempt_id: str) -> str:
    async with tenant_session(world.factory, world.college.id) as s:
        attempt = await s.get(ExamAttempt, uuid.UUID(attempt_id))
        assert attempt is not None
        return attempt.status


async def endings(world: World, attempt_id: str) -> list[AuditLog]:
    async with tenant_session(world.factory, world.college.id) as s:
        return list(
            await s.scalars(
                select(AuditLog).where(
                    AuditLog.target_id == uuid.UUID(attempt_id),
                    AuditLog.action.in_(("attempt.submitted", "attempt.auto_submitted")),
                )
            )
        )


async def overdue(world: World, attempt_id: str, seconds: int = 120) -> None:
    await world.set_attempt(
        attempt_id,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        deadline_at=datetime.now(UTC) - timedelta(seconds=seconds),
    )


async def test_submit_gives_a_receipt_and_repeating_is_harmless(world: World) -> None:
    attempt = begin(world)
    essay, mcq = (
        attempt["questions"][3]["exam_question_id"],
        attempt["questions"][0]["exam_question_id"],
    )
    save(
        world,
        attempt["id"],
        [
            {"exam_question_id": essay, "text_answer": "Base case", "client_revision": 1},
            {"exam_question_id": mcq, "selected_option_ids": [], "client_revision": 1},
        ],
    )
    first = submit(world, attempt["id"])
    assert first.status_code == 200, first.text
    receipt = first.json()
    assert receipt["status"] == "SUBMITTED"
    assert (receipt["answered"], receipt["total"]) == (1, 4)  # a cleared answer doesn't count
    assert re.fullmatch(r"[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}", receipt["code"])

    assert submit(world, attempt["id"]).json() == receipt  # double submit: the same receipt
    again = world.client.get(f"/api/v1/attempts/{attempt['id']}/receipt", headers=world.me)
    assert again.json() == receipt
    assert len(await endings(world, attempt["id"])) == 1

    # Afterwards nothing changes the attempt.
    late = save(
        world,
        attempt["id"],
        [{"exam_question_id": essay, "text_answer": "x", "client_revision": 2}],
    )
    assert late.status_code == 409 and late.json()["error"]["code"] == "ATTEMPT_SUBMITTED"
    resumed = world.client.get(f"/api/v1/attempts/{attempt['id']}", headers=world.me)
    assert resumed.json()["error"]["code"] == "ALREADY_SUBMITTED"
    restart = world.client.post(world.start_url, headers=world.me)
    assert restart.json()["error"]["code"] == "ALREADY_SUBMITTED"
    listed = world.client.get("/api/v1/student/exams", headers=world.me).json()
    assert [e["state"] for e in listed["completed"]] == ["SUBMITTED"]


async def test_no_receipt_before_submitting(world: World) -> None:
    attempt = begin(world)
    response = world.client.get(f"/api/v1/attempts/{attempt['id']}/receipt", headers=world.me)
    assert response.status_code == 404


async def test_submitting_after_the_grace_counts_as_automatic(world: World) -> None:
    attempt = begin(world)
    await overdue(world, attempt["id"])
    assert submit(world, attempt["id"]).json()["status"] == "AUTO_SUBMITTED"
    (row,) = await endings(world, attempt["id"])
    assert row.action == "attempt.auto_submitted" and row.actor_id is None


async def test_touching_an_overdue_attempt_ends_it(world: World) -> None:
    attempt = begin(world)
    await overdue(world, attempt["id"])
    essay = attempt["questions"][3]["exam_question_id"]
    late = save(
        world,
        attempt["id"],
        [{"exam_question_id": essay, "text_answer": "late", "client_revision": 1}],
    )
    assert late.status_code == 409 and late.json()["error"]["code"] == "TIME_UP"
    assert await status_of(world, attempt["id"]) == "AUTO_SUBMITTED"
    receipt = world.client.get(f"/api/v1/attempts/{attempt['id']}/receipt", headers=world.me).json()
    assert receipt["status"] == "AUTO_SUBMITTED" and receipt["answered"] == 0


async def test_sweeper_ends_only_attempts_past_the_grace(
    world: World, app_engine: AsyncEngine
) -> None:
    factory = create_session_factory(app_engine)
    attempt = begin(world)
    await overdue(world, attempt["id"], seconds=30)  # inside the grace: a save may still arrive
    await submit_service.sweep(factory)
    assert await status_of(world, attempt["id"]) == "IN_PROGRESS"

    await overdue(world, attempt["id"], seconds=61)
    assert await submit_service.sweep(factory) >= 1
    assert await status_of(world, attempt["id"]) == "AUTO_SUBMITTED"
    await submit_service.sweep(factory)  # running again is harmless
    assert len(await endings(world, attempt["id"])) == 1


async def test_submit_racing_the_sweeper_ends_it_once(
    world: World, app_engine: AsyncEngine
) -> None:
    factory = create_session_factory(app_engine)
    attempt = begin(world)
    await overdue(world, attempt["id"])
    principal = Principal(world.student.id, world.college.id, "STUDENT")

    async def student() -> None:
        async with tenant_session(factory, world.college.id) as s:
            await submit_service.submit(s, principal, uuid.UUID(attempt["id"]))

    await asyncio.gather(student(), submit_service.sweep(factory), student())
    assert await status_of(world, attempt["id"]) == "AUTO_SUBMITTED"
    assert len(await endings(world, attempt["id"])) == 1


async def test_voided_attempts_have_no_receipt(world: World) -> None:
    attempt = begin(world)
    await world.set_attempt(attempt["id"], status="VOIDED")
    assert submit(world, attempt["id"]).status_code == 404
