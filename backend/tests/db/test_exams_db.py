"""Exam tables and the frozen exam version (PRD EX-06, architecture D-11).

Runs as the app's own database user: these rules hold even if application code got them wrong.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import SessionFactory, create_session_factory, tenant_session
from app.exams.models import Exam, ExamAssignment, ExamQuestion, ExamVersion
from app.platform.models import Institution
from app.questions.models import Question, QuestionVersion
from app.users.models import User, UserGroup
from cli import commands
from tests.db.question_helpers import purge_institutions

NOW = datetime.now(UTC)


@dataclass
class World:
    factory: SessionFactory
    college: Institution
    teacher: User
    student: User
    questions: list[Question]
    exam: Exam


@pytest.fixture
async def world(app_engine: AsyncEngine, migrator_engine: AsyncEngine) -> AsyncIterator[World]:
    factory = create_session_factory(app_engine)
    college = await commands.create_institution(factory, f"Exams DB test {uuid.uuid4().hex[:8]}")
    async with tenant_session(factory, college.id) as s:
        teacher = User(email=f"t{uuid.uuid4().hex[:8]}@abc.edu", full_name="T", role="TEACHER")
        student = User(email=f"s{uuid.uuid4().hex[:8]}@abc.edu", full_name="S", role="STUDENT")
        s.add_all([teacher, student])
        await s.flush()
        questions = []
        for i in range(3):
            q = Question(owner_id=teacher.id, type="DESCRIPTIVE")
            s.add(q)
            await s.flush()
            v = QuestionVersion(
                question_id=q.id, version_no=1, body=f"Q{i}", points=1, created_by=teacher.id
            )
            s.add(v)
            await s.flush()
            q.current_version_id = v.id
            questions.append(q)
        exam = Exam(owner_id=teacher.id, title="Mid-term")
        s.add(exam)
        await s.commit()
    yield World(factory, college, teacher, student, questions, exam)
    await purge_institutions(migrator_engine, [college.id])


async def test_defaults_match_the_prd(world: World) -> None:
    async with tenant_session(world.factory, world.college.id) as s:
        exam = await s.get(Exam, world.exam.id)
        assert exam is not None
        assert (exam.status, exam.navigation_mode, exam.release_policy) == (
            "DRAFT",
            "FREE",
            "MANUAL",
        )
        assert (exam.shuffle_questions, exam.shuffle_options, exam.run_code_enabled) == (
            False,
            False,
            True,
        )
        assert (exam.counted_submission, exam.proctoring_mode) == ("BEST", "OFF")
        assert exam.proctoring_detectors == {
            "sensitivity": "STANDARD",
            "gaze": False,
            "books": False,
        }
        assert exam.open_at is None and exam.duration_min is None  # drafts may leave them empty


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"status": "LIVE"}, "ck_exam_status"),
        ({"navigation_mode": "RANDOM"}, "ck_exam_navigation_mode"),
        ({"release_policy": "AUTO"}, "ck_exam_release_policy"),
        ({"counted_submission": "FIRST"}, "ck_exam_counted_submission"),
        ({"proctoring_mode": "AUDIO"}, "ck_exam_proctoring_mode"),
        ({"open_at": NOW, "close_at": NOW - timedelta(hours=1)}, "ck_exam_window_order"),
        ({"duration_min": 0}, "ck_exam_duration_range"),
        ({"duration_min": 601}, "ck_exam_duration_range"),
        ({"pass_percent": Decimal("100.5")}, "ck_exam_pass_percent_range"),
    ],
)
async def test_exam_settings_are_checked(
    world: World, values: dict[str, object], constraint: str
) -> None:
    async with tenant_session(world.factory, world.college.id) as s:
        with pytest.raises(IntegrityError, match=constraint):
            await s.execute(update(Exam).where(Exam.id == world.exam.id).values(**values))


async def test_questions_in_order_and_reorder_by_swapping(world: World) -> None:
    async with tenant_session(world.factory, world.college.id) as s:
        rows = [
            ExamQuestion(exam_id=world.exam.id, question_id=q.id, order_index=i)
            for i, q in enumerate(world.questions)
        ]
        s.add_all(rows)
        await s.commit()
        # Swap the first two in one transaction: allowed, uniqueness is checked at commit.
        await s.execute(
            update(ExamQuestion).where(ExamQuestion.id == rows[0].id).values(order_index=1)
        )
        await s.execute(
            update(ExamQuestion).where(ExamQuestion.id == rows[1].id).values(order_index=0)
        )
        await s.commit()
        order = await s.scalars(
            select(ExamQuestion.question_id)
            .where(ExamQuestion.exam_id == world.exam.id)
            .order_by(ExamQuestion.order_index)
        )
        assert list(order) == [world.questions[1].id, world.questions[0].id, world.questions[2].id]

    async with tenant_session(world.factory, world.college.id) as s:
        await s.execute(
            update(ExamQuestion).where(ExamQuestion.id == rows[2].id).values(order_index=0)
        )
        with pytest.raises(IntegrityError, match="uq_exam_question_exam_id_order_index"):
            await s.commit()  # a real clash is still refused

    async with tenant_session(world.factory, world.college.id) as s:
        s.add(ExamQuestion(exam_id=world.exam.id, question_id=world.questions[0].id, order_index=9))
        with pytest.raises(IntegrityError, match="uq_exam_question_exam_id_question_id"):
            await s.flush()  # the same question twice


async def test_one_assignment_per_student(world: World) -> None:
    async with tenant_session(world.factory, world.college.id) as s:
        group = UserGroup(name="CSE-A")
        s.add(group)
        await s.flush()
        s.add(
            ExamAssignment(
                exam_id=world.exam.id,
                student_id=world.student.id,
                assigned_by=world.teacher.id,
                via_group_id=group.id,
            )
        )
        await s.commit()
        await s.execute(delete(UserGroup).where(UserGroup.id == group.id))
        await s.commit()  # deleting the group keeps the assignment
        kept = await s.scalar(select(ExamAssignment).where(ExamAssignment.exam_id == world.exam.id))
        assert kept is not None and kept.via_group_id is None

        s.add(
            ExamAssignment(
                exam_id=world.exam.id, student_id=world.student.id, assigned_by=world.teacher.id
            )
        )
        with pytest.raises(IntegrityError, match="uq_exam_assignment_exam_id_student_id"):
            await s.flush()


async def publish(world: World) -> ExamVersion:
    async with tenant_session(world.factory, world.college.id) as s:
        version = ExamVersion(
            exam_id=world.exam.id,
            version_no=1,
            snapshot={"title": "Mid-term", "questions": []},
            content_hash="0" * 64,
        )
        s.add(version)
        await s.flush()
        await s.execute(
            update(Exam)
            .where(Exam.id == world.exam.id)
            .values(status="PUBLISHED", published_version_id=version.id)
        )
        await s.commit()
        return version


async def test_published_version_is_frozen(world: World) -> None:
    version = await publish(world)
    for statement in (
        update(ExamVersion)
        .where(ExamVersion.id == version.id)
        .values(snapshot={"title": "Changed"}),
        update(ExamVersion).where(ExamVersion.id == version.id).values(content_hash="1" * 64),
        delete(ExamVersion).where(ExamVersion.id == version.id),
        delete(Exam).where(Exam.id == world.exam.id),  # would cascade into the version
    ):
        async with tenant_session(world.factory, world.college.id) as s:
            with pytest.raises(DBAPIError, match="frozen"):
                await s.execute(statement)

    async with tenant_session(world.factory, world.college.id) as s:
        kept = await s.get(ExamVersion, version.id)
        assert kept is not None and kept.snapshot == {"title": "Mid-term", "questions": []}
        # The exam row itself stays editable (window end, archive) as the API allows.
        await s.execute(update(Exam).where(Exam.id == world.exam.id).values(status="ARCHIVED"))
        await s.commit()


async def test_a_draft_exam_can_be_deleted(world: World) -> None:
    async with tenant_session(world.factory, world.college.id) as s:
        s.add(ExamQuestion(exam_id=world.exam.id, question_id=world.questions[0].id, order_index=0))
        await s.commit()
        await s.execute(delete(Exam).where(Exam.id == world.exam.id))
        await s.commit()
        assert (
            await s.scalar(select(ExamQuestion.id).where(ExamQuestion.exam_id == world.exam.id))
            is None
        )
