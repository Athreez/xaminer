"""Exam analytics (PRD MON-03..05; TCK-1203): the numbers match a sample worked out by hand."""

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import ExamAttempt
from app.db.session import tenant_session
from app.exams.models import ExamAssignment
from app.execution.results import handle
from app.grading.objective import grade
from app.main import create_app
from app.users.models import User
from tests.db.api_helpers import S3_PORT, make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_execution_results import World as CodingWorld
from tests.db.test_execution_results import all_but_last_two, result
from tests.db.test_execution_results import build as build_coding
from tests.db.test_start_attempt_api import World, bearer, build
from tests.services import require


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings())) as test_client:
        yield test_client


@pytest.fixture
async def world(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, client: TestClient
) -> AsyncIterator[World]:
    w, college = await build(app_engine, client, shuffle=False)
    yield w
    await purge_institutions(migrator_engine, [college.id])


async def another_student(world: World, name: str) -> dict[str, str]:
    async with tenant_session(world.factory, world.college.id) as s:
        user = User(email=f"{uuid.uuid4().hex[:8]}@abc.edu", full_name=name, role="STUDENT")
        s.add(user)
        await s.flush()
        owner = (await s.get_one(User, world.student.id)).id  # any user will do as assigner
        s.add(
            ExamAssignment(exam_id=uuid.UUID(world.exam_id), student_id=user.id, assigned_by=owner)
        )
        await s.commit()
    return bearer(user, world.college)


async def take(world: World, me: dict[str, str], picks: dict[int, list[str]]) -> None:
    """Start, pick options by label for question positions (0-based), submit, grade."""
    attempt = world.client.post(world.start_url, headers=me).json()
    answers: list[dict[str, Any]] = []
    for index, labels in picks.items():
        q = attempt["questions"][index]
        ids = [o["id"] for o in q["question"]["options"] if o["label"] in labels]
        answers.append(
            {
                "exam_question_id": q["exam_question_id"],
                "selected_option_ids": ids,
                "client_revision": 1,
            }
        )
    world.client.put(
        f"/api/v1/attempts/{attempt['id']}/answers", json={"answers": answers}, headers=me
    )
    assert world.client.post(f"/api/v1/attempts/{attempt['id']}/submit", headers=me).is_success
    await grade(world.factory, uuid.UUID(attempt["id"]))


async def test_numbers_match_a_hand_worked_sample(world: World) -> None:
    # Questions: MCQ 2 pts (Option 0 right), MSQ 2 pts (Options 0 and 1), True/False 1, essay 5.
    await take(world, world.me, {0: ["Option 0"], 1: ["Option 0", "Option 1"], 2: ["True"]})  # 5
    await take(
        world, await another_student(world, "B"), {0: ["Option 1"], 1: ["Option 0"], 2: ["True"]}
    )  # 1
    await take(world, await another_student(world, "C"), {})  # 0

    body = world.client.get(
        f"/api/v1/exams/{world.exam_id}/analytics", headers=world.teacher
    ).json()
    assert body["graded"] == 3
    assert (body["average"], body["median"], body["highest"], body["lowest"]) == (
        "2.00",
        "1.00",
        "5.00",
        "0.00",
    )
    assert body["histogram"] == [1, 1, 0, 0, 0, 1, 0, 0, 0, 0]  # 0 %, 10 %, 50 %
    assert body["pass_rate"] is None  # no pass mark set
    mcq, msq, true_false, essay = body["questions"]
    assert (mcq["average"], mcq["full_marks"]) == ("0.67", 1)
    assert {o["label"]: o["picked"] for o in mcq["options"]} == {
        "Option 0": 1,
        "Option 1": 1,
        "Option 2": 0,
        "Option 3": 0,
    }
    assert (msq["average"], msq["full_marks"]) == ("0.67", 1)  # all or nothing: B scores 0
    assert (true_false["average"], true_false["full_marks"]) == ("0.67", 2)
    assert (essay["average"], essay["full_marks"], essay["options"]) == ("0.00", 0, [])
    assert (
        world.client.get(f"/api/v1/exams/{world.exam_id}/analytics", headers=world.me).status_code
        == 403
    )


async def test_coding_verdicts_and_pass_rate_per_test_case(
    app_engine: AsyncEngine, migrator_engine: AsyncEngine, client: TestClient
) -> None:
    require(S3_PORT, "Object storage")
    w: CodingWorld
    w, college = await build_coding(app_engine, client, "BEST")
    try:
        await handle(w.factory, result(await w.submission(1), all_but_last_two()))
        assert client.post(f"/api/v1/attempts/{w.attempt_id}/submit", headers=w.me).is_success
        await grade(w.factory, w.attempt_id)
        async with tenant_session(w.factory, w.institution_id) as s:
            exam_id = (await s.get_one(ExamAttempt, w.attempt_id)).exam_id
        body = client.get(f"/api/v1/exams/{exam_id}/analytics", headers=w.teacher).json()
        coding = next(q for q in body["questions"] if q["type"] == "CODING")
        assert coding["verdicts"] == {"PARTIAL": 1}
        cases = {c["number"]: c for c in coding["test_cases"]}
        assert len(cases) == 8 and not cases[1]["hidden"] and cases[2]["hidden"]
        assert (cases[1]["pass_rate"], cases[1]["possibly_broken"]) == (1.0, False)
        assert (cases[7]["pass_rate"], cases[7]["possibly_broken"]) == (0.0, True)
        assert "expected_output" not in str(body) and "out 7" not in str(body)  # never content
    finally:
        await purge_institutions(migrator_engine, [college.id])
