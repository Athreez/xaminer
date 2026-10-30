"""Grading objective answers when an attempt ends (PRD GRD-01; TCK-0902): every MCQ, MSQ and
True/False question gets a score (unanswered ones 0), descriptive answers are left alone, and
running it again gives the same scores."""

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import Answer
from app.db.session import system_session
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


def option(question: dict[str, Any], label: str) -> str:
    return next(o["id"] for o in question["question"]["options"] if o["label"] == label)  # type: ignore[no-any-return]


async def scores(world: World, attempt_id: str) -> dict[str, tuple[Decimal | None, Decimal | None]]:
    async with system_session(world.factory) as s:
        rows = await s.scalars(select(Answer).where(Answer.attempt_id == uuid.UUID(attempt_id)))
        return {str(a.exam_question_id): (a.auto_score, a.score) for a in rows}


async def test_objective_answers_are_scored_once_the_attempt_ends(
    world: World, no_grading_jobs: list[uuid.UUID]
) -> None:
    attempt = world.client.post(world.start_url, headers=world.me).json()
    mcq, msq, true_false, essay = attempt["questions"]
    answers = [
        {
            "exam_question_id": mcq["exam_question_id"],
            "selected_option_ids": [option(mcq, "Option 0")],
        },
        {
            "exam_question_id": msq["exam_question_id"],
            "selected_option_ids": [option(msq, "Option 0"), option(msq, "Option 2")],
        },
        {"exam_question_id": essay["exam_question_id"], "text_answer": "Base case"},
    ]
    saved = world.client.put(
        f"/api/v1/attempts/{attempt['id']}/answers",
        json={"answers": [{**a, "client_revision": 1} for a in answers]},
        headers=world.me,
    )
    assert saved.status_code == 200, saved.text
    assert await grade(world.factory, uuid.UUID(attempt["id"])) == 0  # not ended yet: nothing

    submitted = world.client.post(f"/api/v1/attempts/{attempt['id']}/submit", headers=world.me)
    assert submitted.status_code == 200, submitted.text
    assert no_grading_jobs == [uuid.UUID(attempt["id"])]  # queued once it was committed

    assert await grade(world.factory, uuid.UUID(attempt["id"])) == 3
    first = await scores(world, attempt["id"])
    assert first == {
        mcq["exam_question_id"]: (Decimal("2.00"), Decimal("2.00")),
        msq["exam_question_id"]: (Decimal("0.00"), Decimal("0.00")),  # a wrong pick, no negatives
        true_false["exam_question_id"]: (Decimal("0.00"), Decimal("0.00")),  # unanswered: a 0 row
        essay["exam_question_id"]: (None, None),  # descriptive: left for a grader
    }
    assert await grade(world.factory, uuid.UUID(attempt["id"])) == 3
    assert await scores(world, attempt["id"]) == first  # again: identical
