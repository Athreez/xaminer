"""Camera events and SIGNAL_LOST (PRD § 6.5, PRC-14; TCK-1004, TCK-1105): the exam screen gets
what to watch for, camera events are stored with the server's severity, and SIGNAL_LOST comes
only from heartbeats that arrive while the frame count stands still, never from a lost
connection."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import ExamAttempt
from app.db.session import system_session, tenant_session
from app.main import create_app
from app.proctoring import signal
from app.proctoring.models import ProctoringEvent
from tests.db.api_helpers import make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_start_attempt_api import World, build


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False, proctoring_mode="VIDEO")
        yield w
    await purge_institutions(migrator_engine, [college.id])


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(make_settings().redis_url.get_secret_value())
    yield client
    await client.aclose()


def start(world: World) -> str:
    consent = f"/api/v1/student/exams/{world.exam_id}/consent"
    world.client.post(consent, json={"decision": "ACCEPTED"}, headers=world.me)
    started = world.client.post(world.start_url, headers=world.me)
    assert started.status_code == 200, started.text
    return str(started.json()["id"])


async def events(world: World, attempt_id: str) -> list[ProctoringEvent]:
    async with system_session(world.factory) as s:
        return list(
            await s.scalars(
                select(ProctoringEvent).where(ProctoringEvent.attempt_id == uuid.UUID(attempt_id))
            )
        )


async def test_camera_events_get_the_servers_severity(world: World) -> None:
    attempt_id = start(world)
    view = world.client.get(f"/api/v1/attempts/{attempt_id}", headers=world.me).json()
    assert view["proctoring"] == {
        "mode": "VIDEO",
        "screen_sharing": True,
        "sensitivity": "STANDARD",
        "gaze": False,
    }
    now = datetime.now(UTC).isoformat()
    sent = [
        {"kind": "FACE_ABSENT", "duration_ms": 70_000},
        {"kind": "MULTIPLE_FACES", "duration_ms": 3_000, "details": {"faces": 2}},
        {"kind": "GAZE_AWAY", "duration_ms": 9_000, "details": {"direction": "left"}},
        {"kind": "SCREEN_SHARE_STOPPED", "duration_ms": 20_000},
    ]
    body = {"events": [{"client_id": str(uuid.uuid4()), "occurred_at": now} | e for e in sent]}
    response = world.client.post(
        f"/api/v1/attempts/{attempt_id}/events", json=body, headers=world.me
    )
    assert response.status_code == 204, response.text
    stored = {e.kind: (e.severity, e.details) for e in await events(world, attempt_id)}
    assert stored == {
        "FACE_ABSENT": ("HIGH", {}),
        "MULTIPLE_FACES": ("MEDIUM", {"faces": 2}),
        "GAZE_AWAY": ("LOW", {"direction": "left"}),
        "SCREEN_SHARE_STOPPED": ("MEDIUM", {}),
    }
    # SIGNAL_LOST is the server's own.
    body = {"events": [{"client_id": str(uuid.uuid4()), "occurred_at": now, "kind": "SIGNAL_LOST"}]}
    response = world.client.post(
        f"/api/v1/attempts/{attempt_id}/events", json=body, headers=world.me
    )
    assert response.status_code == 422


async def test_signal_lost_only_while_heartbeats_arrive(world: World, redis: Redis) -> None:
    attempt_id = start(world)
    beat = world.client.post(
        f"/api/v1/attempts/{attempt_id}/heartbeat", json={"proctoring_frames": 10}, headers=world.me
    )
    assert beat.status_code == 200, beat.text
    t0 = datetime.now(UTC)

    async def check(frames: int | None, seconds: int) -> None:
        async with tenant_session(world.factory, world.college.id) as s:
            attempt = await s.get_one(ExamAttempt, uuid.UUID(attempt_id))
            await signal.check(s, redis, attempt, frames, t0 + timedelta(seconds=seconds))

    await check(40, 30)  # frames moving: fine
    await check(40, 80)  # 50 s still: not yet
    assert await events(world, attempt_id) == []
    await check(40, 100)  # 70 s still
    await check(None, 400)  # still, and the screen stopped saying: the same event, extended
    (lost,) = await events(world, attempt_id)
    assert (lost.kind, lost.severity, lost.duration_ms) == ("SIGNAL_LOST", "HIGH", 370_000)

    # A lost connection: heartbeats stop, the state is forgotten, and nothing new is raised.
    await redis.delete(f"attempt:{attempt_id}:proctoring")
    await check(None, 1000)
    await check(None, 1030)
    assert len(await events(world, attempt_id)) == 1


async def test_no_signal_lost_without_proctoring(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, redis: Redis
) -> None:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False)
        attempt_id = client.post(w.start_url, headers=w.me).json()["id"]
        t0 = datetime.now(UTC)
        async with tenant_session(w.factory, college.id) as s:
            attempt = await s.get_one(ExamAttempt, uuid.UUID(attempt_id))
            for seconds in (0, 100, 400):
                await signal.check(s, redis, attempt, None, t0 + timedelta(seconds=seconds))
        assert await events(w, attempt_id) == []
    await purge_institutions(migrator_engine, [college.id])
