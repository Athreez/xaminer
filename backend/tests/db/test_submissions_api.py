"""Submit Code through the API (PRD EXE-04, EXE-05; TCK-0809): graded on every case, hidden
cases shown as pass/fail only, 5 s apart, never over the limit even when sent at once."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import ExamAttempt
from app.auth.tokens import Principal
from app.core.errors import AppError
from app.core.storage import Storage
from app.db.session import system_session, tenant_session
from app.execution.models import CodingSubmission
from app.execution.results import handle
from app.execution.submissions import SubmitIn, submit
from app.main import create_app
from app.platform.models import Institution
from app.users.models import User
from tests.db.api_helpers import S3_PORT, make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_execution_results import EXPECTED, World, all_but_last_two, build, result
from tests.db.test_start_attempt_api import bearer
from tests.services import require
from workers.exec_messages import ExecJob, StepResult

CODE = {"language_key": "python312", "source": "print(input().replace('in', 'out'))"}


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


def url(world: World) -> str:
    return f"/api/v1/attempts/{world.attempt_id}/questions/{world.exam_question_id}/submissions"


async def earlier(world: World, by: timedelta = timedelta(seconds=6)) -> None:
    async with system_session(world.factory) as s:
        await s.execute(
            update(CodingSubmission)
            .where(CodingSubmission.attempt_id == world.attempt_id)
            .values(created_at=CodingSubmission.created_at - by)
        )
        await s.commit()


async def add_old(world: World, count: int, auto: bool = False) -> None:
    async with tenant_session(world.factory, world.institution_id) as s:
        top = await s.scalar(select(func.coalesce(func.max(CodingSubmission.submission_no), 0)))
        for i in range(count):
            s.add(
                CodingSubmission(
                    attempt_id=world.attempt_id,
                    exam_question_id=world.exam_question_id,
                    submission_no=(top or 0) + i + 1,
                    language_key="python312",
                    source="x",
                    status="FAILED",
                    is_auto=auto,
                    created_at=datetime.now(UTC) - timedelta(minutes=5),
                )
            )
        await s.commit()


async def test_graded_on_every_case_hidden_ones_pass_fail_only(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    sent = client.post(url(world), json=CODE, headers=world.me)
    assert sent.status_code == 202, sent.text
    submission = sent.json()
    assert (submission["submission_no"], submission["status"], submission["poll_after_ms"]) == (
        1,
        "QUEUED",
        1500,
    )
    ((queue, job),) = no_exec_jobs
    assert queue == "exec.submit" and job.kind == "submit" and job.cases == "all"
    assert job.bundle_url and job.job_id != submission["id"]  # the job is the evaluation

    await handle(world.factory, result(uuid.UUID(job.job_id), all_but_last_two()))
    done = client.get(f"/api/v1/submissions/{submission['id']}", headers=world.me)
    body = done.json()
    assert (body["status"], body["verdict"], body["score"], body["max_score"]) == (
        "EVALUATED",
        "PARTIAL",
        "6.25",
        "10.00",
    )
    assert (body["passed_cases"], body["total_cases"], body["is_counted"]) == (6, 8, True)
    first, *hidden = body["cases"]
    assert (first["number"], first["hidden"], first["input"], first["expected_output"]) == (
        1,
        False,
        "in 1",
        "out 1",
    )
    assert [(c["number"], c["passed"]) for c in hidden] == [
        (2, True), (3, True), (4, True), (5, True), (6, True), (7, False), (8, False),
    ]  # fmt: skip
    for case in hidden:
        assert (
            case["input"],
            case["expected_output"],
            case["stdout"],
            case["time_ms"],
            case["outcome"],
        ) == (None,) * 5
    for secret in EXPECTED[1:]:
        assert secret not in done.text


async def test_five_seconds_apart(client: TestClient, world: World) -> None:
    client.post(url(world), json=CODE, headers=world.me)
    again = client.post(url(world), json=CODE, headers=world.me)
    assert again.status_code == 429 and again.json()["error"]["code"] == "SUBMIT_TOO_SOON"
    await earlier(world)
    assert client.post(url(world), json=CODE, headers=world.me).status_code == 202


async def test_concurrent_submits_never_exceed_the_limit(world: World) -> None:
    await add_old(world, 9)  # one left of the default 10
    async with system_session(world.factory) as s:
        attempt = await s.get_one(ExamAttempt, world.attempt_id)
    principal = Principal(attempt.student_id, world.institution_id, "STUDENT")
    storage = Storage(make_settings())

    async def one() -> str:
        async with tenant_session(world.factory, world.institution_id) as s:
            try:
                await submit(
                    s,
                    principal,
                    world.attempt_id,
                    world.exam_question_id,
                    SubmitIn(**CODE),
                    storage,
                )
                return "accepted"
            except AppError as error:
                return error.code

    outcomes = await asyncio.gather(*(one() for _ in range(6)))
    assert outcomes.count("accepted") == 1, outcomes
    async with system_session(world.factory) as s:
        counted = await s.scalar(
            select(func.count())
            .select_from(CodingSubmission)
            .where(
                CodingSubmission.attempt_id == world.attempt_id,
                CodingSubmission.is_auto.is_(False),
            )
        )
    assert counted == 10


async def test_limit_reached_but_automatic_ones_dont_count(
    client: TestClient, world: World
) -> None:
    await add_old(world, 3, auto=True)
    await add_old(world, 9)
    assert client.post(url(world), json=CODE, headers=world.me).status_code == 202
    await earlier(world)
    full = client.post(url(world), json=CODE, headers=world.me)
    assert full.status_code == 409 and full.json()["error"]["code"] == "SUBMISSION_LIMIT"
    history = client.get(url(world), headers=world.me).json()
    assert (history["submissions_left"], history["max_submissions"]) == (0, 10)


async def test_accepted_in_the_grace_refused_after_it(client: TestClient, world: World) -> None:
    async def deadline(seconds_ago: int) -> None:
        async with system_session(world.factory) as s:
            await s.execute(
                update(ExamAttempt)
                .where(ExamAttempt.id == world.attempt_id)
                .values(
                    started_at=datetime.now(UTC) - timedelta(hours=1),
                    deadline_at=datetime.now(UTC) - timedelta(seconds=seconds_ago),
                )
            )
            await s.commit()

    await deadline(20)  # the timer hit zero just now: a last submission still counts
    assert client.post(url(world), json=CODE, headers=world.me).status_code == 202
    await earlier(world)
    await deadline(120)
    late = client.post(url(world), json=CODE, headers=world.me)
    assert late.status_code == 409 and late.json()["error"]["code"] == "TIME_UP"


async def test_history_shows_which_counts_to_student_and_owner_only(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    client.post(url(world), json=CODE, headers=world.me)
    await earlier(world)
    client.post(url(world), json=CODE, headers=world.me)
    first, second = (uuid.UUID(job.job_id) for _, job in no_exec_jobs)
    await handle(world.factory, result(first, all_but_last_two()))
    compile_error = StepResult(
        exit_code=1, stdout="", stderr="SyntaxError", time_ms=5,
        timed_out=False, memory_exceeded=False, output_exceeded=False,
    )  # fmt: skip
    await handle(world.factory, result(second, [], compile=compile_error))

    history = client.get(url(world), headers=world.me).json()
    rows = [
        (s["submission_no"], s["verdict"], s["score"], s["is_counted"])
        for s in history["submissions"]
    ]
    assert rows == [(2, "COMPILE_ERROR", "0.00", False), (1, "PARTIAL", "6.25", True)]
    assert history["submissions"][0]["compile_output"] == "SyntaxError"
    assert history["submissions_left"] == 8

    assert client.get(url(world), headers=world.teacher).status_code == 200  # the exam's owner
    async with tenant_session(world.factory, world.institution_id) as s:
        other = User(email=f"o{uuid.uuid4().hex[:8]}@abc.edu", full_name="O", role="TEACHER")
        s.add(other)
        await s.commit()
        college = await s.get_one(Institution, world.institution_id)
    assert client.get(url(world), headers=bearer(other, college)).status_code == 404
