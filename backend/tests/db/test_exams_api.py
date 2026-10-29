"""Exams through the real HTTP API (PRD EX-01, EX-03, EX-06, EX-08; settings PRD § 6.3)."""

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.audit.models import AuditLog
from app.auth.tokens import Principal, create_access_token
from app.db.session import SessionFactory, create_session_factory, tenant_session
from app.exams.models import Exam, ExamQuestion, ExamVersion
from app.main import create_app
from app.platform.models import Institution
from app.questions.models import Question, QuestionVersion
from app.users.models import User
from cli import commands
from tests.db.api_helpers import SECRET, make_settings
from tests.db.question_helpers import purge_institutions

URL = "/api/v1/exams"
SOON = datetime.now(UTC).replace(microsecond=0) + timedelta(days=2)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@dataclass
class World:
    factory: SessionFactory
    college: Institution
    ids: list[uuid.UUID]

    async def user(
        self, role: str = "TEACHER", college: Institution | None = None
    ) -> tuple[User, dict[str, str]]:
        college = college or self.college
        async with tenant_session(self.factory, college.id) as s:
            user = User(
                email=f"u{uuid.uuid4().hex[:8]}@abc.edu", full_name=f"{role.title()} X", role=role
            )
            s.add(user)
            await s.commit()
        token = create_access_token(Principal(user.id, college.id, role), SECRET, 15)
        return user, {"Authorization": f"Bearer {token}"}

    async def audit(self, action: str) -> list[AuditLog]:
        async with tenant_session(self.factory, self.college.id) as s:
            return list(await s.scalars(select(AuditLog).where(AuditLog.action == action)))

    async def publish(self, exam_id: str) -> None:
        """Stand-in for the publish step (TCK-0506): a frozen version and the status."""
        async with tenant_session(self.factory, self.college.id) as s:
            version = ExamVersion(
                exam_id=uuid.UUID(exam_id), version_no=1, snapshot={}, content_hash="0" * 64
            )
            s.add(version)
            await s.flush()
            await s.execute(
                update(Exam)
                .where(Exam.id == uuid.UUID(exam_id))
                .values(status="PUBLISHED", published_version_id=version.id)
            )
            await s.commit()


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(factory, f"Exams API test {uuid.uuid4().hex[:8]}")
    w = World(factory, college, [college.id])
    yield w
    await purge_institutions(migrator_engine, w.ids)


