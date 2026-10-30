"""The publish check through the real HTTP API (PRD § 6.4). One test per block and warning:
each starts from an exam that can be published and breaks exactly one thing."""

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.tokens import Principal, create_access_token
from app.db.session import SessionFactory, create_session_factory, tenant_session
from app.exams.models import Exam, ExamVersion
from app.main import create_app
from app.platform.models import Institution
from app.users.models import User
from cli import commands
from tests.db.api_helpers import SECRET, make_settings
from tests.db.question_helpers import purge_institutions

START = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@dataclass
class Ready:
    """An exam that passes the check, and handles to break it."""

    client: TestClient
    factory: SessionFactory
    college: Institution
    me: dict[str, str]
    exam_id: str
    question_ids: list[str]
    student_id: str

    @property
    def url(self) -> str:
        return f"/api/v1/exams/{self.exam_id}"

    def patch(self, **body: Any) -> None:
        response = self.client.patch(self.url, json=body, headers=self.me)
        assert response.status_code == 200, response.text

    async def set_row(self, **values: Any) -> None:
        """Change the exam row directly, for states the API won't produce."""
        async with tenant_session(self.factory, self.college.id) as s:
            await s.execute(update(Exam).where(Exam.id == uuid.UUID(self.exam_id)).values(**values))
            await s.commit()

    def question(self, **body: Any) -> str:
        payload = {
            "type": "DESCRIPTIVE",
            "body": "Explain recursion",
            "points": "5",
            "rubric": "Base case",
        }
        response = self.client.post("/api/v1/questions", json=payload | body, headers=self.me)
        assert response.status_code == 201, response.text
        return response.json()["id"]  # type: ignore[no-any-return]

    def set_questions(self, ids: list[str]) -> None:
        response = self.client.put(
            f"{self.url}/questions",
            json={"questions": [{"question_id": q} for q in ids]},
            headers=self.me,
        )
        assert response.status_code == 200, response.text

    def result(self) -> dict[str, Any]:
        response = self.client.get(f"{self.url}/publish-check", headers=self.me)
        assert response.status_code == 200, response.text
        return response.json()  # type: ignore[no-any-return]

    def codes(self, kind: str = "blocks") -> list[str]:
        return [issue["code"] for issue in self.result()[kind]]


@pytest.fixture
async def ready(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[Ready]:
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(
        factory, f"Publish check test {uuid.uuid4().hex[:8]}"
    )
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
        r = Ready(client, factory, college, me, exam["id"], [], str(student.id))
        r.question_ids = [r.question(), r.question(body="Define a stack")]
        r.set_questions(r.question_ids)
        client.post(f"{r.url}/assignments", json={"student_ids": [r.student_id]}, headers=me)
        yield r
    await purge_institutions(migrator_engine, [college.id])


def test_a_complete_exam_can_be_published(ready: Ready) -> None:
    assert ready.result() == {"can_publish": True, "blocks": [], "warnings": []}


# ----------------------------------------------------------------------------- blocks


def test_no_questions(ready: Ready) -> None:
    ready.set_questions([])
    result = ready.result()
    assert result["can_publish"] is False
    assert [(b["code"], b["field"]) for b in result["blocks"]] == [("NO_QUESTIONS", "questions")]


def test_no_window(ready: Ready) -> None:
    ready.patch(open_at=None)
    (issue,) = ready.result()["blocks"]
    assert (issue["code"], issue["field"]) == ("NO_WINDOW", "open_at")


async def test_window_already_closed(ready: Ready) -> None:
    await ready.set_row(open_at=START - timedelta(days=3), close_at=START - timedelta(days=2))
    assert ready.codes() == ["WINDOW_IN_PAST"]


def test_no_duration(ready: Ready) -> None:
    ready.patch(duration_min=None)
    assert ready.codes() == ["NO_DURATION"]


def test_duration_longer_than_window(ready: Ready) -> None:
    ready.patch(duration_min=200)  # the window is 3 h = 180 min
    (issue,) = ready.result()["blocks"]
    assert issue["code"] == "DURATION_LONGER_THAN_WINDOW" and "200 min" in issue["message"]
    assert "180 min" in issue["message"] and issue["field"] == "duration_min"


def test_no_students(ready: Ready) -> None:
    ready.client.delete(f"{ready.url}/assignments/{ready.student_id}", headers=ready.me)
    assert ready.codes() == ["NO_STUDENTS"]


def test_coding_question_not_validated(ready: Ready) -> None:
    coding = ready.question(type="CODING", body="Reverse a linked list", rubric=None)
    ready.set_questions([*ready.question_ids, coding])
    (issue,) = ready.result()["blocks"]
    assert issue["code"] == "CODING_NOT_VALIDATED" and issue["question_id"] == coding
    assert issue["message"].startswith("Question 3 “Reverse a linked list”")


async def test_proctored_exam_without_text_gets_the_standard_consent(ready: Ready) -> None:
    ready.patch(proctoring_mode="VIDEO_AUDIO")
    assert ready.codes() == []  # no wording of its own: the standard text is used
    published = ready.client.post(f"{ready.url}/publish", headers=ready.me)
    assert published.status_code == 200, published.text
    async with tenant_session(ready.factory, ready.college.id) as s:
        exam = await s.get_one(Exam, uuid.UUID(ready.url.rsplit("/", 1)[1]))
        version = await s.get_one(ExamVersion, exam.published_version_id)
    consent = version.snapshot["consent_text"]
    assert "camera and microphone" in consent and "30 days" in consent


async def test_institution_default_consent_text_counts(ready: Ready) -> None:
    ready.patch(proctoring_mode="VIDEO_AUDIO")
    async with tenant_session(ready.factory, ready.college.id) as s:
        await s.execute(
            update(Institution)
            .where(Institution.id == ready.college.id)
            .values(default_consent_text="Our standard proctoring notice.")
        )
        await s.commit()
    assert ready.codes() == []


async def test_already_published(ready: Ready) -> None:
    await ready.set_row(status="PUBLISHED")
    assert ready.codes() == ["NOT_A_DRAFT"]


def test_several_blocks_are_all_listed(ready: Ready) -> None:
    ready.set_questions([])
    ready.patch(duration_min=None)
    ready.client.delete(f"{ready.url}/assignments/{ready.student_id}", headers=ready.me)
    assert ready.codes() == ["NO_QUESTIONS", "NO_DURATION", "NO_STUDENTS"]


# ----------------------------------------------------------------------------- warnings


def test_descriptive_without_rubric(ready: Ready) -> None:
    plain = ready.question(body="Compare BFS and DFS", rubric=None)
    ready.set_questions([*ready.question_ids, plain])
    result = ready.result()
    assert result["can_publish"] is True  # a warning never blocks
    (issue,) = result["warnings"]
    assert issue["code"] == "NO_RUBRIC" and issue["question_id"] == plain
    assert issue["message"] == "Question 3 “Compare BFS and DFS” has no rubric for graders."


def test_shuffle_with_sequential_navigation(ready: Ready) -> None:
    ready.patch(shuffle_questions=True, navigation_mode="SEQUENTIAL")
    assert ready.codes("warnings") == ["SHUFFLE_WITH_SEQUENTIAL"]


def test_very_short_duration(ready: Ready) -> None:
    ready.patch(duration_min=1)  # 1 minute for 2 questions
    (issue,) = ready.result()["warnings"]
    assert issue["code"] == "SHORT_DURATION" and "1 min for 2 questions" in issue["message"]
