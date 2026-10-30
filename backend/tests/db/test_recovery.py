"""Stuck execution jobs (PRD EXE-07, EXE-08; TCK-0811): waiting is fine, a job that started and
went silent is sent again, three starts without a result is INTERNAL_ERROR with no score."""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.storage import Storage
from app.db.session import system_session, tenant_session
from app.execution.models import CodeRun, CodingEvaluation, CodingSubmission
from app.execution.recovery import started, sweep
from app.execution.results import handle
from app.main import create_app
from app.questions.models import CodingConfig
from tests.db.api_helpers import S3_PORT, make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_execution_results import EXPECTED, World, build, result, step
from tests.services import require
from workers.exec_messages import ExecJob

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


async def submit(client: TestClient, world: World, jobs: list[tuple[str, ExecJob]]) -> ExecJob:
    url = f"/api/v1/attempts/{world.attempt_id}/questions/{world.exam_question_id}/submissions"
    assert client.post(url, json=CODE, headers=world.me).status_code == 202
    return jobs[-1][1]


async def evaluation(world: World, job: ExecJob) -> CodingEvaluation:
    async with system_session(world.factory) as s:
        return await s.get_one(CodingEvaluation, uuid.UUID(job.job_id))


async def run_sweep(world: World, later: timedelta) -> dict[str, int]:
    """Sweep as if `later` had passed. Counts only this test's rows matter, so they're checked
    through the rows themselves."""
    return await sweep(world.factory, Storage(make_settings()), datetime.now(UTC) + later)


async def test_waiting_in_the_queue_is_never_touched_but_a_lost_job_is_sent_again(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    job = await submit(client, world, no_exec_jobs)
    await run_sweep(world, timedelta(minutes=14))  # busy: still queued, untouched
    assert len(no_exec_jobs) == 1
    await run_sweep(world, timedelta(hours=2))  # never picked up: the message was lost
    resent = [j for _, j in no_exec_jobs if j.job_id == job.job_id]
    assert len(resent) == 2
    row = await evaluation(world, job)
    assert (row.status, row.starts) == ("QUEUED", 0)  # being lost isn't a failure


async def test_started_and_silent_is_sent_again_and_still_grades(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    job = await submit(client, world, no_exec_jobs)
    await started(world.factory, job.job_id, "submit")
    row = await evaluation(world, job)
    assert row.starts == 1 and row.started_at is not None
    await run_sweep(world, timedelta(minutes=10))  # may still be running a slow job
    assert len(no_exec_jobs) == 1
    await run_sweep(world, timedelta(minutes=16))  # the worker died mid-job
    assert [j.job_id for _, j in no_exec_jobs] == [job.job_id, job.job_id]
    assert no_exec_jobs[-1][1].bundle_url  # a fresh link
    row = await evaluation(world, job)
    assert (row.status, row.started_at) == ("QUEUED", None)

    await handle(world.factory, result(uuid.UUID(job.job_id), [step(e) for e in EXPECTED]))
    row = await evaluation(world, job)
    assert (row.status, row.verdict) == ("DONE", "ACCEPTED")  # no lost submission


async def test_three_starts_without_a_result_is_internal_error_no_score(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    job = await submit(client, world, no_exec_jobs)
    for _ in range(3):
        await started(world.factory, job.job_id, "submit")
    await run_sweep(world, timedelta(minutes=20))
    row = await evaluation(world, job)
    assert (row.status, row.verdict, row.score) == ("FAILED", "INTERNAL_ERROR", None)
    async with system_session(world.factory) as s:
        submission = await s.scalar(
            select(CodingSubmission).where(CodingSubmission.attempt_id == world.attempt_id)
        )
    assert submission is not None and (submission.status, submission.is_counted) == (
        "FAILED",
        False,
    )
    assert len([j for _, j in no_exec_jobs if j.job_id == job.job_id]) == 1  # not sent again
    # A late result changes nothing now.
    assert (
        await handle(world.factory, result(uuid.UUID(job.job_id), [step(e) for e in EXPECTED]))
        == "ignored"
    )


async def test_stuck_runs_and_validations_are_marked_failed(
    client: TestClient, world: World
) -> None:
    long_ago = datetime.now(UTC) - timedelta(hours=1)
    async with tenant_session(world.factory, world.institution_id) as s:
        run = CodeRun(
            attempt_id=world.attempt_id,
            exam_question_id=world.exam_question_id,
            language_key="python312",
            source="x",
            created_at=long_ago,
        )
        s.add(run)
        await s.commit()
    draft = client.post(
        "/api/v1/questions",
        json={"type": "CODING", "body": "Draft.", "points": "5"},
        headers=world.teacher,
    ).json()
    version_id = uuid.UUID(draft["version"]["id"])
    async with system_session(world.factory) as s:
        await s.execute(
            update(CodingConfig)
            .where(CodingConfig.version_id == version_id)
            .values(
                validation_status="VALIDATING",
                validation_report={
                    "run": "r1",
                    "started_at": long_ago.isoformat(),
                    "pending": ["python312"],
                    "languages": {},
                },
            )
        )
        await s.commit()

    await run_sweep(world, timedelta(0))
    async with system_session(world.factory) as s:
        assert (await s.get_one(CodeRun, run.id)).status == "FAILED"  # the student may run again
        config = await s.get_one(CodingConfig, version_id)
    assert config.validation_status == "FAILED"
    assert config.validation_report["languages"]["python312"]["status"] == "ERROR"
    assert config.validation_report["pending"] == []


async def test_started_ignores_unknown_and_finished_jobs(world: World) -> None:
    await started(world.factory, "validation:x:y:z", "validation")  # not a row id: ignored
    await started(world.factory, str(uuid.uuid4()), "submit")  # unknown: ignored
