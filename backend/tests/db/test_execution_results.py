"""Grading execution results in app-worker (TCK-0806): compare, score, save with weights, count
the right submission, move grading on. A result that arrives twice changes nothing."""

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import ExamAttempt
from app.db.session import SessionFactory, create_session_factory, system_session, tenant_session
from app.exams.models import Exam
from app.execution.models import CodeRun, CodingEvaluation, CodingSubmission, TestCaseResult
from app.execution.results import handle
from app.main import create_app
from app.questions.models import CodingConfig
from app.users.models import User
from cli import commands
from tests.db.api_helpers import make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_start_attempt_api import bearer
from workers.exec_messages import CaseResult, ExecResult, StepResult

WEIGHTS = [1, 1, 2, 2, 2, 2, 3, 3]  # the PRD's worked example: W = 16
EXPECTED = [f"out {i}" for i in range(1, 9)]


@dataclass
class World:
    factory: SessionFactory
    attempt_id: uuid.UUID
    exam_question_id: uuid.UUID
    institution_id: uuid.UUID
    me: dict[str, str] = field(default_factory=dict)  # the student's auth header
    essay_id: uuid.UUID | None = None
    teacher: dict[str, str] = field(default_factory=dict)  # the exam owner's auth header

    async def submission(self, no: int, points: str = "10") -> uuid.UUID:
        """A submission and its queued evaluation (the job); returns the evaluation id."""
        async with tenant_session(self.factory, self.institution_id) as s:
            sub = CodingSubmission(
                attempt_id=self.attempt_id,
                exam_question_id=self.exam_question_id,
                submission_no=no,
                language_key="python312",
                source="print()",
            )
            s.add(sub)
            await s.flush()
            evaluation = CodingEvaluation(submission_id=sub.id, max_score=Decimal(points))
            s.add(evaluation)
            await s.commit()
            return evaluation.id

    async def rows(self, model: Any, **where: Any) -> list[Any]:
        async with system_session(self.factory) as s:
            query = select(model).filter_by(**where)
            return list(await s.scalars(query))


def step(stdout: str, **flags: Any) -> dict[str, Any]:
    values = {
        "exit_code": 0,
        "stdout": stdout,
        "stderr": "",
        "time_ms": 5,
        "timed_out": False,
        "memory_exceeded": False,
        "output_exceeded": False,
    }
    return values | flags


def result(job: uuid.UUID, outputs: list[dict[str, Any]], **extra: Any) -> ExecResult:
    values: dict[str, Any] = {
        "job_id": str(job),
        "kind": "submit",
        "status": "COMPLETED",
        "image_digest": "sha256:abc",
        "compile": None,
        "cases": [CaseResult(name=f"{i:03d}", **o) for i, o in enumerate(outputs, start=1)],
    } | extra
    return ExecResult(**values)


def all_but_last_two() -> list[dict[str, Any]]:
    outputs = [step(e + "\n") for e in EXPECTED]  # TRIM ignores the newline
    outputs[6] = step("wrong")
    outputs[7] = step("", timed_out=True, exit_code=None)
    return outputs


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


