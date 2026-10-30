"""Results (PRD GRD-05..09; TCK-0905..0907): computed once grading is complete, released only when
every attempt is graded, students see their own released results only (no keys or rubrics), and
a change to a released score keeps a revision."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.grading.objective import grade
from app.main import create_app
from tests.db.api_helpers import make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_start_attempt_api import World, build


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False)
        yield w
    await purge_institutions(migrator_engine, [college.id])


def pick(question: dict[str, Any], *labels: str) -> list[str]:
    return [o["id"] for o in question["question"]["options"] if o["label"] in labels]


async def all_right_but_the_essay(world: World) -> dict[str, Any]:
    attempt = world.client.post(world.start_url, headers=world.me).json()
    mcq, msq, true_false, essay = attempt["questions"]
    answers = [
        {"exam_question_id": mcq["exam_question_id"], "selected_option_ids": pick(mcq, "Option 0")},
        {
            "exam_question_id": msq["exam_question_id"],
            "selected_option_ids": pick(msq, "Option 0", "Option 1"),
        },
        {
            "exam_question_id": true_false["exam_question_id"],
            "selected_option_ids": pick(true_false, "True"),
        },
        {"exam_question_id": essay["exam_question_id"], "text_answer": "A base case."},
    ]
    world.client.put(
        f"/api/v1/attempts/{attempt['id']}/answers",
        json={"answers": [{**a, "client_revision": 1} for a in answers]},
        headers=world.me,
    )
    assert world.client.post(
        f"/api/v1/attempts/{attempt['id']}/submit", headers=world.me
    ).is_success
    await grade(world.factory, uuid.UUID(attempt["id"]))
    return {"id": attempt["id"], "essay": essay["exam_question_id"]}


async def test_results_are_released_only_when_grading_is_complete(world: World) -> None:
    attempt = await all_right_but_the_essay(world)
    results_url = f"/api/v1/exams/{world.exam_id}/results"
    mine = f"/api/v1/student/results/{attempt['id']}"

    waiting = world.client.get(results_url, headers=world.teacher).json()
    (row,) = waiting["rows"]
    assert (row["grading_status"], row["total_score"]) == ("AWAITING_MANUAL", None)
    assert waiting["can_release"] is False
    assert waiting["blocked_reason"] == "1 attempt is still being graded."
    refused = world.client.post(f"{results_url}/release", headers=world.teacher)
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "RESULTS_NOT_READY")

    marked = world.client.put(
        f"/api/v1/attempts/{attempt['id']}/answers/{attempt['essay']}/mark",
        json={"score": "4", "feedback": "Name the stack."},
        headers=world.teacher,
    )
    assert marked.status_code == 200, marked.text
    ready = world.client.get(results_url, headers=world.teacher).json()
    assert (ready["rows"][0]["total_score"], ready["rows"][0]["percentage"]) == ("9.00", "90.00")
    assert (ready["can_release"], ready["unreleased"]) == (True, 1)
    assert world.client.get(mine, headers=world.me).status_code == 404  # not released yet
    listed = world.client.get("/api/v1/student/results", headers=world.me).json()["items"]
    assert [(i["released"], i["total_score"]) for i in listed] == [(False, None)]

    detail = world.client.get(f"{results_url}/{attempt['id']}", headers=world.teacher).json()
    assert detail["questions"][0]["correct_labels"] == ["Option 0"]  # the teacher sees the key

    released = world.client.post(f"{results_url}/release", headers=world.teacher)
    assert released.status_code == 200, released.text
    assert released.json()["rows"][0]["released_at"] is not None
    assert released.json()["blocked_reason"] == "Nothing to release."

    student = world.client.get(mine, headers=world.me)
    assert student.status_code == 200, student.text
    body = student.json()
    assert (body["total_score"], body["max_score"], body["percentage"]) == (
        "9.00",
        "10.00",
        "90.00",
    )
    assert [q["score"] for q in body["questions"]] == ["2.00", "2.00", "1.00", "4.00"]
    assert body["questions"][3]["feedback"] == "Name the stack."
    assert body["questions"][0]["selected_labels"] == ["Option 0"]
    assert "correct_labels" not in body["questions"][0]  # never the key
    assert "rubric" not in body["questions"][3]
    listed = world.client.get("/api/v1/student/results", headers=world.me).json()["items"]
    assert [(i["released"], i["total_score"]) for i in listed] == [(True, "9.00")]


async def test_changing_a_released_score_keeps_a_revision(world: World) -> None:
    attempt = await all_right_but_the_essay(world)
    mark_url = f"/api/v1/attempts/{attempt['id']}/answers/{attempt['essay']}/mark"
    world.client.put(mark_url, json={"score": "4"}, headers=world.teacher)
    world.client.post(f"/api/v1/exams/{world.exam_id}/results/release", headers=world.teacher)

    no_reason = world.client.put(mark_url, json={"score": "5"}, headers=world.teacher)
    assert (no_reason.status_code, no_reason.json()["error"]["code"]) == (422, "REASON_REQUIRED")
    changed = world.client.put(
        mark_url, json={"score": "5", "reason": "Re-read: full marks"}, headers=world.teacher
    )
    assert changed.status_code == 200, changed.text

    body = world.client.get(f"/api/v1/student/results/{attempt['id']}", headers=world.me).json()
    assert body["total_score"] == "10.00"
    assert [(r["old_score"], r["new_score"], r["reason"]) for r in body["revisions"]] == [
        ("9.00", "10.00", "Re-read: full marks")
    ]


async def test_others_never_see_a_result(world: World) -> None:
    attempt = await all_right_but_the_essay(world)
    url = f"/api/v1/exams/{world.exam_id}/results"
    assert world.client.get(url, headers=world.me).status_code == 403  # students: no
    assert (
        world.client.get(f"/api/v1/student/results/{uuid.uuid4()}", headers=world.me).status_code
        == 404
    )
    assert (
        world.client.get(
            f"/api/v1/student/results/{attempt['id']}", headers=world.teacher
        ).status_code
        == 404
    )
