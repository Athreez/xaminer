"""Autosave through the real HTTP API (PRD ATT-07, ATT-08, ATT-11)."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import AttemptQuestion, CodeDraft, ExamAttempt
from app.db.session import tenant_session
from app.exams.models import Exam, ExamAssignment, ExamQuestion, ExamVersion
from app.main import create_app
from app.questions.models import Question, QuestionVersion
from app.users.models import User
from tests.db.api_helpers import make_settings
from tests.db.question_helpers import purge_institutions
from tests.db.test_start_attempt_api import World, bearer, build


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    with TestClient(create_app(make_settings())) as client:
        w, college = await build(app_engine, client, shuffle=False)
        yield w
    await purge_institutions(migrator_engine, [college.id])


def begin(world: World) -> dict[str, Any]:
    response = world.client.post(world.start_url, headers=world.me)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def save(world: World, attempt_id: str, *answers: dict[str, Any]):  # type: ignore[no-untyped-def]
    return world.client.put(
        f"/api/v1/attempts/{attempt_id}/answers", json={"answers": list(answers)}, headers=world.me
    )


def stored(world: World, attempt_id: str) -> dict[str, Any]:
    body = world.client.get(f"/api/v1/attempts/{attempt_id}", headers=world.me).json()
    return {q["exam_question_id"]: q for q in body["questions"]}


async def test_save_and_resume(world: World) -> None:
    attempt = begin(world)
    mcq, msq, tf, essay = attempt["questions"]
    option = mcq["question"]["options"][2]["id"]
    picks = [o["id"] for o in msq["question"]["options"][:2]]

    response = save(
        world,
        attempt["id"],
        {
            "exam_question_id": mcq["exam_question_id"],
            "selected_option_ids": [option],
            "client_revision": 1,
        },
        {
            "exam_question_id": msq["exam_question_id"],
            "selected_option_ids": picks,
            "client_revision": 1,
        },
        {
            "exam_question_id": essay["exam_question_id"],
            "text_answer": "Recursion calls itself.",
            "client_revision": 1,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["saved"]) == 3 and result["stale"] == []
    assert 0 < result["seconds_left"] <= 3600

    after = stored(world, attempt["id"])
    assert after[mcq["exam_question_id"]]["answer"]["selected_option_ids"] == [option]
    assert after[msq["exam_question_id"]]["answer"]["selected_option_ids"] == picks
    assert after[essay["exam_question_id"]]["answer"]["text_answer"] == "Recursion calls itself."
    assert after[tf["exam_question_id"]]["answer"] is None


async def test_old_or_repeated_saves_never_overwrite_newer_ones(world: World) -> None:
    attempt = begin(world)
    essay = attempt["questions"][3]["exam_question_id"]

    def write(text: str, revision: int) -> dict[str, Any]:
        return save(
            world,
            attempt["id"],
            {"exam_question_id": essay, "text_answer": text, "client_revision": revision},
        ).json()  # type: ignore[no-any-return]

    assert write("v5", 5)["saved"] == [essay]
    assert write("v3 arriving late", 3)["stale"] == [essay]  # out of order: ignored
    assert write("v5 again", 5)["stale"] == [essay]  # repeated: harmless
    assert stored(world, attempt["id"])[essay]["answer"] == {
        "selected_option_ids": None,
        "text_answer": "v5",
        "client_revision": 5,
    }
    assert write("v6", 6)["saved"] == [essay]
    assert stored(world, attempt["id"])[essay]["answer"]["text_answer"] == "v6"

    # Within one batch, the newest revision of a question wins.
    batch = save(
        world,
        attempt["id"],
        {"exam_question_id": essay, "text_answer": "v8", "client_revision": 8},
        {"exam_question_id": essay, "text_answer": "v7", "client_revision": 7},
    ).json()
    assert batch["saved"] == [essay]
    assert stored(world, attempt["id"])[essay]["answer"]["text_answer"] == "v8"


async def test_clearing_an_answer(world: World) -> None:
    attempt = begin(world)
    mcq = attempt["questions"][0]
    option = mcq["question"]["options"][0]["id"]
    eq = mcq["exam_question_id"]
    save(
        world,
        attempt["id"],
        {"exam_question_id": eq, "selected_option_ids": [option], "client_revision": 1},
    )
    save(
        world,
        attempt["id"],
        {"exam_question_id": eq, "selected_option_ids": [], "client_revision": 2},
    )
    assert stored(world, attempt["id"])[eq]["answer"]["selected_option_ids"] is None


async def test_answers_are_checked_against_the_exam(world: World) -> None:
    attempt = begin(world)
    mcq, msq, tf, essay = attempt["questions"]
    foreign_option = msq["question"]["options"][0]["id"]
    two = [o["id"] for o in mcq["question"]["options"][:2]]
    bad = [
        (
            {"exam_question_id": mcq["exam_question_id"], "selected_option_ids": [foreign_option]},
            "selected_option_ids",
        ),
        (
            {"exam_question_id": mcq["exam_question_id"], "selected_option_ids": two},
            "selected_option_ids",
        ),
        ({"exam_question_id": tf["exam_question_id"], "text_answer": "True"}, "text_answer"),
        (
            {
                "exam_question_id": essay["exam_question_id"],
                "selected_option_ids": [foreign_option],
            },
            "selected_option_ids",
        ),
        ({"exam_question_id": str(uuid.uuid4()), "text_answer": "x"}, "exam_question_id"),
    ]
    for answer, field in bad:
        response = save(world, attempt["id"], {**answer, "client_revision": 1})
        assert response.status_code == 422, answer
        assert response.json()["error"]["details"][0]["field"] == f"answers.0.{field}", answer
    huge = save(
        world,
        attempt["id"],
        {
            "exam_question_id": essay["exam_question_id"],
            "text_answer": "x" * 65_537,
            "client_revision": 1,
        },
    )
    assert huge.status_code == 422
    no_revision = save(
        world, attempt["id"], {"exam_question_id": essay["exam_question_id"], "text_answer": "x"}
    )
    assert no_revision.status_code == 422


async def test_flags(world: World) -> None:
    attempt = begin(world)
    eq = attempt["questions"][1]["exam_question_id"]
    url = f"/api/v1/attempts/{attempt['id']}/flags/{eq}"
    assert world.client.put(url, json={"marked": True}, headers=world.me).status_code == 204
    assert stored(world, attempt["id"])[eq]["marked_for_review"] is True
    world.client.put(url, json={"marked": False}, headers=world.me)
    assert stored(world, attempt["id"])[eq]["marked_for_review"] is False
    missing = f"/api/v1/attempts/{attempt['id']}/flags/{uuid.uuid4()}"
    assert world.client.put(missing, json={"marked": True}, headers=world.me).status_code == 404


async def test_deadline_and_grace(world: World) -> None:
    attempt = begin(world)
    essay = attempt["questions"][3]["exam_question_id"]
    answer = {"exam_question_id": essay, "text_answer": "x", "client_revision": 1}
    await world.set_attempt(
        attempt["id"],
        started_at=datetime.now(UTC) - timedelta(hours=1),
        deadline_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    assert save(world, attempt["id"], answer).status_code == 200  # within the 60 s grace

    await world.set_attempt(attempt["id"], deadline_at=datetime.now(UTC) - timedelta(seconds=61))
    late = save(world, attempt["id"], {**answer, "client_revision": 2})
    assert late.status_code == 409 and late.json()["error"]["code"] == "TIME_UP"


async def test_submitted_or_voided(world: World) -> None:
    attempt = begin(world)
    answer = {
        "exam_question_id": attempt["questions"][3]["exam_question_id"],
        "text_answer": "x",
        "client_revision": 1,
    }
    await world.set_attempt(attempt["id"], status="SUBMITTED", submitted_at=datetime.now(UTC))
    refused = save(world, attempt["id"], answer)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "ATTEMPT_SUBMITTED"
    await world.set_attempt(attempt["id"], status="VOIDED")
    assert save(world, attempt["id"], answer).status_code == 404


async def test_someone_elses_attempt(world: World) -> None:
    attempt = begin(world)
    async with tenant_session(world.factory, world.college.id) as s:
        other = User(email=f"o{uuid.uuid4().hex[:8]}@abc.edu", full_name="O", role="STUDENT")
        s.add(other)
        await s.commit()
    answer = {
        "exam_question_id": attempt["questions"][3]["exam_question_id"],
        "text_answer": "x",
        "client_revision": 1,
    }
    response = world.client.put(
        f"/api/v1/attempts/{attempt['id']}/answers",
        json={"answers": [answer]},
        headers=bearer(other, world.college),
    )
    assert response.status_code == 404


# ----------------------------------------------------------------------------- code drafts


async def coding_attempt(world: World) -> tuple[str, str, str]:
    """An attempt with a coding question, made directly (coding questions can't be published until
    they can be validated, E07). Returns (attempt id, coding exam-question id, written one)."""
    async with tenant_session(world.factory, world.college.id) as s:
        teacher = await s.scalar(select(User).where(User.role == "TEACHER"))
        assert teacher is not None
        now = datetime.now(UTC)
        exam = Exam(
            owner_id=teacher.id,
            title="Coding",
            status="PUBLISHED",
            open_at=now - timedelta(hours=1),
            close_at=now + timedelta(hours=2),
            duration_min=60,
        )
        s.add(exam)
        await s.flush()
        ids, snap = [], []
        for i, kind in enumerate(("CODING", "DESCRIPTIVE")):
            q = Question(owner_id=teacher.id, type=kind)
            s.add(q)
            await s.flush()
            v = QuestionVersion(
                question_id=q.id, version_no=1, body="Q", points=1, created_by=teacher.id
            )
            s.add(v)
            await s.flush()
            eq = ExamQuestion(
                exam_id=exam.id, question_id=q.id, order_index=i, pinned_version_id=v.id
            )
            s.add(eq)
            await s.flush()
            ids.append(eq.id)
            snap.append(
                {
                    "exam_question_id": str(eq.id),
                    "version_id": str(v.id),
                    "type": kind,
                    "body": "Q",
                    "points": "1.00",
                    "negative_marks": "0.00",
                    "options": [],
                }
            )
        version = ExamVersion(
            exam_id=exam.id,
            version_no=1,
            content_hash="0" * 64,
            snapshot={
                "title": "Coding",
                "total_points": "2.00",
                "questions": snap,
                "settings": {
                    "navigation_mode": "FREE",
                    "run_code_enabled": True,
                    "shuffle_questions": False,
                    "shuffle_options": False,
                },
            },
        )
        s.add(version)
        await s.flush()
        exam.published_version_id = version.id
        s.add(ExamAssignment(exam_id=exam.id, student_id=world.student.id, assigned_by=teacher.id))
        attempt = ExamAttempt(
            exam_id=exam.id,
            exam_version_id=version.id,
            student_id=world.student.id,
            deadline_at=now + timedelta(hours=1),
            shuffle_seed=1,
        )
        s.add(attempt)
        await s.flush()
        for position, eq_id in enumerate(ids, start=1):
            s.add(AttemptQuestion(attempt_id=attempt.id, exam_question_id=eq_id, position=position))
        await s.commit()
        return str(attempt.id), str(ids[0]), str(ids[1])


async def test_code_drafts(world: World) -> None:
    attempt_id, coding, written = await coding_attempt(world)

    def draft(question: str, source: str, revision: int, language: str = "python312"):  # type: ignore[no-untyped-def]
        return world.client.put(
            f"/api/v1/attempts/{attempt_id}/drafts/{question}",
            json={"language_key": language, "source": source, "client_revision": revision},
            headers=world.me,
        )

    assert draft(coding, "print(1)", 1).json()["saved"] is True
    assert draft(coding, "print(0)", 1).json()["saved"] is False  # not newer: ignored
    assert draft(coding, "print(2)", 2).json()["saved"] is True
    assert (
        draft(coding, "int main(){}", 1, "cpp17").json()["saved"] is True
    )  # one draft per language
    async with tenant_session(world.factory, world.college.id) as s:
        drafts = {
            d.language_key: d.source
            for d in await s.scalars(
                select(CodeDraft).where(CodeDraft.attempt_id == uuid.UUID(attempt_id))
            )
        }
    assert drafts == {"python312": "print(2)", "cpp17": "int main(){}"}
    # The exam screen gets them back on resume, newest first.
    resumed = world.client.get(f"/api/v1/attempts/{attempt_id}", headers=world.me).json()
    item = next(i for i in resumed["questions"] if i["exam_question_id"] == coding)
    assert [(d["language_key"], d["source"], d["client_revision"]) for d in item["drafts"]] == [
        ("cpp17", "int main(){}", 1),
        ("python312", "print(2)", 2),
    ]

    assert draft(written, "print(1)", 1).status_code == 422  # not a coding question
    assert draft(coding, "x", 3, "cobol").status_code == 422  # unknown language
    coding_answer = world.client.put(
        f"/api/v1/attempts/{attempt_id}/answers",
        json={"answers": [{"exam_question_id": coding, "text_answer": "x", "client_revision": 1}]},
        headers=world.me,
    )
    assert coding_answer.status_code == 422  # coding answers are drafts and submissions
