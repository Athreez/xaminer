"""Leak test: hidden test cases and reference solutions never reach a student (PRD CQ-05, NFR-02).

A coding question gets markers in its hidden test case and reference solution, then goes through
everything a student (or the teacher's student-view preview) can call. None of those responses may
contain a marker; the public example must be there.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory, tenant_session
from app.exams.models import Exam, ExamVersion
from app.main import create_app
from app.questions.models import CodingConfig
from app.users.models import User
from cli import commands
from tests.db.api_helpers import make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_start_attempt_api import bearer

HIDDEN = "HIDDEN-MARKER-7f3a"
REFERENCE = "REFERENCE-MARKER-91c2"
PUBLIC_IN, PUBLIC_OUT = "PUBLIC-EXAMPLE-IN", "PUBLIC-EXAMPLE-OUT"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def college(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator:  # type: ignore[type-arg]
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(factory, f"Leak test {uuid.uuid4().hex[:8]}")
    yield factory, college
    await purge_institutions(migrator_engine, [college.id])


async def test_hidden_cases_never_reach_a_student(client: TestClient, college) -> None:  # type: ignore[no-untyped-def]
    factory, inst = college
    async with tenant_session(factory, inst.id) as s:
        teacher = User(email=f"t{uuid.uuid4().hex[:8]}@abc.edu", full_name="T", role="TEACHER")
        student = User(email=f"s{uuid.uuid4().hex[:8]}@abc.edu", full_name="S", role="STUDENT")
        s.add_all([teacher, student])
        await s.commit()
    t, me = bearer(teacher, inst), bearer(student, inst)

    qid = client.post(
        "/api/v1/questions",
        json={"type": "CODING", "body": "Echo the input.", "points": "10"},
        headers=t,
    ).json()["id"]
    q = f"/api/v1/questions/{qid}"
    client.put(
        f"{q}/coding",
        json={"allowed_languages": [{"language_key": "python312", "starter_code": "# start"}]},
        headers=t,
    ).raise_for_status()
    client.post(
        f"{q}/test-cases",
        json={"visibility": "PUBLIC", "input": PUBLIC_IN, "expected_output": PUBLIC_OUT},
        headers=t,
    ).raise_for_status()
    client.post(
        f"{q}/test-cases",
        json={"input": f"{HIDDEN}-in", "expected_output": f"{HIDDEN}-out", "weight": 5},
        headers=t,
    ).raise_for_status()
    client.put(
        f"{q}/reference-solutions/python312", json={"source": f"print('{REFERENCE}')"}, headers=t
    ).raise_for_status()
    async with tenant_session(factory, inst.id) as s:  # validation arrives in TCK-0705
        await s.execute(update(CodingConfig).values(validation_status="PASSED"))
        await s.commit()

    soon = datetime.now(UTC) + timedelta(days=1)
    exam = client.post(
        "/api/v1/exams",
        json={
            "title": "Leak",
            "open_at": soon.isoformat(),
            "close_at": (soon + timedelta(hours=3)).isoformat(),
            "duration_min": 60,
        },
        headers=t,
    ).json()
    e = f"/api/v1/exams/{exam['id']}"
    client.put(
        f"{e}/questions", json={"questions": [{"question_id": qid}]}, headers=t
    ).raise_for_status()
    client.post(
        f"{e}/assignments", json={"student_ids": [str(student.id)]}, headers=t
    ).raise_for_status()
    published = client.post(f"{e}/publish", headers=t)
    assert published.status_code == 200, published.text
    async with tenant_session(factory, inst.id) as s:
        now = datetime.now(UTC)
        await s.execute(
            update(Exam).values(open_at=now - timedelta(hours=1), close_at=now + timedelta(hours=2))
        )
        await s.commit()
        snapshot = await s.scalar(select(ExamVersion.snapshot))

    seen: dict[str, str] = {}

    def call(name: str, method: str, url: str, headers: dict[str, str], **kwargs) -> dict:  # type: ignore[no-untyped-def,type-arg]
        response = client.request(method, url, headers=headers, **kwargs)
        assert response.status_code < 300, (name, response.text)
        seen[name] = response.text
        return response.json() if response.content else {}

    call("student exams", "GET", "/api/v1/student/exams", me)
    call("student exam detail", "GET", f"/api/v1/student/exams/{exam['id']}", me)
    started = call("start", "POST", f"/api/v1/student/exams/{exam['id']}/attempts", me)
    a = f"/api/v1/attempts/{started['id']}"
    resumed = call("resume", "GET", a, me)
    call("heartbeat", "POST", f"{a}/heartbeat", me, json={})
    eq = resumed["questions"][0]["exam_question_id"]
    call(
        "draft",
        "PUT",
        f"{a}/drafts/{eq}",
        me,
        json={"language_key": "python312", "source": "print(1)", "client_revision": 1},
    )
    call("teacher preview", "GET", f"{q}/preview", t)
    preview_attempt = call("preview attempt", "POST", f"{e}/preview-attempt", t)
    call("preview resume", "GET", f"/api/v1/attempts/{preview_attempt['id']}", t)
    call("submit", "POST", f"{a}/submit", me)
    call("receipt", "GET", f"{a}/receipt", me)

    for name, body in seen.items():
        assert HIDDEN not in body, f"hidden test case leaked in: {name}"
        assert REFERENCE not in body, f"reference solution leaked in: {name}"
    assert HIDDEN not in str(snapshot) and REFERENCE not in str(snapshot)  # not even stored

    coding = resumed["questions"][0]["question"]["coding"]
    assert coding["examples"] == [{"input": PUBLIC_IN, "expected_output": PUBLIC_OUT}]
    assert coding["languages"] == [
        {"key": "python312", "display_name": "Python 3.12", "starter_code": "# start"}
    ]
    assert coding["max_submissions"] == 10 and coding["run_code_allowed"] is True
    assert PUBLIC_IN in seen["teacher preview"]