def create(client: TestClient, headers: dict[str, str], **body: Any) -> dict[str, Any]:
    response = client.post(URL, json={"title": "Mid-term", **body}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


async def test_only_teachers_manage_exams(client: TestClient, world: World) -> None:
    for role in ("ADMIN", "STUDENT"):
        _, headers = await world.user(role)
        assert client.get(URL, headers=headers).status_code == 403
        assert client.post(URL, json={"title": "x"}, headers=headers).status_code == 403


async def test_create_with_defaults(client: TestClient, world: World) -> None:
    _, me = await world.user()
    exam = create(client, me)
    assert exam["status"] == "DRAFT" and exam["title"] == "Mid-term"
    assert (exam["navigation_mode"], exam["release_policy"], exam["counted_submission"]) == (
        "FREE",
        "MANUAL",
        "BEST",
    )
    assert exam["shuffle_questions"] is False and exam["run_code_enabled"] is True
    assert exam["proctoring_mode"] == "OFF"
    assert exam["proctoring_detectors"] == {
        "sensitivity": "STANDARD",
        "gaze": False,
        "books": False,
    }
    assert exam["open_at"] is None and exam["duration_min"] is None and exam["consent_text"] is None
    assert (exam["question_count"], exam["total_points"], exam["assigned_count"]) == (0, "0", 0)
    assert len(await world.audit("exam.created")) == 1


async def test_create_with_settings(client: TestClient, world: World) -> None:
    _, me = await world.user()
    exam = create(
        client,
        me,
        instructions="Read **carefully**. <script>alert(1)</script>",
        open_at=SOON.isoformat(),
        close_at=(SOON + timedelta(hours=3)).isoformat(),
        duration_min=90,
        navigation_mode="SEQUENTIAL",
        pass_percent="40",
        proctoring_mode="VIDEO_AUDIO",
        proctoring_detectors={"sensitivity": "STRICT", "gaze": True, "books": False},
        consent_text="We record your webcam and microphone.",
    )
    assert exam["instructions"] == "Read **carefully**."  # Markdown cleaned like questions
    assert exam["duration_min"] == 90 and exam["pass_percent"] == "40.00"
    assert exam["proctoring_detectors"]["sensitivity"] == "STRICT"
    assert datetime.fromisoformat(exam["open_at"]) == SOON


@pytest.mark.parametrize(
    "body",
    [
        {"title": "   "},
        {"duration_min": 0},
        {"duration_min": 601},
        {"pass_percent": "101"},
        {"navigation_mode": "RANDOM"},
        {"proctoring_detectors": {"sensitivity": "PARANOID"}},
        {"proctoring_detectors": {"faces": False}},
        {"open_at": "2026-11-01T10:00:00"},  # no time zone
        {"open_at": SOON.isoformat(), "close_at": (SOON - timedelta(minutes=1)).isoformat()},
        {"status": "PUBLISHED"},  # status changes only through publish / archive
    ],
    ids=[
        "blank-title",
        "zero-minutes",
        "too-long",
        "pass-over-100",
        "bad-navigation",
        "bad-sensitivity",
        "unknown-detector",
        "naive-time",
        "close-before-open",
        "status",
    ],
)
async def test_bad_settings_are_rejected(
    client: TestClient, world: World, body: dict[str, Any]
) -> None:
    _, me = await world.user()
    response = client.post(URL, json={"title": "Mid-term", **body}, headers=me)
    assert response.status_code == 422, response.text


async def test_edit_a_draft(client: TestClient, world: World) -> None:
    _, me = await world.user()
    exam = create(client, me, open_at=SOON.isoformat())
    url = f"{URL}/{exam['id']}"
    changed = client.patch(
        url, json={"title": "Final", "duration_min": 60, "shuffle_options": True}, headers=me
    )
    assert changed.status_code == 200, changed.text
    assert (changed.json()["title"], changed.json()["duration_min"]) == ("Final", 60)
    (row,) = await world.audit("exam.updated")
    assert row.changes is not None and row.changes["title"] == {"old": "Mid-term", "new": "Final"}

    cleared = client.patch(url, json={"duration_min": None}, headers=me).json()
    assert cleared["duration_min"] is None
    clash = client.patch(
        url, json={"close_at": (SOON - timedelta(hours=1)).isoformat()}, headers=me
    )
    assert clash.status_code == 422 and clash.json()["error"]["details"][0]["field"] == "close_at"
    assert client.patch(url, json={}, headers=me).status_code == 200
    assert len(await world.audit("exam.updated")) == 2  # nothing changed: no new entry


async def test_published_exam_only_changes_its_window_end(client: TestClient, world: World) -> None:
    _, me = await world.user()
    exam = create(
        client, me, open_at=SOON.isoformat(), close_at=(SOON + timedelta(hours=2)).isoformat()
    )
    url = f"{URL}/{exam['id']}"
    await world.publish(exam["id"])

    refused = client.patch(url, json={"duration_min": 30}, headers=me)
    assert refused.status_code == 409
    error = refused.json()["error"]
    assert error["code"] == "EXAM_PUBLISHED" and error["details"][0]["field"] == "duration_min"

    later = (SOON + timedelta(hours=5)).isoformat()
    extended = client.patch(url, json={"close_at": later}, headers=me)
    assert extended.status_code == 200 and extended.json()["published_version_no"] == 1
    past = client.patch(
        url, json={"close_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}, headers=me
    )
    assert past.status_code == 422
    same = client.patch(url, json={"title": "Mid-term"}, headers=me)  # unchanged value: fine
    assert same.status_code == 200

    assert client.delete(url, headers=me).status_code == 409  # archive instead
    archived = client.post(f"{url}/archive", headers=me)
    assert archived.status_code == 200 and archived.json()["status"] == "ARCHIVED"
    frozen = client.patch(url, json={"close_at": later}, headers=me)
    assert frozen.status_code == 409 and frozen.json()["error"]["code"] == "EXAM_ARCHIVED"


async def test_delete_a_draft(client: TestClient, world: World) -> None:
    _, me = await world.user()
    exam = create(client, me)
    assert client.delete(f"{URL}/{exam['id']}", headers=me).status_code == 204
    assert client.get(f"{URL}/{exam['id']}", headers=me).status_code == 404
    assert len(await world.audit("exam.deleted")) == 1


async def test_counts_and_total_points(client: TestClient, world: World) -> None:
    teacher, me = await world.user()
    exam = create(client, me)
    async with tenant_session(world.factory, world.college.id) as s:
        for i, (own, override) in enumerate([(2, None), (3, 5)]):
            q = Question(owner_id=teacher.id, type="DESCRIPTIVE")
            s.add(q)
            await s.flush()
            v = QuestionVersion(
                question_id=q.id, version_no=1, body="Q", points=own, created_by=teacher.id
            )
            s.add(v)
            await s.flush()
            q.current_version_id = v.id
            s.add(
                ExamQuestion(
                    exam_id=uuid.UUID(exam["id"]), question_id=q.id, order_index=i, points=override
                )
            )
        await s.commit()
    fresh = client.get(f"{URL}/{exam['id']}", headers=me).json()
    assert fresh["question_count"] == 2 and fresh["total_points"] == "7.00"  # 2 + the exam's own 5


async def test_lists(client: TestClient, world: World) -> None:
    _, me = await world.user()
    _, other = await world.user()
    first = create(client, me, title="Data Structures quiz")
    second = create(client, me, title="Algorithms final")
    create(client, other, title="Colleague's exam")
    await world.publish(second["id"])

    def ids(headers: dict[str, str], **params: str) -> list[str]:
        response = client.get(URL, params=params, headers=headers)
        assert response.status_code == 200, response.text
        return [e["id"] for e in response.json()["data"]]

    assert ids(me) == [second["id"], first["id"]]  # only mine, newest first
    assert ids(me, status="DRAFT") == [first["id"]]
    assert ids(me, q="structures") == [first["id"]]

    _, admin = await world.user("ADMIN")
    listed = client.get("/api/v1/admin/exams", headers=admin).json()["data"]
    assert len(listed) == 3
    entry = next(e for e in listed if e["id"] == second["id"])
    assert entry["owner_name"] == "Teacher X" and entry["status"] == "PUBLISHED"
    assert set(entry) == {
        "id",
        "title",
        "owner_name",
        "status",
        "open_at",
        "close_at",
        "duration_min",
        "assigned_count",
    }  # metadata only

    _, student = await world.user("STUDENT")
    assert client.get("/api/v1/admin/exams", headers=student).status_code == 403
    assert client.get("/api/v1/admin/exams", headers=me).status_code == 403
    outsider_college = await commands.create_institution(
        world.factory, f"Exams API test {uuid.uuid4().hex[:8]}"
    )
    world.ids.append(outsider_college.id)
    _, outsider_admin = await world.user("ADMIN", outsider_college)
    assert client.get("/api/v1/admin/exams", headers=outsider_admin).json()["data"] == []
