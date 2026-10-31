"""Proctoring pictures through the real API and real storage (PRD PRC-05, PRC-10, PRC-13,
PRC-17; TCK-1006, TCK-1102, TCK-1107): only with the attempt token, checked and re-encoded (EXIF
gone), repeats and pictures over the limits dropped quietly, the exam's teacher sees them through
short links (audited), spot checks never, and the cleanup deletes them on time."""

import io
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.models import AuditLog
from app.core.storage import Storage
from app.db.session import system_session, tenant_session
from app.exams.models import Exam
from app.main import create_app
from app.proctoring import captures
from app.proctoring.models import ProctoringCapture
from app.users.models import User
from tests.db.api_helpers import S3_PORT, make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_start_attempt_api import World, bearer, build
from tests.services import require


@pytest.fixture(autouse=True)
def storage_running() -> None:
    require(S3_PORT, "Object storage")


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False, proctoring_mode="VIDEO")
        yield w
    await purge_institutions(migrator_engine, [college.id])


def jpeg_with_gps() -> bytes:
    exif = Image.Exif()
    exif[0x8825] = {2: (51.0, 30.0, 0.0)}  # GPS latitude
    out = io.BytesIO()
    Image.new("RGB", (64, 48), "teal").save(out, "JPEG", exif=exif)
    return out.getvalue()


class Sitting:
    """A started proctored attempt and its attempt token."""

    def __init__(self, world: World) -> None:
        consent = f"/api/v1/student/exams/{world.exam_id}/consent"
        world.client.post(consent, json={"decision": "ACCEPTED"}, headers=world.me)
        self.world = world
        self.id = world.client.post(world.start_url, headers=world.me).json()["id"]
        beat = world.client.post(f"/api/v1/attempts/{self.id}/heartbeat", json={}, headers=world.me)
        self.token = {"Authorization": f"Bearer {beat.json()['attempt_token']}"}

    def send(
        self, headers: dict[str, str] | None = None, data: bytes | None = None, **fields: Any
    ) -> httpx.Response:
        form = {
            "client_id": str(uuid.uuid4()),
            "kind": "CAMERA",
            "purpose": "SPOT_CHECK",
            "taken_at": datetime.now(UTC).isoformat(),
        } | {k: str(v) for k, v in fields.items()}
        return self.world.client.post(
            f"/api/v1/attempts/{self.id}/captures",
            data=form,
            files={"image": ("p.jpg", data or jpeg_with_gps(), "image/jpeg")},
            headers=self.token if headers is None else headers,
        )


async def stored(world: World, attempt_id: str) -> list[ProctoringCapture]:
    async with system_session(world.factory) as s:
        return list(
            await s.scalars(
                select(ProctoringCapture)
                .where(ProctoringCapture.attempt_id == uuid.UUID(attempt_id))
                .order_by(ProctoringCapture.created_at)
            )
        )


async def test_uploads_need_the_attempt_token_and_are_cleaned(world: World) -> None:
    exam = Sitting(world)
    assert exam.send(headers=world.me).status_code == 401  # the access token isn't enough
    assert exam.send(headers={}).status_code == 401
    assert exam.send(data=b"not a picture").status_code == 422
    assert exam.send(kind="SCREEN", purpose="SPOT_CHECK").status_code == 422
    assert exam.send(purpose="EVENT").status_code == 422  # an event picture names its event

    same = str(uuid.uuid4())
    for _ in range(2):  # a repeat changes nothing
        response = exam.send(client_id=same)
        assert (response.status_code, response.content) == (204, b"")
    (row,) = await stored(world, exam.id)
    assert row.storage_key.startswith("tmp/") and row.purpose == "SPOT_CHECK"

    other = Sitting.__new__(Sitting)
    other.world, other.token, other.id = world, exam.token, str(uuid.uuid4())
    assert other.send().status_code == 404  # the token is for one attempt only


async def test_the_teacher_sees_event_and_screen_pictures(world: World) -> None:
    exam = Sitting(world)
    event = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    events = {"events": [{"client_id": event, "kind": "GAZE_AWAY", "occurred_at": now}]}
    world.client.post(f"/api/v1/attempts/{exam.id}/events", json=events, headers=world.me)
    for _ in range(4):  # the 4th is over the limit of 3 per event: dropped quietly
        assert exam.send(purpose="EVENT", event_client_id=event).status_code == 204
    assert exam.send(kind="SCREEN", purpose="LEFT_PAGE").status_code == 204
    assert exam.send().status_code == 204  # a spot check: never shown
    assert len(await stored(world, exam.id)) == 5

    url = f"/api/v1/exams/{world.exam_id}/results/{exam.id}/pictures"
    assert world.client.get(url, headers=world.me).status_code == 403
    pictures = world.client.get(url, headers=world.teacher).json()
    (event_pictures,) = pictures["events"].values()
    assert len(event_pictures) == 3
    (screen,) = pictures["screen"]
    assert screen["purpose"] == "LEFT_PAGE"
    fetched = httpx.get(screen["url"])
    assert fetched.status_code == 200 and fetched.headers["content-type"] == "image/webp"
    assert not Image.open(io.BytesIO(fetched.content)).getexif()  # the GPS position is gone

    async with system_session(world.factory) as s:
        logged = await s.scalars(
            select(AuditLog).where(
                AuditLog.action == "proctoring.evidence_viewed",
                AuditLog.target_id == uuid.UUID(exam.id),
            )
        )
        assert len(list(logged)) == 1


async def test_cleanup_deletes_spot_checks_soon_and_evidence_after_retention(
    world: World,
) -> None:
    exam = Sitting(world)
    assert exam.send().status_code == 204
    assert exam.send(kind="SCREEN", purpose="PERIODIC").status_code == 204
    storage = Storage(make_settings())
    spot, screen = await stored(world, exam.id)

    await captures.clean_up(world.factory, storage)  # nothing due yet
    assert all(c.deleted_at is None for c in await stored(world, exam.id))

    await captures.clean_up(world.factory, storage, datetime.now(UTC) + timedelta(minutes=31))
    spot, screen = await stored(world, exam.id)
    assert spot.deleted_at is not None and screen.deleted_at is None

    async with system_session(world.factory) as s:  # the window closed 31 days ago
        await s.execute(
            update(Exam)
            .where(Exam.id == uuid.UUID(world.exam_id))
            .values(
                open_at=datetime.now(UTC) - timedelta(days=32),
                close_at=datetime.now(UTC) - timedelta(days=31),
            )
        )
        await s.commit()
    async with tenant_session(world.factory, world.college.id) as s:
        admin = User(email=f"a{uuid.uuid4().hex[:8]}@abc.edu", full_name="A", role="ADMIN")
        s.add(admin)
        await s.commit()
    overdue = world.client.get("/api/v1/institution/settings", headers=bearer(admin, world.college))
    assert overdue.json()["overdue_evidence"] == 1
    await captures.clean_up(world.factory, storage)
    spot, screen = await stored(world, exam.id)
    assert screen.deleted_at is not None
    link = storage.signed_url("evidence", screen.storage_key, 60)
    assert httpx.get(link).status_code == 404
