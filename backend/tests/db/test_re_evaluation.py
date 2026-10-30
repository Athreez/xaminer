"""Re-evaluating a coding question (PRD EXE-09; TCK-0814): after a test case is fixed (a new
version), every submission runs again with it, scores change and a released result keeps a
revision with the reason."""

import uuid
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import ExamAttempt
from app.db.session import system_session
from app.execution.models import CodingEvaluation
from app.execution.results import handle
from app.grading.objective import grade
from app.main import create_app
from app.questions.models import CodingConfig, QuestionVersion, TestCase
from tests.db.api_helpers import S3_PORT, make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_execution_results import World, all_but_last_two, build, result
from tests.services import require


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def world(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, client: TestClient
) -> AsyncIterator[World]:
    require(S3_PORT, "Object storage")
    w, college = await build(app_engine, client, "BEST")
    yield w
    await purge_institutions(migrator_engine, [college.id])


async def released_with_two_failures(world: World, client: TestClient) -> str:
    """Graded 6.25 / 10 (cases 7 and 8 fail), submitted, and released. Returns the exam id."""
    await handle(world.factory, result(await world.submission(1), all_but_last_two()))
    submitted = client.post(f"/api/v1/attempts/{world.attempt_id}/submit", headers=world.me)
    assert submitted.status_code == 200, submitted.text
    await grade(world.factory, world.attempt_id)  # the blank essay scores 0: complete
    async with system_session(world.factory) as s:
        exam_id = str((await s.get_one(ExamAttempt, world.attempt_id)).exam_id)
    released = client.post(f"/api/v1/exams/{exam_id}/results/release", headers=world.teacher)
    assert released.status_code == 200, released.text
    return exam_id


async def fix_case_seven(world: World, client: TestClient, *, validated: bool) -> None:
    """The teacher decides "wrong" was right for case 7: a new version (the exam keeps v1)."""
    async with system_session(world.factory) as s:
        case = await s.scalar(
            select(TestCase).where(
                TestCase.expected_output == "out 7",
                TestCase.institution_id == world.institution_id,
            )
        )
        assert case is not None
        question_id = (await s.get_one(QuestionVersion, case.version_id)).question_id
    patched = client.patch(
        f"/api/v1/questions/{question_id}/test-cases/{case.id}",
        json={"expected_output": "wrong"},
        headers=world.teacher,
    )
    assert patched.status_code == 200, patched.text
    if validated:  # validation runs the reference on the exec-worker; here it's taken as passed
        async with system_session(world.factory) as s:
            await s.execute(
                update(CodingConfig)
                .where(
                    CodingConfig.validation_status == "NEEDS_VALIDATION",
                    CodingConfig.institution_id == world.institution_id,
                )
                .values(validation_status="PASSED")
            )
            await s.commit()


def re_evaluate(client: TestClient, world: World, exam_id: str, headers: Any = None):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/exams/{exam_id}/re-evaluate",
        json={"exam_question_id": str(world.exam_question_id), "reason": "Test 7 was wrong"},
        headers=headers or world.teacher,
    )


async def test_re_evaluation_regrades_and_records_a_revision(
    world: World, client: TestClient, no_exec_jobs: list[tuple[str, Any]]
) -> None:
    exam_id = await released_with_two_failures(world, client)
    await fix_case_seven(world, client, validated=True)
    sent_before = len(no_exec_jobs)

    response = re_evaluate(client, world, exam_id)
    assert response.status_code == 200, response.text
    assert response.json() == {"queued": 1, "version_no": 2}
    (_, job) = no_exec_jobs[sent_before]
    async with system_session(world.factory) as s:
        attempt = await s.get_one(ExamAttempt, world.attempt_id)
        assert attempt.grading_status == "AWAITING_CODING"
    assert re_evaluate(client, world, exam_id).status_code == 409  # still running

    # The same output again: case 7 now passes with the fixed expectation (13 of 16 weight).
    assert await handle(world.factory, result(uuid.UUID(job.job_id), all_but_last_two())) == (
        "evaluated"
    )
    async with system_session(world.factory) as s:
        evaluation = await s.get_one(CodingEvaluation, uuid.UUID(job.job_id))
        assert (evaluation.evaluation_no, evaluation.score) == (2, Decimal("8.13"))
        assert (await s.get_one(ExamAttempt, world.attempt_id)).grading_status == "COMPLETE"

    mine = client.get(f"/api/v1/student/results/{world.attempt_id}", headers=world.me).json()
    assert mine["total_score"] == "8.13"
    assert [(r["old_score"], r["new_score"], r["reason"]) for r in mine["revisions"]] == [
        ("6.25", "8.13", "Test 7 was wrong")
    ]
    history = client.get(
        f"/api/v1/attempts/{world.attempt_id}/questions/{world.exam_question_id}/submissions",
        headers=world.me,
    ).json()
    assert history["submissions"][0]["passed_cases"] == 7  # shown with the fixed cases


async def test_an_unvalidated_fix_or_a_student_is_refused(world: World, client: TestClient) -> None:
    exam_id = await released_with_two_failures(world, client)
    await fix_case_seven(world, client, validated=False)
    refused = re_evaluate(client, world, exam_id)
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "NOT_VALIDATED")
    assert re_evaluate(client, world, exam_id, headers=world.me).status_code == 403
