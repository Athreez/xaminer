"""Grading the last draft at the end of an attempt (PRD EXE-06; TCK-0810): a draft newer than the
last submission is submitted and graded, not counted toward the limit; running twice is harmless."""

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.storage import Storage
from app.db.session import system_session
from app.execution.auto_submit import auto_submit
from app.execution.models import CodingEvaluation, CodingSubmission
from app.execution.results import handle
from app.main import create_app
from tests.db.api_helpers import S3_PORT, make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_execution_results import EXPECTED, World, build, result, step
from tests.services import require
from workers.exec_messages import ExecJob

GOOD = "print(input().replace('in', 'out'))"


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


def save_draft(client: TestClient, world: World, source: str, revision: int) -> None:
    response = client.put(
        f"/api/v1/attempts/{world.attempt_id}/drafts/{world.exam_question_id}",
        json={"language_key": "python312", "source": source, "client_revision": revision},
        headers=world.me,
    )
    assert response.status_code == 200, response.text


def hand_in(client: TestClient, world: World) -> None:
    response = client.post(f"/api/v1/attempts/{world.attempt_id}/submit", headers=world.me)
    assert response.status_code == 200, response.text


async def submissions(world: World) -> list[CodingSubmission]:
    async with system_session(world.factory) as s:
        rows = await s.scalars(
            select(CodingSubmission)
            .where(CodingSubmission.attempt_id == world.attempt_id)
            .order_by(CodingSubmission.submission_no)
        )
        return list(rows)


async def test_draft_is_graded_when_the_attempt_ends(
    client: TestClient,
    world: World,
    no_auto_submit_jobs: list[uuid.UUID],
    no_exec_jobs: list[tuple[str, ExecJob]],
) -> None:
    save_draft(client, world, GOOD, 1)
    assert (
        await auto_submit(world.factory, Storage(make_settings()), world.attempt_id) == 0
    )  # still going
    hand_in(client, world)
    assert no_auto_submit_jobs == [world.attempt_id]  # queued once, after the commit

    storage = Storage(make_settings())
    assert await auto_submit(world.factory, storage, world.attempt_id) == 1
    assert await auto_submit(world.factory, storage, world.attempt_id) == 0  # repeat: nothing new
    (auto,) = await submissions(world)
    assert (auto.is_auto, auto.submission_no, auto.source, auto.language_key) == (
        True,
        1,
        GOOD,
        "python312",
    )
    ((queue, job),) = no_exec_jobs
    assert queue == "exec.submit" and job.kind == "submit" and job.source == GOOD

    await handle(world.factory, result(uuid.UUID(job.job_id), [step(e) for e in EXPECTED]))
    async with system_session(world.factory) as s:
        evaluation = await s.get_one(CodingEvaluation, uuid.UUID(job.job_id))
    assert (evaluation.verdict, str(evaluation.score)) == ("ACCEPTED", "10.00")
    (auto,) = await submissions(world)
    assert auto.is_counted


async def test_only_drafts_newer_than_the_last_submission(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    save_draft(client, world, "print('old')", 1)
    sent = client.post(
        f"/api/v1/attempts/{world.attempt_id}/questions/{world.exam_question_id}/submissions",
        json={"language_key": "python312", "source": "print('submitted')"},
        headers=world.me,
    )
    assert sent.status_code == 202
    hand_in(client, world)
    assert await auto_submit(world.factory, Storage(make_settings()), world.attempt_id) == 0
    assert [s.is_auto for s in await submissions(world)] == [False]


async def test_newer_draft_after_a_submission_is_graded_too(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    client.post(
        f"/api/v1/attempts/{world.attempt_id}/questions/{world.exam_question_id}/submissions",
        json={"language_key": "python312", "source": "print('first try')"},
        headers=world.me,
    )
    save_draft(client, world, GOOD, 5)  # kept working after submitting
    hand_in(client, world)
    assert await auto_submit(world.factory, Storage(make_settings()), world.attempt_id) == 1
    rows = await submissions(world)
    assert [(s.submission_no, s.is_auto, s.source) for s in rows] == [
        (1, False, "print('first try')"),
        (2, True, GOOD),
    ]
    history = client.get(
        f"/api/v1/attempts/{world.attempt_id}/questions/{world.exam_question_id}/submissions",
        headers=world.me,
    ).json()
    assert history["submissions_left"] == 9  # the automatic one doesn't count


async def test_no_draft_nothing_to_do(client: TestClient, world: World) -> None:
    hand_in(client, world)
    assert await auto_submit(world.factory, Storage(make_settings()), world.attempt_id) == 0
    assert await submissions(world) == []
