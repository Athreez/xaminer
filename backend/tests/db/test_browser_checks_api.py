"""Browser-check events (PRD PRC-06, PRC-07, PRC-09..11): stored with the server's severity,
repeats harmless, the teacher sees and reviews them, the integrity outcome follows, students never
see them, and an attempt long over takes no more."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import ExamAttempt
from app.db.session import system_session
from app.grading.objective import grade
from app.main import create_app
from app.proctoring.events import severity
from tests.db.api_helpers import make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_start_attempt_api import World, build


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False)
        yield w
    await purge_institutions(migrator_engine, [college.id])


@pytest.mark.parametrize(
    ("kind", "ms", "details", "expected"),
    [
        ("TAB_SWITCH", 2_000, {}, "LOW"),
        ("TAB_SWITCH", 10_000, {}, "MEDIUM"),
        ("TAB_SWITCH", 30_000, {}, "HIGH"),
        ("FULLSCREEN_EXIT", 3_000, {}, "LOW"),
        ("FULLSCREEN_EXIT", 6_000, {}, "HIGH"),
        ("PASTE_BLOCKED", None, {"length": 40}, "MEDIUM"),
        ("PASTE_BLOCKED", None, {"length": 200}, "HIGH"),
        ("MULTIPLE_SCREENS", None, {}, "MEDIUM"),
    ],
)
def test_severity_rules(kind: str, ms: int | None, details: dict[str, Any], expected: str) -> None:
    assert severity(kind, ms, details) == expected


def event(kind: str, **extra: Any) -> dict[str, Any]:
    return {
        "client_id": str(uuid.uuid4()),
        "kind": kind,
        "occurred_at": datetime.now(UTC).isoformat(),
    } | extra


async def test_events_from_the_exam_to_the_teachers_review(world: World) -> None:
    attempt = world.client.post(world.start_url, headers=world.me).json()
    url = f"/api/v1/attempts/{attempt['id']}/events"
    tab = event("TAB_SWITCH", duration_ms=40_000, details={"how": "tab"})
    paste = event("PASTE_BLOCKED", details={"length": 12, "secret": "not kept"})
    sent = world.client.post(url, json={"events": [tab, paste]}, headers=world.me)
    assert (sent.status_code, sent.content) == (204, b"")  # nothing comes back
    assert world.client.post(url, json={"events": [tab]}, headers=world.me).status_code == 204

    (row,) = world.client.get(
        f"/api/v1/exams/{world.exam_id}/monitor", headers=world.teacher
    ).json()["rows"]
    assert row["event_count"] == 2  # the repeat changed nothing

    world.client.post(f"/api/v1/attempts/{attempt['id']}/submit", headers=world.me)
    await grade(world.factory, uuid.UUID(attempt["id"]))
    detail_url = f"/api/v1/exams/{world.exam_id}/results/{attempt['id']}"
    detail = world.client.get(detail_url, headers=world.teacher).json()
    kinds = [(e["kind"], e["severity"]) for e in detail["events"]]
    assert sorted(kinds) == [("PASTE_BLOCKED", "MEDIUM"), ("TAB_SWITCH", "HIGH")]
    assert all("secret" not in e["details"] for e in detail["events"])  # only known facts kept

    for e in detail["events"]:
        decision = "FLAGGED" if e["kind"] == "TAB_SWITCH" else "DISMISSED"
        r = world.client.put(
            f"/api/v1/proctoring-events/{e['id']}/decision",
            json={"decision": decision, "note": "checked"},
            headers=world.teacher,
        )
        assert r.status_code == 200, r.text
        assert (
            world.client.put(
                f"/api/v1/proctoring-events/{e['id']}/decision",
                json={"decision": "DISMISSED"},
                headers=world.me,
            ).status_code
            == 403
        )  # students can't review
    detail = world.client.get(detail_url, headers=world.teacher).json()
    assert detail["integrity_outcome"] == "CONCERNS_CONFIRMED"  # one flagged
    (row,) = world.client.get(
        f"/api/v1/exams/{world.exam_id}/monitor", headers=world.teacher
    ).json()["rows"]
    assert row["event_count"] == 1  # the dismissed one no longer counts


async def test_students_never_see_events_and_late_ones_are_refused(world: World) -> None:
    attempt = world.client.post(world.start_url, headers=world.me).json()
    url = f"/api/v1/attempts/{attempt['id']}/events"
    world.client.post(url, json={"events": [event("MULTIPLE_SCREENS")]}, headers=world.me)
    world.client.post(f"/api/v1/attempts/{attempt['id']}/submit", headers=world.me)
    await grade(world.factory, uuid.UUID(attempt["id"]))
    world.client.post(f"/api/v1/exams/{world.exam_id}/results/release", headers=world.teacher)
    mine = world.client.get(f"/api/v1/student/results/{attempt['id']}", headers=world.me)
    assert mine.status_code == 200, mine.text
    body = mine.json()
    assert body["integrity_outcome"] == "PENDING_REVIEW"  # the outcome only, never the events
    assert "MULTIPLE_SCREENS" not in mine.text and "severity" not in mine.text

    async with system_session(world.factory) as s:
        await s.execute(
            update(ExamAttempt)
            .where(ExamAttempt.id == uuid.UUID(attempt["id"]))
            .values(submitted_at=datetime.now(UTC) - timedelta(minutes=20))
        )
        await s.commit()
    late = world.client.post(url, json={"events": [event("TAB_SWITCH")]}, headers=world.me)
    assert late.status_code == 409