async def build(app_engine: AsyncEngine, client: TestClient, counted: str) -> tuple[World, Any]:
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(factory, f"Grading test {uuid.uuid4().hex[:8]}")
    async with tenant_session(factory, college.id) as s:
        teacher = User(email=f"t{uuid.uuid4().hex[:8]}@abc.edu", full_name="T", role="TEACHER")
        student = User(email=f"s{uuid.uuid4().hex[:8]}@abc.edu", full_name="S", role="STUDENT")
        s.add_all([teacher, student])
        await s.commit()
    t, me = bearer(teacher, college), bearer(student, college)
    q = client.post(
        "/api/v1/questions",
        json={"type": "CODING", "body": "Echo.", "points": "10"},
        headers=t,
    ).json()["id"]
    url = f"/api/v1/questions/{q}"
    client.put(
        f"{url}/coding", json={"allowed_languages": [{"language_key": "python312"}]}, headers=t
    )
    for i, (weight, expected) in enumerate(zip(WEIGHTS, EXPECTED, strict=True)):
        visibility = "PUBLIC" if i == 0 else "HIDDEN"
        body = {
            "input": f"in {i + 1}",
            "expected_output": expected,
            "weight": weight,
            "visibility": visibility,
        }
        client.post(f"{url}/test-cases", json=body, headers=t).raise_for_status()
    essay = client.post(
        "/api/v1/questions",
        json={"type": "DESCRIPTIVE", "body": "Explain.", "points": "5", "rubric": "x"},
        headers=t,
    ).json()["id"]
    async with tenant_session(factory, college.id) as s:
        await s.execute(update(CodingConfig).values(validation_status="PASSED"))
        await s.commit()
    soon = datetime.now(UTC) + timedelta(days=1)
    exam = client.post(
        "/api/v1/exams",
        json={
            "title": "Grading",
            "open_at": soon.isoformat(),
            "close_at": (soon + timedelta(hours=2)).isoformat(),
            "duration_min": 60,
            "counted_submission": counted,
        },
        headers=t,
    ).json()
    e = f"/api/v1/exams/{exam['id']}"
    client.put(
        f"{e}/questions",
        json={"questions": [{"question_id": q}, {"question_id": essay}]},
        headers=t,
    )
    client.post(f"{e}/assignments", json={"student_ids": [str(student.id)]}, headers=t)
    assert client.post(f"{e}/publish", headers=t).status_code == 200
    async with tenant_session(factory, college.id) as s:
        now = datetime.now(UTC)
        await s.execute(update(Exam).values(open_at=now - timedelta(hours=1)))
        await s.commit()
    attempt = client.post(f"/api/v1/student/exams/{exam['id']}/attempts", headers=me).json()
    coding = next(i for i in attempt["questions"] if i["question"]["type"] == "CODING")
    essay_item = next(i for i in attempt["questions"] if i["question"]["type"] == "DESCRIPTIVE")
    world = World(
        factory,
        uuid.UUID(attempt["id"]),
        uuid.UUID(coding["exam_question_id"]),
        college.id,
        me,
        uuid.UUID(essay_item["exam_question_id"]),
        t,
    )
    return world, college


@pytest.fixture
async def world(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, client: TestClient
) -> AsyncIterator[World]:
    w, college = await build(app_engine, client, "BEST")
    yield w
    await purge_institutions(migrator_engine, [college.id])


async def test_scored_with_weights_and_repeats_are_harmless(world: World) -> None:
    job = await world.submission(1)
    message = result(job, all_but_last_two())
    assert await handle(world.factory, message) == "evaluated"
    assert await handle(world.factory, message) == "ignored"  # delivered twice: no change

    (evaluation,) = await world.rows(CodingEvaluation, id=job)
    assert (evaluation.status, evaluation.verdict) == ("DONE", "PARTIAL")
    assert (evaluation.score, evaluation.max_score) == (Decimal("6.25"), Decimal("10.00"))
    assert (evaluation.passed_weight, evaluation.total_weight) == (10, 16)
    assert evaluation.image_digest == "sha256:abc"
    cases = await world.rows(TestCaseResult, evaluation_id=job)
    assert len(cases) == 8 and sum(c.weight for c in cases) == 16
    assert sorted(c.outcome for c in cases).count("PASSED") == 6
    assert {c.outcome for c in cases if c.weight == 3} == {"WRONG_ANSWER", "TIME_LIMIT_EXCEEDED"}
    (submission,) = await world.rows(CodingSubmission, attempt_id=world.attempt_id)
    assert submission.status == "EVALUATED" and submission.is_counted


async def test_platform_failure_is_no_score_never_zero(world: World) -> None:
    job = await world.submission(1)
    failed = result(job, [], status="FAILED", error="bundle hash mismatch")
    assert await handle(world.factory, failed) == "failed"
    (evaluation,) = await world.rows(CodingEvaluation, id=job)
    assert (evaluation.status, evaluation.verdict, evaluation.score) == (
        "FAILED",
        "INTERNAL_ERROR",
        None,
    )
    (submission,) = await world.rows(CodingSubmission, attempt_id=world.attempt_id)
    assert submission.status == "FAILED" and not submission.is_counted

    # Results that don't match the question's test cases are the platform's fault too.
    job = await world.submission(2)
    assert await handle(world.factory, result(job, [step("out 1")])) == "failed"


