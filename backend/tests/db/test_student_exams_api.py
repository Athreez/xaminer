"""The student's exam list and detail through the real HTTP API (PRD ATT-01)."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import ExamAttempt
from app.auth.tokens import Principal, create_access_token
from app.db.session import SessionFactory, create_session_factory, tenant_session
from app.exams.models import Exam
from app.main import create_app
from app.platform.models import Institution
from app.users.models import User
from cli import commands
from tests.db.api_helpers import SECRET, make_settings
from tests.db.question_helpers import purge_institutions

NOW = datetime.now(UTC)
URL = "/api/v1/student/exams"


def bearer(user: User, institution: Institution) -> dict[str, str]:
    token = create_access_token(Principal(user.id, institution.id, user.role), SECRET, 15)
    return {"Authorization": f"Bearer {token}"}


@dataclass
class World:
    client: TestClient
    factory: SessionFactory
    college: Institution
    teacher: dict[str, str]
    student: User
    me: dict[str, str]
    question_id: str

    def exam(
        self,
        title: str,
        opens: timedelta,
        closes: timedelta,
        *,
        assign: bool = True,
        publish: bool = True,
    ) -> str:
        """An exam built and published through the API, then moved to the given window."""
        future = NOW + timedelta(days=5)
        exam = self.client.post(
            "/api/v1/exams",
            json={
                "title": title,
                "open_at": future.isoformat(),
                "close_at": (future + timedelta(hours=3)).isoformat(),
                "duration_min": 60,
                "instructions": "Answer **all** questions.",
            },
            headers=self.teacher,
        ).json()
        url = f"/api/v1/exams/{exam['id']}"
        self.client.put(
            f"{url}/questions",
            json={"questions": [{"question_id": self.question_id}]},
            headers=self.teacher,
        )
        if assign:
            self.client.post(
                f"{url}/assignments",
                json={"student_ids": [str(self.student.id)]},
                headers=self.teacher,
            )
        else:  # publishing needs someone assigned
            other = self.client.get(f"{url}/student-choices", headers=self.teacher).json()
            ids = [s["id"] for s in other if s["id"] != str(self.student.id)]
            self.client.post(
                f"{url}/assignments", json={"student_ids": ids[:1]}, headers=self.teacher
            )
        if publish:
            response = self.client.post(f"{url}/publish", headers=self.teacher)
            assert response.status_code == 200, response.text
        return exam["id"]  # type: ignore[no-any-return]

    async def move(self, exam_id: str, opens: timedelta, closes: timedelta, **values: Any) -> None:
        async with tenant_session(self.factory, self.college.id) as s:
            await s.execute(
                update(Exam)
                .where(Exam.id == uuid.UUID(exam_id))
                .values(open_at=NOW + opens, close_at=NOW + closes, **values)
            )
            await s.commit()

    async def attempt(self, exam_id: str, **values: Any) -> None:
        async with tenant_session(self.factory, self.college.id) as s:
            exam = await s.get(Exam, uuid.UUID(exam_id))
            assert exam is not None and exam.published_version_id is not None
            s.add(
                ExamAttempt(
                    exam_id=exam.id,
                    exam_version_id=exam.published_version_id,
                    student_id=self.student.id,
                    started_at=NOW - timedelta(minutes=10),
                    deadline_at=NOW + timedelta(minutes=50),
                    shuffle_seed=1,
                    **values,
                )
            )
            await s.commit()


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(
        factory, f"Student exams test {uuid.uuid4().hex[:8]}"
    )
    async with tenant_session(factory, college.id) as s:
        teacher = User(
            email=f"t{uuid.uuid4().hex[:8]}@abc.edu", full_name="Tara Teacher", role="TEACHER"
        )
        student = User(email=f"s{uuid.uuid4().hex[:8]}@abc.edu", full_name="Sam", role="STUDENT")
        other = User(email=f"o{uuid.uuid4().hex[:8]}@abc.edu", full_name="Other", role="STUDENT")
        s.add_all([teacher, student, other])
        await s.commit()
    with TestClient(create_app(make_settings())) as client:
        t = bearer(teacher, college)
        q = client.post(
            "/api/v1/questions",
            json={"type": "DESCRIPTIVE", "body": "Explain recursion", "points": "5", "rubric": "x"},
            headers=t,
        ).json()["id"]
        yield World(client, factory, college, t, student, bearer(student, college), q)
    await purge_institutions(migrator_engine, [college.id])


async def test_sections_and_states(world: World) -> None:
    hour, day = timedelta(hours=1), timedelta(days=1)
    open_now = world.exam("Open now", -hour, 2 * hour)
    await world.move(open_now, -hour, 2 * hour)
    upcoming = world.exam("Tomorrow", day, day + 3 * hour)
    await world.move(upcoming, day, day + 3 * hour)
    missed = world.exam("Missed", -3 * hour, -hour)
    await world.move(missed, -3 * hour, -hour)
    too_late = world.exam("Closing", -hour, timedelta(minutes=3))
    await world.move(too_late, -hour, timedelta(minutes=3))
    resume = world.exam("Resume me", -hour, 2 * hour)
    await world.move(resume, -hour, 2 * hour)
    await world.attempt(resume)
    done = world.exam("Done", -hour, 2 * hour)
    await world.move(done, -hour, 2 * hour)
    await world.attempt(done, status="SUBMITTED", submitted_at=NOW)
    world.exam("Draft", -hour, 2 * hour, publish=False)  # never shown
    world.exam("Someone else's", -hour, 2 * hour, assign=False)  # never shown

    response = world.client.get(URL, headers=world.me)
    assert response.status_code == 200, response.text
    body = response.json()

    def states(section: str) -> dict[str, str]:
        return {e["title"]: e["state"] for e in body[section]}

    assert states("available") == {
        "Open now": "AVAILABLE",
        "Closing": "TOO_LATE",
        "Resume me": "IN_PROGRESS",
    }
    assert states("upcoming") == {"Tomorrow": "UPCOMING"}
    assert states("completed") == {"Missed": "MISSED", "Done": "SUBMITTED"}
    card = next(e for e in body["available"] if e["title"] == "Open now")
    assert card["teacher_name"] == "Tara Teacher" and card["question_count"] == 1
    assert card["duration_min"] == 60 and card["attempt"] is None
    resumed = next(e for e in body["available"] if e["title"] == "Resume me")
    assert resumed["attempt"]["status"] == "IN_PROGRESS"


async def test_archived_exams_stay_only_if_taken(world: World) -> None:
    hour = timedelta(hours=1)
    taken = world.exam("Taken then archived", -hour, 2 * hour)
    await world.move(taken, -3 * hour, -hour, status="ARCHIVED")
    await world.attempt(taken, status="SUBMITTED", submitted_at=NOW)
    untaken = world.exam("Archived, not taken", -hour, 2 * hour)
    await world.move(untaken, -3 * hour, -hour, status="ARCHIVED")
    body = world.client.get(URL, headers=world.me).json()
    assert [e["title"] for e in body["completed"]] == ["Taken then archived"]


async def test_a_voided_attempt_lets_the_student_start_again(world: World) -> None:
    hour = timedelta(hours=1)
    exam = world.exam("Voided", -hour, 2 * hour)
    await world.move(exam, -hour, 2 * hour)
    await world.attempt(exam, status="VOIDED")
    (card,) = world.client.get(URL, headers=world.me).json()["available"]
    assert card["state"] == "AVAILABLE" and card["attempt"] is None


async def test_detail(world: World) -> None:
    hour = timedelta(hours=1)
    exam = world.exam("Mid-term", -hour, 2 * hour)
    await world.move(exam, -hour, 2 * hour)
    response = world.client.get(f"{URL}/{exam}", headers=world.me)
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["instructions"] == "Answer **all** questions."
    assert detail["navigation_mode"] == "FREE" and detail["run_code_enabled"] is True
    assert detail["has_coding"] is False and detail["total_points"] == "5.00"
    assert detail["state"] == "AVAILABLE"
    assert abs(datetime.fromisoformat(detail["server_time"]) - datetime.now(UTC)) < timedelta(
        seconds=30
    )
    assert "rubric" not in response.text and "is_correct" not in response.text

    draft = world.exam("Draft", -hour, 2 * hour, publish=False)
    unassigned = world.exam("Not mine", -hour, 2 * hour, assign=False)
    for hidden in (draft, unassigned, str(uuid.uuid4())):
        assert world.client.get(f"{URL}/{hidden}", headers=world.me).status_code == 404


async def test_who_can_call_it(world: World) -> None:
    assert world.client.get(URL, headers=world.teacher).json() == {
        "available": [],
        "upcoming": [],
        "completed": [],
    }  # a teacher has no assignments
    async with tenant_session(world.factory, world.college.id) as s:
        admin = User(email=f"a{uuid.uuid4().hex[:8]}@abc.edu", full_name="A", role="ADMIN")
        s.add(admin)
        await s.commit()
    assert world.client.get(URL, headers=bearer(admin, world.college)).status_code == 403
    assert world.client.get(URL).status_code == 401
