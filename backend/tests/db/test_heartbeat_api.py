"""The heartbeat through the real HTTP API (PRD ATT-04, ATT-12)."""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.heartbeat import live_key
from app.attempts.models import ExamAttempt
from app.auth.tokens import InvalidTokenError, decode_access_token, decode_attempt_token
from app.db.session import tenant_session
from app.main import create_app
from tests.db.api_helpers import SECRET, make_settings
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


def beat(world: World, attempt_id: str, unsynced: int = 0):  # type: ignore[no-untyped-def]
    return world.client.post(
        f"/api/v1/attempts/{attempt_id}/heartbeat", json={"unsynced": unsynced}, headers=world.me
    )


async def last_beat(world: World, attempt_id: str) -> datetime | None:
    async with tenant_session(world.factory, world.college.id) as s:
        attempt = await s.get(ExamAttempt, uuid.UUID(attempt_id))
        assert attempt is not None
        return attempt.last_heartbeat_at


async def test_heartbeat_reports_time_and_issues_an_upload_token(
    world: World, redis: Redis
) -> None:
    attempt = world.client.post(world.start_url, headers=world.me).json()
    response = beat(world, attempt["id"], unsynced=3)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "IN_PROGRESS" and body["accepts_saves"] is True
    assert body["deadline_at"] == attempt["deadline_at"] and 0 < body["seconds_left"] <= 3600
    assert body["attempt_token_expires_in"] == 600

    grant = decode_attempt_token(body["attempt_token"], SECRET)
    assert str(grant.attempt_id) == attempt["id"] and grant.user_id == world.student.id
    # Upload-only: it is not an access token, and the API refuses it.
    with pytest.raises(InvalidTokenError):
        decode_access_token(body["attempt_token"], SECRET)
    refused = world.client.get(
        "/api/v1/student/exams", headers={"Authorization": f"Bearer {body['attempt_token']}"}
    )
    assert refused.status_code == 401
    # And an access token is not an attempt token.
    with pytest.raises(InvalidTokenError):
        decode_attempt_token(world.me["Authorization"].removeprefix("Bearer "), SECRET)

    live = json.loads(await redis.get(live_key(uuid.UUID(attempt["id"]))) or "{}")
    assert live["unsynced"] == 3


async def test_postgres_is_written_at_most_once_a_minute(world: World, redis: Redis) -> None:
    attempt = world.client.post(world.start_url, headers=world.me).json()
    beat(world, attempt["id"])
    first = await last_beat(world, attempt["id"])
    assert first is not None
    for _ in range(4):
        assert beat(world, attempt["id"]).status_code == 200
    assert await last_beat(world, attempt["id"]) == first  # buffered in Redis meanwhile

    await redis.delete(f"attempt:{attempt['id']}:heartbeat-written")  # as if a minute passed
    beat(world, attempt["id"])
    later = await last_beat(world, attempt["id"])
    assert later is not None and later > first


async def test_teacher_actions_reach_the_screen(world: World) -> None:
    attempt = world.client.post(world.start_url, headers=world.me).json()
    extended = datetime.fromisoformat(attempt["deadline_at"]) + timedelta(minutes=15)
    await world.set_attempt(attempt["id"], deadline_at=extended, extra_minutes=15)
    body = beat(world, attempt["id"]).json()
    assert datetime.fromisoformat(body["deadline_at"]) == extended and body["extra_minutes"] == 15

    await world.set_attempt(attempt["id"], status="AUTO_SUBMITTED", submitted_at=datetime.now(UTC))
    body = beat(world, attempt["id"]).json()
    assert body["status"] == "AUTO_SUBMITTED" and body["attempt_token"] is None
    assert body["accepts_saves"] is False

    await world.set_attempt(attempt["id"], status="VOIDED")
    assert beat(world, attempt["id"]).json()["status"] == "VOIDED"


async def test_after_the_grace_saves_stop(world: World) -> None:
    attempt = world.client.post(world.start_url, headers=world.me).json()
    await world.set_attempt(
        attempt["id"],
        started_at=datetime.now(UTC) - timedelta(hours=1),
        deadline_at=datetime.now(UTC) - timedelta(seconds=90),
    )
    body = beat(world, attempt["id"]).json()
    assert body["seconds_left"] == 0 and body["accepts_saves"] is False
