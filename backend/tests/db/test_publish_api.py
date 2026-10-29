"""Publishing through the real HTTP API (PRD EX-05, EX-06)."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.tokens import Principal, create_access_token
from app.db.session import SessionFactory, create_session_factory, tenant_session
from app.exams.models import ExamQuestion, ExamVersion
from app.exams.publish import content_hash
from app.main import create_app
from app.platform.models import Institution
from app.questions.models import QuestionVersion
from app.users.models import User
from cli import commands
from tests.db.api_helpers import SECRET, make_settings
from tests.db.question_helpers import purge_institutions

START = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)


@dataclass
class Setup:
    client: TestClient
    factory: SessionFactory
    college: Institution
    me: dict[str, str]
    exam_id: str
    mcq_id: str
    essay_id: str
    student_id: str

    @property
    def url(self) -> str:
        return f"/api/v1/exams/{self.exam_id}"

    def publish(self):  # type: ignore[no-untyped-def]
        return self.client.post(f"{self.url}/publish", headers=self.me)

    async def version(self) -> ExamVersion:
        async with tenant_session(self.factory, self.college.id) as s:
            row = await s.scalar(
                select(ExamVersion).where(ExamVersion.exam_id == uuid.UUID(self.exam_id))
            )
            assert row is not None
            return row


@pytest.fixture
async def setup(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[Setup]:
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(factory, f"Publish test {uuid.uuid4().hex[:8]}")
    async with tenant_session(factory, college.id) as s:
        teacher = User(email=f"t{uuid.uuid4().hex[:8]}@abc.edu", full_name="T", role="TEACHER")
        student = User(email=f"s{uuid.uuid4().hex[:8]}@abc.edu", full_name="S", role="STUDENT")
        s.add_all([teacher, student])
        await s.commit()
    me = {
        "Authorization": "Bearer "
        + create_access_token(Principal(teacher.id, college.id, "TEACHER"), SECRET, 15)
    }
    with TestClient(create_app(make_settings())) as client:

        def question(body: dict[str, Any]) -> str:
            response = client.post("/api/v1/questions", json=body, headers=me)
            assert response.status_code == 201, response.text
            return response.json()["id"]  # type: ignore[no-any-return]

        mcq = question(
            {
                "type": "MCQ",
                "body": "Index of the first element?",
                "points": "2",
                "options": [
                    {"label": "0", "is_correct": True},
                    {"label": "1", "is_correct": False},
                ],
            }
        )
        essay = question(
            {
                "type": "DESCRIPTIVE",
                "body": "Explain recursion",
                "points": "5",
                "rubric": "Base case",
            }
        )
        exam = client.post(
            "/api/v1/exams",
            json={
                "title": "Mid-term",
                "open_at": START.isoformat(),
                "close_at": (START + timedelta(hours=3)).isoformat(),
                "duration_min": 60,
            },
            headers=me,
        ).json()
        url = f"/api/v1/exams/{exam['id']}"
        client.put(
            f"{url}/questions",
            json={"questions": [{"question_id": essay}, {"question_id": mcq, "points": "3"}]},
            headers=me,
        )
        client.post(f"{url}/assignments", json={"student_ids": [str(student.id)]}, headers=me)
        yield Setup(client, factory, college, me, exam["id"], mcq, essay, str(student.id))
    await purge_institutions(migrator_engine, [college.id])


async def test_blocked_until_the_check_passes(setup: Setup) -> None:
    setup.client.delete(f"{setup.url}/assignments/{setup.student_id}", headers=setup.me)
    setup.client.patch(setup.url, json={"duration_min": None}, headers=setup.me)
    refused = setup.publish()
    assert refused.status_code == 409
    error = refused.json()["error"]
    assert (
        error["code"] == "PUBLISH_BLOCKED"
        and error["message"] == "2 things need fixing before publishing."
    )
    assert [d["type"] for d in error["details"]] == ["NO_DURATION", "NO_STUDENTS"]
    assert setup.client.get(setup.url, headers=setup.me).json()["status"] == "DRAFT"


async def test_publish_freezes_the_exam(setup: Setup) -> None:
    published = setup.publish()
    assert published.status_code == 200, published.text
    assert (
        published.json()["status"] == "PUBLISHED" and published.json()["published_version_no"] == 1
    )

    version = await setup.version()
    snap = version.snapshot
    assert version.content_hash == content_hash(snap)
    assert snap["title"] == "Mid-term" and snap["settings"]["duration_min"] == 60
    assert snap["total_points"] == "8.00"  # 5 + the exam's own 3 for the MCQ
    assert [q["question_id"] for q in snap["questions"]] == [setup.essay_id, setup.mcq_id]
    essay, mcq = snap["questions"]
    assert essay["rubric"] == "Base case" and essay["points"] == "5.00"
    assert mcq["points"] == "3.00" and [o["is_correct"] for o in mcq["options"]] == [True, False]

    async with tenant_session(setup.factory, setup.college.id) as s:
        pinned = list(
            await s.scalars(
                select(ExamQuestion.pinned_version_id).where(
                    ExamQuestion.exam_id == uuid.UUID(setup.exam_id)
                )
            )
        )
        assert len(pinned) == 2 and None not in pinned
        locked = list(
            await s.scalars(select(QuestionVersion.is_locked).where(QuestionVersion.id.in_(pinned)))
        )
        assert locked == [True, True]


async def test_after_publishing(setup: Setup) -> None:
    setup.publish()
    me, url = setup.me, setup.url

    # Settings are fixed; the error names the field (acceptance for TCK-0506).
    refused = setup.client.patch(url, json={"duration_min": 45}, headers=me)
    assert refused.status_code == 409
    assert refused.json()["error"]["details"][0]["field"] == "duration_min"
    assert (
        setup.client.put(f"{url}/questions", json={"questions": []}, headers=me).status_code == 409
    )
    assert setup.publish().status_code == 409  # already published

    # The window's end and the assignments can still change.
    later = (START + timedelta(hours=6)).isoformat()
    assert setup.client.patch(url, json={"close_at": later}, headers=me).status_code == 200

    # Editing a question now makes version 2; the exam keeps version 1.
    edited = setup.client.patch(
        f"/api/v1/questions/{setup.mcq_id}", json={"points": "4"}, headers=me
    )
    assert edited.headers.get("X-New-Version") == "true"
    rows = setup.client.get(f"{url}/questions", headers=me).json()["questions"]
    assert [q["version_no"] for q in rows] == [1, 1]
    version = await setup.version()
    assert version.snapshot["questions"][1]["version_no"] == 1


async def test_institution_consent_is_copied_into_the_snapshot(setup: Setup) -> None:
    async with tenant_session(setup.factory, setup.college.id) as s:
        await s.execute(
            update(Institution)
            .where(Institution.id == setup.college.id)
            .values(default_consent_text="Standard notice.")
        )
        await s.commit()
    setup.client.patch(setup.url, json={"proctoring_mode": "VIDEO"}, headers=setup.me)
    assert setup.publish().status_code == 200
    assert (await setup.version()).snapshot["consent_text"] == "Standard notice."
