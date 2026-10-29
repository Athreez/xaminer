"""Attempt tables (PRD ATT-02, ATT-03, ATT-08). Runs as the app's own database user."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.attempts.models import Answer, AttemptQuestion, CodeDraft, ExamAttempt
from app.db.session import SessionFactory, create_session_factory, tenant_session
from app.exams.models import Exam, ExamQuestion, ExamVersion
from app.platform.models import Institution
from app.questions.models import Question, QuestionVersion
from app.users.models import User
from cli import commands
from tests.db.question_helpers import purge_institutions

NOW = datetime.now(UTC)


@dataclass
class World:
    factory: SessionFactory
    college: Institution
    exam: Exam
    version: ExamVersion
    exam_question: ExamQuestion
    student: User

    def attempt(self, **overrides: object) -> ExamAttempt:
        values: dict[str, object] = {
            "exam_id": self.exam.id,
            "exam_version_id": self.version.id,
            "student_id": self.student.id,
            "deadline_at": NOW + timedelta(hours=1),
            "shuffle_seed": 42,
        }
        return ExamAttempt(**(values | overrides))


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(factory, f"Attempts DB test {uuid.uuid4().hex[:8]}")
    async with tenant_session(factory, college.id) as s:
        teacher = User(email=f"t{uuid.uuid4().hex[:8]}@abc.edu", full_name="T", role="TEACHER")
        student = User(email=f"s{uuid.uuid4().hex[:8]}@abc.edu", full_name="S", role="STUDENT")
        s.add_all([teacher, student])
        await s.flush()
        question = Question(owner_id=teacher.id, type="DESCRIPTIVE")
        s.add(question)
        await s.flush()
        qv = QuestionVersion(
            question_id=question.id, version_no=1, body="Q", points=1, created_by=teacher.id
        )
        s.add(qv)
        await s.flush()
        question.current_version_id = qv.id
        exam = Exam(owner_id=teacher.id, title="E", status="PUBLISHED")
        s.add(exam)
        await s.flush()
        eq = ExamQuestion(
            exam_id=exam.id, question_id=question.id, order_index=0, pinned_version_id=qv.id
        )
        version = ExamVersion(exam_id=exam.id, version_no=1, snapshot={}, content_hash="0" * 64)
        s.add_all([eq, version])
        await s.commit()
    yield World(factory, college, exam, version, eq, student)
    await purge_institutions(migrator_engine, [college.id])


async def test_two_simultaneous_starts_make_one_attempt(world: World) -> None:
    """ATT-02: both requests race to insert; exactly one wins."""

    async def start() -> bool:
        async with tenant_session(world.factory, world.college.id) as s:
            s.add(world.attempt())
            try:
                await s.commit()
                return True
            except IntegrityError as exc:
                assert "uq_exam_attempt_one_active" in str(exc)
                return False

    assert sorted(await asyncio.gather(start(), start())) == [False, True]
    async with tenant_session(world.factory, world.college.id) as s:
        count = len(
            list(
                await s.scalars(select(ExamAttempt.id).where(ExamAttempt.exam_id == world.exam.id))
            )
        )
    assert count == 1


async def test_a_voided_attempt_allows_a_new_one(world: World) -> None:
    async with tenant_session(world.factory, world.college.id) as s:
        first = world.attempt()
        s.add(first)
        await s.commit()
        await s.execute(
            update(ExamAttempt).where(ExamAttempt.id == first.id).values(status="VOIDED")
        )
        await s.commit()
        s.add(world.attempt())
        await s.commit()  # allowed: the earlier one is voided


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"status": "PAUSED"}, "ck_exam_attempt_status"),
        ({"grading_status": "DONE"}, "ck_exam_attempt_grading_status"),
        ({"status": "SUBMITTED"}, "ck_exam_attempt_submitted_has_time"),
        ({"extra_minutes": -1}, "ck_exam_attempt_extra_minutes_range"),
        (
            {"started_at": NOW, "deadline_at": NOW - timedelta(minutes=1)},
            "ck_exam_attempt_deadline_after_start",
        ),
    ],
    ids=[
        "status",
        "grading-status",
        "submitted-without-time",
        "negative-extension",
        "deadline-before-start",
    ],
)
async def test_attempt_rules(world: World, overrides: dict[str, object], constraint: str) -> None:
    async with tenant_session(world.factory, world.college.id) as s:
        s.add(world.attempt(**overrides))
        with pytest.raises(IntegrityError, match=constraint):
            await s.flush()


async def test_question_order_answers_and_drafts(world: World) -> None:
    async with tenant_session(world.factory, world.college.id) as s:
        attempt = world.attempt()
        s.add(attempt)
        await s.flush()
        attempt_id = attempt.id  # read before commit: later access would reload it
        s.add(
            AttemptQuestion(
                attempt_id=attempt_id,
                exam_question_id=world.exam_question.id,
                position=1,
                option_order=[2, 0, 1],
            )
        )
        s.add(
            Answer(
                attempt_id=attempt_id,
                exam_question_id=world.exam_question.id,
                text_answer="An answer",
                client_revision=3,
            )
        )
        s.add(
            CodeDraft(
                attempt_id=attempt_id,
                exam_question_id=world.exam_question.id,
                language_key="python312",
                source="print(1)",
            )
        )
        await s.commit()
        stored = await s.scalar(
            select(AttemptQuestion).where(AttemptQuestion.attempt_id == attempt_id)
        )
        assert (
            stored is not None
            and stored.option_order == [2, 0, 1]
            and stored.marked_for_review is False
        )

        s.add(
            AttemptQuestion(
                attempt_id=attempt_id, exam_question_id=world.exam_question.id, position=2
            )
        )
        with pytest.raises(IntegrityError, match="uq_attempt_question_attempt_id_exam_question_id"):
            await s.flush()
        await s.rollback()

        with pytest.raises(IntegrityError, match="ck_answer_text_answer_length"):
            await s.execute(
                update(Answer)
                .where(Answer.attempt_id == attempt_id)
                .values(text_answer="x" * 65_537)
            )
        await s.rollback()

        s.add(
            CodeDraft(
                attempt_id=attempt_id,
                exam_question_id=world.exam_question.id,
                language_key="cobol",
                source="",
            )
        )
        with pytest.raises(IntegrityError, match="fk_code_draft_language_key_language"):
            await s.flush()