async def test_compile_error_scores_zero_without_running(world: World) -> None:
    job = await world.submission(1)
    compile_failed = StepResult(**step("", exit_code=1, stderr="main.py: SyntaxError"))
    assert await handle(world.factory, result(job, [], compile=compile_failed)) == "evaluated"
    (evaluation,) = await world.rows(CodingEvaluation, id=job)
    assert (evaluation.verdict, evaluation.score, evaluation.total_weight) == (
        "COMPILE_ERROR",
        Decimal("0.00"),
        16,
    )
    assert "SyntaxError" in (evaluation.compile_output or "")
    assert await world.rows(TestCaseResult, evaluation_id=job) == []


async def test_best_submission_counts(world: World) -> None:
    first = await world.submission(1)
    await handle(world.factory, result(first, all_but_last_two()))  # 6.25
    second = await world.submission(2)
    await handle(world.factory, result(second, [step(e) for e in EXPECTED]))  # 10
    third = await world.submission(3)
    await handle(world.factory, result(third, [step("nope")] * 8))  # 0
    counted = {
        s.submission_no: s.is_counted
        for s in await world.rows(CodingSubmission, attempt_id=world.attempt_id)
    }
    assert counted == {1: False, 2: True, 3: False}


async def test_last_submission_counts_when_the_exam_says_so(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, client: TestClient
) -> None:
    w, college = await build(app_engine, client, "LAST")
    try:
        await handle(w.factory, result(await w.submission(1), [step(e) for e in EXPECTED]))
        await handle(w.factory, result(await w.submission(2), all_but_last_two()))
        counted = {
            s.submission_no: s.is_counted
            for s in await w.rows(CodingSubmission, attempt_id=w.attempt_id)
        }
        assert counted == {1: False, 2: True}
    finally:
        await purge_institutions(migrator_engine, [college.id])


async def test_grading_moves_on_when_no_code_is_waiting(world: World) -> None:
    first, second = await world.submission(1), await world.submission(2)
    async with system_session(world.factory) as s:
        await s.execute(
            update(ExamAttempt)
            .where(ExamAttempt.id == world.attempt_id)
            .values(status="SUBMITTED", submitted_at=func.now(), grading_status="AWAITING_CODING")
        )
        await s.commit()

    async def status() -> str:
        (attempt,) = await world.rows(ExamAttempt, id=world.attempt_id)
        return str(attempt.grading_status)

    await handle(world.factory, result(first, all_but_last_two()))
    assert await status() == "AWAITING_CODING"  # the second is still queued
    await handle(world.factory, result(second, [], status="FAILED"))
    assert await status() == "AWAITING_MANUAL"  # the exam has a descriptive question


async def test_run_code_keeps_public_cases_only(world: World) -> None:
    async with tenant_session(world.factory, world.institution_id) as s:
        run = CodeRun(
            attempt_id=world.attempt_id,
            exam_question_id=world.exam_question_id,
            language_key="python312",
            source="print()",
        )
        custom = CodeRun(
            attempt_id=world.attempt_id,
            exam_question_id=world.exam_question_id,
            language_key="python312",
            source="print()",
            custom_input="my input",
        )
        s.add_all([run, custom])
        await s.commit()
    # A run of case 002 (hidden) must never be reported, even if it shows up in the result.
    message = result(run.id, [step("out 1"), step("out 2")], kind="run")
    assert await handle(world.factory, message) == "run"
    assert await handle(world.factory, message) == "ignored"
    (saved,) = await world.rows(CodeRun, id=run.id)
    assert saved.status == "COMPLETED"
    assert [(r["name"], r["input"], r["expected_output"], r["passed"]) for r in saved.results] == [
        ("001", "in 1", "out 1", True)
    ]
    custom_result = ExecResult(
        job_id=str(custom.id),
        kind="run",
        status="COMPLETED",
        cases=[CaseResult(name="custom", **step("echo: my input"))],
    )
    await handle(world.factory, custom_result)
    (saved,) = await world.rows(CodeRun, id=custom.id)
    assert saved.results == [
        {
            "name": "custom",
            "input": "my input",
            "expected_output": None,
            "stdout": "echo: my input",
            "stderr": "",
            "outcome": None,
            "passed": None,
            "time_ms": 5,
            "timed_out": False,
        }
    ]


async def test_unknown_or_validation_jobs_are_ignored(world: World) -> None:
    assert await handle(world.factory, result(uuid.uuid4(), [])) == "ignored"
    assert await handle(world.factory, result(uuid.uuid4(), [], kind="validation")) == "ignored"
