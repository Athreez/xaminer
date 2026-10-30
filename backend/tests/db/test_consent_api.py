"""Consent before a proctored exam (PRD PRC-03; TCK-1001): starting is refused until the student
agrees, every answer is kept with the wording's hash, the latest answer counts, and an exam
without proctoring has no consent step."""

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import system_session
from app.main import create_app
from app.proctoring.consent import text_hash
from app.proctoring.models import ConsentRecord
from tests.db.api_helpers import make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_start_attempt_api import World, build


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False, proctoring_mode="VIDEO_AUDIO")
        yield w
    await purge_institutions(migrator_engine, [college.id])


async def test_start_needs_consent_and_the_latest_answer_counts(world: World) -> None:
    url = f"/api/v1/student/exams/{world.exam_id}/consent"
    refused = world.client.post(world.start_url, headers=world.me)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "CONSENT_REQUIRED"

    shown = world.client.get(url, headers=world.me).json()
    assert shown["decision"] is None and shown["proctoring_mode"] == "VIDEO_AUDIO"
    assert shown["screen_sharing"] is True  # on by default
    assert "your camera, microphone and screen" in shown["text"]
    detail = world.client.get(f"/api/v1/student/exams/{world.exam_id}", headers=world.me).json()
    assert detail["screen_sharing"] is True

    declined = world.client.post(url, json={"decision": "DECLINED"}, headers=world.me).json()
    assert declined["decision"] == "DECLINED"
    assert world.client.post(world.start_url, headers=world.me).status_code == 409

    world.client.post(url, json={"decision": "ACCEPTED"}, headers=world.me)
    assert world.client.get(url, headers=world.me).json()["decision"] == "ACCEPTED"
    started = world.client.post(world.start_url, headers=world.me)
    assert started.status_code == 200, started.text

    async with system_session(world.factory) as s:
        rows = list(
            await s.scalars(
                select(ConsentRecord)
                .where(ConsentRecord.exam_id == uuid.UUID(world.exam_id))
                .order_by(ConsentRecord.decided_at)
            )
        )
    assert [r.decision for r in rows] == ["DECLINED", "ACCEPTED"]  # every answer kept
    assert {r.consent_text_hash for r in rows} == {text_hash(shown["text"])}


async def test_teachers_cant_answer_for_students(world: World) -> None:
    url = f"/api/v1/student/exams/{world.exam_id}/consent"
    # A teacher isn't assigned to the exam, so it doesn't exist for them.
    r = world.client.post(url, json={"decision": "ACCEPTED"}, headers=world.teacher)
    assert r.status_code == 404
    bad = world.client.post(url, json={"decision": "MAYBE"}, headers=world.me)
    assert bad.status_code == 422


async def test_no_consent_step_without_proctoring(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine
) -> None:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False)
        try:
            r = client.get(f"/api/v1/student/exams/{w.exam_id}/consent", headers=w.me)
            assert r.json()["error"]["code"] == "NOT_PROCTORED"
            assert client.post(w.start_url, headers=w.me).status_code == 200
        finally:
            await purge_institutions(migrator_engine, [college.id])
