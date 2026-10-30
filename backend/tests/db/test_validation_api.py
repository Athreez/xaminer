"""Validating coding questions (PRD CQ-08, CQ-09; TCK-0705): a good reference passes, a bad one
fails, slow cases warn, edits reset the status and late results are ignored."""

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory
from app.execution.results import handle
from app.main import create_app
from cli import commands
from tests.db.api_helpers import S3_PORT, make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_questions_api import URL, World
from tests.services import require
from workers.exec_messages import CaseResult, ExecJob, ExecResult, StepResult

PY = {"language_key": "python312"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    require(S3_PORT, "Object storage")  # the bundle is built on the way
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(factory, f"Validation test {uuid.uuid4().hex[:8]}")
    w = World(factory, college, [college.id])
    yield w
    await purge_institutions(migrator_engine, w.ids)


def make_question(client: TestClient, me: dict[str, str], languages: list[dict[str, str]]) -> str:
    qid = client.post(
        URL, json={"type": "CODING", "body": "Add.", "points": "5"}, headers=me
    ).json()["id"]
    q = f"{URL}/{qid}"
    client.put(
        f"{q}/coding", json={"allowed_languages": languages, "time_limit_ms": 1000}, headers=me
    )
    client.post(
        f"{q}/test-cases",
        json={"visibility": "PUBLIC", "input": "1 2", "expected_output": "3"},
        headers=me,
    )
    client.post(f"{q}/test-cases", json={"input": "5 7", "expected_output": "12"}, headers=me)
    for language in languages:
        client.put(
            f"{q}/reference-solutions/{language['language_key']}", json={"source": "x"}, headers=me
        )
    return qid


def reply(
    job: ExecJob, outputs: list[str], times: list[int] | None = None, **extra: Any
) -> ExecResult:
    times = times or [10] * len(outputs)
    cases = [
        CaseResult(
            name=f"{i:03d}",
            exit_code=0,
            stdout=out,
            stderr="",
            time_ms=t,
            timed_out=False,
            memory_exceeded=False,
            output_exceeded=False,
        )
        for i, (out, t) in enumerate(zip(outputs, times, strict=True), start=1)
    ]
    values: dict[str, Any] = {
        "job_id": job.job_id,
        "kind": "validation",
        "status": "COMPLETED",
        "cases": cases,
    } | extra
    return ExecResult(**values)


def coding(client: TestClient, me: dict[str, str], qid: str) -> dict[str, Any]:
    return client.get(f"{URL}/{qid}", headers=me).json()["coding"]  # type: ignore[no-any-return]


async def test_good_reference_passes_with_times_and_warnings(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    me = await world.user()
    qid = make_question(client, me, [PY])
    started = client.post(f"{URL}/{qid}/validate", headers=me)
    assert started.status_code == 200, started.text
    assert started.json()["coding"]["validation_status"] == "VALIDATING"

    ((queue, job),) = no_exec_jobs
    assert queue == "exec.validation" and job.kind == "validation" and job.cases == "all"
    assert job.time_limit_ms == 2500  # 1000 ms x Python's 2.5
    assert job.source == "x" and job.bundle_url and job.bundle_sha256
    assert job.language.image == "xaminer-runner-python312:2"

    # Case 2 takes 1300 ms: over half of 2500 ms, so a warning (it still passes).
    assert await handle(world.factory, reply(job, ["3\n", "12"], [40, 1300])) == "validated"
    after = coding(client, me, qid)
    assert after["validation_status"] == "PASSED"
    report = after["validation_report"]["languages"]["python312"]
    assert report["status"] == "PASSED" and report["time_limit_ms"] == 2500
    assert [(c["name"], c["hidden"], c["time_ms"], c["slow"]) for c in report["cases"]] == [
        ("001", False, 40, False),
        ("002", True, 1300, True),
    ]
    assert after["validation_report"]["warnings"] == [
        "python312: test 2 took 1300 ms, over half the 2500 ms limit."
    ]
    assert await handle(world.factory, reply(job, ["3", "12"])) == "ignored"  # repeat


async def test_bad_reference_fails(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    me = await world.user()
    qid = make_question(client, me, [PY])
    client.post(f"{URL}/{qid}/validate", headers=me)
    ((_, job),) = no_exec_jobs
    await handle(world.factory, reply(job, ["3", "13"]))
    after = coding(client, me, qid)
    assert after["validation_status"] == "FAILED"
    cases = after["validation_report"]["languages"]["python312"]["cases"]
    assert [(c["outcome"], c["stdout"]) for c in cases] == [
        ("PASSED", None),
        ("WRONG_ANSWER", "13"),
    ]


async def test_every_reference_must_pass_and_compile(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    me = await world.user()
    qid = make_question(client, me, [PY, {"language_key": "cpp17"}])
    client.post(f"{URL}/{qid}/validate", headers=me)
    jobs = {job.language.key: job for _, job in no_exec_jobs}
    assert jobs["cpp17"].time_limit_ms == 1000  # C++ has no multiplier
    assert await handle(world.factory, reply(jobs["python312"], ["3", "12"])) == "recorded"
    assert coding(client, me, qid)["validation_status"] == "VALIDATING"  # C++ still running
    broken = StepResult(
        exit_code=1, stdout="", stderr="main.cpp:1: error", time_ms=200,
        timed_out=False, memory_exceeded=False, output_exceeded=False,
    )  # fmt: skip
    await handle(world.factory, reply(jobs["cpp17"], [], compile=broken))
    after = coding(client, me, qid)
    assert after["validation_status"] == "FAILED"
    assert after["validation_report"]["languages"]["cpp17"]["compile_output"] == "main.cpp:1: error"


async def test_editing_a_case_resets_and_late_results_are_ignored(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    me = await world.user()
    qid = make_question(client, me, [PY])
    client.post(f"{URL}/{qid}/validate", headers=me)
    ((_, job),) = no_exec_jobs
    case = client.get(f"{URL}/{qid}/test-cases", headers=me).json()[1]
    client.patch(f"{URL}/{qid}/test-cases/{case['id']}", json={"expected_output": "99"}, headers=me)
    assert coding(client, me, qid)["validation_status"] == "NEEDS_VALIDATION"
    assert await handle(world.factory, reply(job, ["3", "12"])) == "ignored"  # for the old cases
    assert coding(client, me, qid)["validation_status"] == "NEEDS_VALIDATION"

    # A new run ignores the old run's results too.
    client.post(f"{URL}/{qid}/validate", headers=me)
    assert await handle(world.factory, reply(job, ["3", "99"])) == "ignored"
    assert await handle(world.factory, reply(no_exec_jobs[-1][1], ["3", "99"])) == "validated"
    assert coding(client, me, qid)["validation_status"] == "PASSED"


async def test_platform_failure_is_an_error_not_a_pass(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    me = await world.user()
    qid = make_question(client, me, [PY])
    client.post(f"{URL}/{qid}/validate", headers=me)
    ((_, job),) = no_exec_jobs
    await handle(world.factory, reply(job, [], status="FAILED", error="bundle hash mismatch"))
    after = coding(client, me, qid)
    assert after["validation_status"] == "FAILED"
    assert after["validation_report"]["languages"]["python312"]["status"] == "ERROR"


async def test_refused_while_something_is_missing_or_published(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    me = await world.user()
    bare = client.post(
        URL, json={"type": "CODING", "body": "Add.", "points": "5"}, headers=me
    ).json()
    blocked = client.post(f"{URL}/{bare['id']}/validate", headers=me)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "VALIDATION_BLOCKED"
    assert len(blocked.json()["error"]["details"]) == 3

    qid = make_question(client, me, [PY])
    version = client.get(f"{URL}/{qid}", headers=me).json()["version"]["id"]
    await world.lock(version)
    locked = client.post(f"{URL}/{qid}/validate", headers=me)
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "QUESTION_LOCKED"
    assert no_exec_jobs == []

    other = await world.user()
    assert client.post(f"{URL}/{qid}/validate", headers=other).status_code == 404


async def test_a_passed_question_can_be_published(
    client: TestClient, world: World, no_exec_jobs: list[tuple[str, ExecJob]]
) -> None:
    from datetime import UTC, datetime, timedelta

    me = await world.user()
    qid = make_question(client, me, [PY])
    soon = datetime.now(UTC) + timedelta(days=1)
    exam = client.post(
        "/api/v1/exams",
        json={
            "title": "V",
            "open_at": soon.isoformat(),
            "close_at": (soon + timedelta(hours=2)).isoformat(),
            "duration_min": 60,
        },
        headers=me,
    ).json()
    check = f"/api/v1/exams/{exam['id']}/publish-check"
    client.put(
        f"/api/v1/exams/{exam['id']}/questions",
        json={"questions": [{"question_id": qid}]},
        headers=me,
    )

    def codes() -> list[str]:
        return [b["code"] for b in client.get(check, headers=me).json()["blocks"]]

    assert "CODING_NOT_VALIDATED" in codes()
    client.post(f"{URL}/{qid}/validate", headers=me)
    await handle(world.factory, reply(no_exec_jobs[-1][1], ["3", "12"]))
    assert "CODING_NOT_VALIDATED" not in codes()
