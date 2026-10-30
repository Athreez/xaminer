"""Run Code through the API (PRD EXE-02, EXE-03; TCK-0808): public cases only, one at a time,
8 s apart, 20 per question; results never show anything hidden."""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import ExamAttempt
from app.db.session import system_session, tenant_session
from app.execution.models import CodeRun
from app.execution.results import handle
from app.execution.runs import delete_old_runs
from app.main import create_app
from app.platform.models import Institution
from app.users.models import User
from tests.db.api_helpers import S3_PORT, make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_execution_results import World, build, step
from tests.db.test_start_attempt_api import bearer
from tests.services import require
from workers.exec_messages import CaseResult, ExecJob, ExecResult

PY = {"language_key": "python312", "source": "print(input().replace('in', 'out'))"}


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


def url(world: World, eq: uuid.UUID | None = None) -> str:
    return f"/api/v1/attempts/{world.attempt_id}/questions/{eq or world.exam_question_id}/runs"


async def age_runs(world: World, by: timedelta) -> None:
    async with system_session(world.factory) as s:
        await s.execute(
            update(CodeRun)
            .where(CodeRun.attempt_id == world.attempt_id)
            .values(created_at=CodeRun.created_at - by)
        )
        await s.commit()


def result_for(job: ExecJob, cases: list[tuple[str, str]]) -> ExecResult:
    return ExecResult(
        job_id=job.job_id,
        kind="run",
        status="COMPLETED",
        cases=[CaseResult(name=name, **step(out)) for name, out in cases],
    )


async def test_runs_public_cases_and_never_shows_hidden_ones(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, Any]]
) -> None:
    started = client.post(url(world), json=PY, headers=world.me)
    assert started.status_code == 202, started.text
    run = started.json()
    assert (run["status"], run["results"], run["runs_left"], run["poll_after_ms"]) == (
        "QUEUED",
        None,
        19,
        1000,
    )
    ((queue, job),) = no_exec_jobs
    assert queue == "exec.run" and job.kind == "run" and job.cases == "public"
    assert job.bundle_url and job.custom_input is None
    assert job.time_limit_ms == 5000  # default 2000 ms x Python's 2.5

    # Even if a hidden case came back, it is never kept or shown.
    await handle(world.factory, result_for(job, [("001", "out 1"), ("002", "out 2")]))
    done = client.get(f"/api/v1/runs/{run['id']}", headers=world.me)
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "COMPLETED" and body["poll_after_ms"] is None
    assert [
        (r["name"], r["input"], r["expected_output"], r["passed"]) for r in body["results"]
    ] == [("001", "in 1", "out 1", True)]
    for hidden in ("in 2", "out 2", "out 8"):
        assert hidden not in done.text


async def test_one_at_a_time_and_eight_seconds_apart(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, Any]]
) -> None:
    client.post(url(world), json=PY, headers=world.me)
    busy = client.post(url(world), json=PY, headers=world.me)
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "RUN_IN_PROGRESS"

    await handle(world.factory, result_for(no_exec_jobs[0][1], [("001", "out 1")]))
    soon = client.post(url(world), json=PY, headers=world.me)
    assert soon.status_code == 429 and soon.json()["error"]["code"] == "RUN_TOO_SOON"
    assert 1 <= int(soon.headers["Retry-After"]) <= 9  # the 8 s gap, in the standard header
    assert 1 <= soon.json()["error"]["details"][0]["retry_after_s"] <= 8

    await age_runs(world, timedelta(seconds=9))
    assert client.post(url(world), json=PY, headers=world.me).status_code == 202


async def test_twenty_runs_per_question(client: TestClient, world: World) -> None:
    async with tenant_session(world.factory, world.institution_id) as s:
        for _ in range(20):
            s.add(
                CodeRun(
                    attempt_id=world.attempt_id,
                    exam_question_id=world.exam_question_id,
                    language_key="python312",
                    source="x",
                    status="COMPLETED",
                    created_at=datetime.now(UTC) - timedelta(minutes=5),
                )
            )
        await s.commit()
    full = client.post(url(world), json=PY, headers=world.me)
    assert full.status_code == 409 and full.json()["error"]["code"] == "RUN_LIMIT"


async def test_only_allowed_languages_and_coding_questions(
    client: TestClient, world: World
) -> None:
    java = client.post(url(world), json=PY | {"language_key": "java21"}, headers=world.me)
    assert java.status_code == 422 and java.json()["error"]["code"] == "LANGUAGE_NOT_ALLOWED"
    essay = client.post(url(world, world.essay_id), json=PY, headers=world.me)
    assert essay.status_code == 409 and essay.json()["error"]["code"] == "NOT_CODING"
    missing = client.post(url(world, uuid.uuid4()), json=PY, headers=world.me)
    assert missing.status_code == 404


async def test_no_runs_once_time_is_up(client: TestClient, world: World) -> None:
    async with system_session(world.factory) as s:
        await s.execute(
            update(ExamAttempt)
            .where(ExamAttempt.id == world.attempt_id)
            .values(
                started_at=datetime.now(UTC) - timedelta(hours=1),
                deadline_at=datetime.now(UTC) - timedelta(seconds=10),
            )
        )
        await s.commit()
    late = client.post(url(world), json=PY, headers=world.me)
    assert late.status_code == 409 and late.json()["error"]["code"] == "TIME_UP"


async def test_custom_input_needs_no_bundle_and_compares_nothing(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, Any]]
) -> None:
    run = client.post(url(world), json=PY | {"custom_input": "in 42"}, headers=world.me).json()
    assert run["custom_input"] is True
    ((_, job),) = no_exec_jobs
    assert job.custom_input == "in 42" and job.bundle_url is None
    await handle(world.factory, result_for(job, [("custom", "out 42")]))
    results = client.get(f"/api/v1/runs/{run['id']}", headers=world.me).json()["results"]
    assert [(r["name"], r["input"], r["stdout"], r["passed"]) for r in results] == [
        ("custom", "in 42", "out 42", None)
    ]


async def test_runs_are_private_and_deleted_after_a_day(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, Any]]
) -> None:
    run = client.post(url(world), json=PY, headers=world.me).json()
    async with tenant_session(world.factory, world.institution_id) as s:
        other = User(email=f"o{uuid.uuid4().hex[:8]}@abc.edu", full_name="O", role="STUDENT")
        s.add(other)
        await s.commit()
        college = await s.get_one(Institution, world.institution_id)
    assert (
        client.get(f"/api/v1/runs/{run['id']}", headers=bearer(other, college)).status_code == 404
    )

    await age_runs(world, timedelta(hours=25))
    assert await delete_old_runs(world.factory) >= 1
    assert client.get(f"/api/v1/runs/{run['id']}", headers=world.me).status_code == 404
