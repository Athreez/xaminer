"""Teacher actions on attempts through the real HTTP API (PRD MON-02, ATT-02)."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.models import AuditLog
from app.db.session import tenant_session
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


def act(world: World, attempt_id: str, action: str, **body: Any):  # type: ignore[no-untyped-def]
    return world.client.post(
        f"/api/v1/attempts/{attempt_id}/{action}", json=body, headers=world.teacher
    )


def heartbeat(world: World, attempt_id: str) -> dict[str, Any]:
    response = world.client.post(
        f"/api/v1/attempts/{attempt_id}/heartbeat", json={}, headers=world.me
    )
    return response.json()  # type: ignore[no-any-return]


async def audit(world: World, attempt_id: str, action: str) -> list[AuditLog]:
    async with tenant_session(world.factory, world.college.id) as s:
        return list(
            await s.scalars(
                select(AuditLog).where(
                    AuditLog.target_id == uuid.UUID(attempt_id), AuditLog.action == action
                )
            )
        )


async def test_extension_reaches_the_student_on_the_next_heartbeat(world: World) -> None:
    attempt = begin(world)
    response = act(
        world, attempt["id"], "extend", minutes=15, reason="Wi-Fi dropped for 10 minutes"
    )
    assert response.status_code == 200, response.text
    extended = response.json()
    expected = datetime.fromisoformat(attempt["deadline_at"]) + timedelta(minutes=15)
    assert (
        datetime.fromisoformat(extended["deadline_at"]) == expected
        and extended["extra_minutes"] == 15
    )

    beat = heartbeat(world, attempt["id"])  # acceptance: visible on the next heartbeat
    assert datetime.fromisoformat(beat["deadline_at"]) == expected and beat["extra_minutes"] == 15
    (row,) = await audit(world, attempt["id"], "attempt.extended")
    assert row.changes is not None and row.changes["reason"] == "Wi-Fi dropped for 10 minutes"
    assert row.actor_role == "TEACHER"


async def test_the_window_end_limits_extensions(world: World) -> None:
    now = datetime.now(UTC)
    await world.window(-timedelta(minutes=50), timedelta(minutes=30))  # started late: cut by close
    attempt = begin(world)
    refused = act(world, attempt["id"], "extend", minutes=10, reason="Fire drill")
    assert refused.status_code == 409
    error = refused.json()["error"]
    assert error["code"] == "WINDOW_ENDS_FIRST" and error["details"][0]["field"] == "close_at"

    # Move the window's end (allowed after publishing), then the extension works.
    later = (now + timedelta(hours=2)).isoformat()
    moved = world.client.patch(
        f"/api/v1/exams/{world.exam_id}", json={"close_at": later}, headers=world.teacher
    )
    assert moved.status_code == 200, moved.text
    assert act(world, attempt["id"], "extend", minutes=10, reason="Fire drill").status_code == 200


async def test_extension_limits_and_reasons(world: World) -> None:
    await world.window(-timedelta(hours=1), timedelta(hours=20))
    attempt = begin(world)
    for _ in range(5):
        assert (
            act(world, attempt["id"], "extend", minutes=120, reason="Accommodation").status_code
            == 200
        )
    too_much = act(world, attempt["id"], "extend", minutes=1, reason="Accommodation")
    assert too_much.status_code == 409 and too_much.json()["error"]["code"] == "TOO_MUCH_EXTRA_TIME"
    assert act(world, attempt["id"], "extend", minutes=5).status_code == 422  # reason required
    assert act(world, attempt["id"], "extend", minutes=5, reason="  ").status_code == 422
    assert act(world, attempt["id"], "extend", minutes=0, reason="Accommodation").status_code == 422


async def test_force_submit(world: World) -> None:
    attempt = begin(world)
    response = act(world, attempt["id"], "force-submit", reason="Left the exam hall")
    assert response.status_code == 200 and response.json()["status"] == "AUTO_SUBMITTED"
    assert heartbeat(world, attempt["id"])["status"] == "AUTO_SUBMITTED"
    essay = attempt["questions"][3]["exam_question_id"]
    late = world.client.put(
        f"/api/v1/attempts/{attempt['id']}/answers",
        json={"answers": [{"exam_question_id": essay, "text_answer": "x", "client_revision": 1}]},
        headers=world.me,
    )
    assert late.json()["error"]["code"] == "ATTEMPT_SUBMITTED"
    again = act(world, attempt["id"], "force-submit", reason="Twice")
    assert again.status_code == 409 and again.json()["error"]["code"] == "ATTEMPT_ENDED"
    assert (
        act(world, attempt["id"], "extend", minutes=5, reason="Too late").json()["error"]["code"]
        == "ATTEMPT_ENDED"
    )
    (row,) = await audit(world, attempt["id"], "attempt.force_submitted")
    assert row.changes == {"reason": "Left the exam hall"}


async def test_void_lets_the_student_start_again(world: World) -> None:
    attempt = begin(world)
    world.client.post(f"/api/v1/attempts/{attempt['id']}/submit", headers=world.me)
    voided = act(world, attempt["id"], "void", reason="Sat the wrong paper")
    assert voided.status_code == 200 and voided.json()["status"] == "VOIDED"  # even after submit
    assert heartbeat(world, attempt["id"])["status"] == "VOIDED"
    assert (
        act(world, attempt["id"], "void", reason="Again").json()["error"]["code"]
        == "ALREADY_VOIDED"
    )

    fresh = world.client.post(world.start_url, headers=world.me)
    assert fresh.status_code == 200 and fresh.json()["id"] != attempt["id"]
    (row,) = await audit(world, attempt["id"], "attempt.voided")
    assert row.changes is not None and row.changes["status"] == {
        "old": "SUBMITTED",
        "new": "VOIDED",
    }


async def test_students_cannot_manage_attempts(world: World) -> None:
    attempt = begin(world)
    response = world.client.post(
        f"/api/v1/attempts/{attempt['id']}/extend",
        json={"minutes": 30, "reason": "Please"},
        headers=world.me,
    )
    assert response.status_code == 403
