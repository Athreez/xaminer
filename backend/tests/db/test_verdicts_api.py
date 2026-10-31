"""The server's check of proctoring pictures (PRD PRC-07, § 6.5; TCK-1103, TCK-1104): camera
events wait unseen until checked, an event the pictures don't show is rejected (and its pictures
deleted), low confidence lowers the severity, a phone in a spot check becomes an event with that
picture as evidence, a spot check with nothing is deleted, and an event without pictures is shown
unchecked."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.storage import Storage
from app.db.session import system_session
from app.main import create_app
from app.proctoring import verdicts
from app.proctoring.models import ProctoringCapture, ProctoringEvent
from tests.db.api_helpers import S3_PORT, make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_captures_api import Sitting
from tests.db.test_start_attempt_api import World, build
from tests.services import require
from workers.inference_messages import Face, Finding, InferenceJob, Thing


@pytest.fixture(autouse=True)
def storage_running() -> None:
    require(S3_PORT, "Object storage")


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False, proctoring_mode="VIDEO")
        yield w
    await purge_institutions(migrator_engine, [college.id])


FACE = Face(score=0.9, area=0.1)
SMALL = Face(score=0.8, area=0.01)


def found(*faces: Face, things: tuple[Thing, ...] = ()) -> Finding:
    return Finding(id="p", faces=list(faces), things=list(things))


def test_what_confirms_an_event() -> None:
    assert verdicts.confirms("FACE_ABSENT", [found(), found(FACE), found()]) == pytest.approx(2 / 3)
    assert verdicts.confirms("FACE_ABSENT", [found(FACE)] * 3) == 0
    assert verdicts.confirms("MULTIPLE_FACES", [found(FACE, SMALL)]) == 0  # far behind: ignored
    assert verdicts.confirms("MULTIPLE_FACES", [found(FACE, FACE)]) == 1
    people = (Thing(label="person", score=0.8), Thing(label="person", score=0.6))
    assert verdicts.confirms("MULTIPLE_FACES", [found(FACE, things=people)]) == 1


def event(sitting: Sitting, kind: str, duration_ms: int) -> str:
    client_id = str(uuid.uuid4())
    body = {
        "events": [
            {
                "client_id": client_id,
                "kind": kind,
                "occurred_at": datetime.now(UTC).isoformat(),
                "duration_ms": duration_ms,
            }
        ]
    }
    world = sitting.world
    world.client.post(f"/api/v1/attempts/{sitting.id}/events", json=body, headers=world.me)
    return client_id


async def rows(world: World, model: Any, attempt_id: str) -> list[Any]:
    async with system_session(world.factory) as s:
        return list(
            await s.scalars(
                select(model)
                .where(model.attempt_id == uuid.UUID(attempt_id))
                .order_by(model.created_at)
            )
        )


def teacher_events(world: World, attempt_id: str) -> list[dict[str, Any]]:
    url = f"/api/v1/exams/{world.exam_id}/results/{attempt_id}"
    return world.client.get(url, headers=world.teacher).json()["events"]  # type: ignore[no-any-return]


async def test_camera_events_are_checked_before_the_teacher_sees_them(world: World) -> None:
    sitting = Sitting(world)
    absent = event(sitting, "FACE_ABSENT", 70_000)  # HIGH by the rules
    crowd = event(sitting, "MULTIPLE_FACES", 6_000)  # HIGH by the rules
    for client_id in (absent, crowd):
        for _ in range(3):
            sitting.send(purpose="EVENT", event_client_id=client_id)
    assert teacher_events(world, sitting.id) == []  # waiting for the check

    jobs: list[InferenceJob] = []
    storage = Storage(make_settings())
    assert (
        await verdicts.dispatch(
            world.factory, storage, send=jobs.append, attempts=[uuid.UUID(sitting.id)]
        )
        == 2
    )
    assert (
        await verdicts.dispatch(
            world.factory, storage, send=jobs.append, attempts=[uuid.UUID(sitting.id)]
        )
        == 0
    )  # sent once
    assert [len(j.pictures) for j in jobs] == [3, 3]
    assert httpx.get(jobs[0].pictures[0].url).status_code == 200  # the worker can fetch them

    by_kind = {e.client_id: e for e in await rows(world, ProctoringEvent, sitting.id)}
    absent_job, crowd_job = (
        next(j for j in jobs if j.job_id == f"event:{by_kind[uuid.UUID(c)].id}")
        for c in (absent, crowd)
    )
    # The face was there all along: rejected. One picture of three with a second face: kept,
    # one level lower.
    await verdicts.apply(
        world.factory,
        storage,
        {"job_id": absent_job.job_id, "findings": [found(FACE).model_dump()] * 3},
    )
    crowd_findings = [found(FACE, FACE), found(FACE), found(FACE)]
    await verdicts.apply(
        world.factory,
        storage,
        {"job_id": crowd_job.job_id, "findings": [f.model_dump() for f in crowd_findings]},
    )
    shown = teacher_events(world, sitting.id)
    assert [(e["kind"], e["severity"]) for e in shown] == [("MULTIPLE_FACES", "MEDIUM")]

    events = {e.kind: e for e in await rows(world, ProctoringEvent, sitting.id)}
    assert events["FACE_ABSENT"].status == "REJECTED"
    assert events["MULTIPLE_FACES"].confidence == pytest.approx(0.33)
    pictures = await rows(world, ProctoringCapture, sitting.id)
    rejected = [p for p in pictures if str(p.event_client_id) == absent]
    assert all(p.deleted_at is not None for p in rejected)
    assert httpx.get(storage.signed_url("evidence", rejected[0].storage_key, 60)).status_code == 404


async def test_spot_checks_become_phone_events_or_are_deleted(world: World) -> None:
    sitting = Sitting(world)
    sitting.send()
    sitting.send()
    jobs: list[InferenceJob] = []
    storage = Storage(make_settings())
    await verdicts.dispatch(
        world.factory, storage, send=jobs.append, attempts=[uuid.UUID(sitting.id)]
    )
    phone, nothing = jobs
    await verdicts.apply(
        world.factory,
        storage,
        {
            "job_id": phone.job_id,
            "findings": [found(FACE, things=(Thing(label="cell phone", score=0.9),)).model_dump()],
        },
    )
    await verdicts.apply(
        world.factory, storage, {"job_id": nothing.job_id, "findings": [found(FACE).model_dump()]}
    )
    (shown,) = teacher_events(world, sitting.id)
    assert (shown["kind"], shown["severity"]) == ("PHONE_DETECTED", "HIGH")
    url = f"/api/v1/exams/{world.exam_id}/results/{sitting.id}/pictures"
    pictures = world.client.get(url, headers=world.teacher).json()
    (evidence,) = pictures["events"][shown["id"]]
    assert httpx.get(evidence["url"]).status_code == 200  # moved out of tmp/, kept

    kept, gone = sorted(
        await rows(world, ProctoringCapture, sitting.id), key=lambda p: p.deleted_at is not None
    )
    assert not kept.storage_key.startswith("tmp/") and kept.purpose == "EVENT"
    assert gone.deleted_at is not None and gone.checked_at is not None


async def test_an_event_without_pictures_is_shown_unchecked(world: World) -> None:
    sitting = Sitting(world)
    event(sitting, "FACE_ABSENT", 20_000)
    storage = Storage(make_settings())
    jobs: list[InferenceJob] = []
    await verdicts.dispatch(
        world.factory, storage, send=jobs.append, attempts=[uuid.UUID(sitting.id)]
    )  # may still come
    assert teacher_events(world, sitting.id) == []
    later = datetime.now(UTC) + timedelta(minutes=3)
    await verdicts.dispatch(
        world.factory, storage, later, send=jobs.append, attempts=[uuid.UUID(sitting.id)]
    )
    assert jobs == []
    (shown,) = teacher_events(world, sitting.id)
    assert (shown["kind"], shown["severity"]) == ("FACE_ABSENT", "MEDIUM")
