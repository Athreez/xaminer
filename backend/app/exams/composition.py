"""The questions in an exam (PRD EX-02, ACC-04).

The page sends the whole ordered list; the server works out what was added, removed, moved or
re-marked and saves it in one transaction, so the order is never half-changed. Teachers may add
their own questions and those colleagues share with the institution (the same rule as reading the
question bank). Only drafts change: a published exam's questions are frozen in its version.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import ExamAttempt
from app.audit.service import record
from app.auth.tokens import Principal
from app.core.errors import AppError
from app.exams.models import ExamQuestion
from app.exams.service import get_own
from app.questions.models import Question, QuestionVersion
from app.questions.schemas import QuestionType
from app.questions.service import title_of
from app.users.models import User

MAX_QUESTIONS = 200
Marks = Annotated[Decimal, Field(gt=0, le=1000, max_digits=6, decimal_places=2)]
Penalty = Annotated[Decimal, Field(ge=0, le=1000, max_digits=6, decimal_places=2)]


class ExamQuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: uuid.UUID
    points: Marks | None = Field(default=None, description="Null: the question's own points")
    negative_marks: Penalty | None = Field(default=None, description="Null: the question's own")


class ExamQuestionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[ExamQuestionIn] = Field(max_length=MAX_QUESTIONS, description="In exam order")


class ExamQuestionView(BaseModel):
    question_id: uuid.UUID
    position: int = Field(description="1 for the first question")
    title: str
    type: QuestionType
    owner_name: str
    is_mine: bool
    version_no: int = Field(description="Pinned version once published, else the current one")
    points: Decimal = Field(description="Marks in this exam")
    negative_marks: Decimal
    points_override: Decimal | None = Field(description="Set by this exam, or null")
    negative_marks_override: Decimal | None
    question_points: Decimal = Field(description="The question's own points")


class ExamQuestions(BaseModel):
    questions: list[ExamQuestionView]
    total_points: Decimal


def _invalid(
    field: str, message: str, status: int = 422, code: str = "VALIDATION_FAILED"
) -> AppError:
    return AppError(
        code,
        message,
        status_code=status,
        details=[{"field": field, "message": message, "type": "exam"}],
    )


async def list_questions(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID
) -> ExamQuestions:
    shown = func.coalesce(ExamQuestion.pinned_version_id, Question.current_version_id)
    rows = (
        await session.execute(
            select(ExamQuestion, Question, QuestionVersion, User.full_name)
            .join(Question, Question.id == ExamQuestion.question_id)
            .join(QuestionVersion, QuestionVersion.id == shown)
            .join(User, User.id == Question.owner_id)
            .where(ExamQuestion.exam_id == exam_id)
            .order_by(ExamQuestion.order_index)
        )
    ).all()
    views = [
        ExamQuestionView(
            question_id=q.id,
            position=i + 1,
            title=title_of(v.body),
            type=q.type,  # type: ignore[arg-type]
            owner_name=owner,
            is_mine=q.owner_id == principal.user_id,
            version_no=v.version_no,
            points=eq.points if eq.points is not None else v.points,
            negative_marks=eq.negative_marks if eq.negative_marks is not None else v.negative_marks,
            points_override=eq.points,
            negative_marks_override=eq.negative_marks,
            question_points=v.points,
        )
        for i, (eq, q, v, owner) in enumerate(rows)
    ]
    return ExamQuestions(questions=views, total_points=sum((v.points for v in views), Decimal(0)))


async def get_questions(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID
) -> ExamQuestions:
    exam = await get_own(session, principal, exam_id)
    return await list_questions(session, principal, exam.id)


async def set_questions(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID, body: ExamQuestionsIn
) -> ExamQuestions:
    exam = await get_own(session, principal, exam_id)
    if exam.status != "DRAFT":
        raise _invalid(
            "questions",
            "The exam is published, so its questions are fixed."
            if exam.status == "PUBLISHED"
            else "This exam is archived and can't be changed.",
            409,
            "EXAM_PUBLISHED" if exam.status == "PUBLISHED" else "EXAM_ARCHIVED",
        )

    wanted = [item.question_id for item in body.questions]
    seen: set[uuid.UUID] = set()
    for i, qid in enumerate(wanted):
        if qid in seen:
            raise _invalid(
                f"questions.{i}.question_id", f"Question {i + 1} is already in the exam."
            )
        seen.add(qid)

    # Usable: your own or shared with the institution, and not archived (ACC-04).
    usable = {
        q.id: (q, v)
        for q, v in (
            await session.execute(
                select(Question, QuestionVersion)
                .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
                .where(
                    Question.id.in_(wanted),
                    Question.archived_at.is_(None),
                    or_(
                        Question.owner_id == principal.user_id, Question.visibility == "INSTITUTION"
                    ),
                )
            )
        ).all()
    }
    for i, item in enumerate(body.questions):
        found = usable.get(item.question_id)
        if found is None:
            raise _invalid(
                f"questions.{i}.question_id",
                f"Question {i + 1} can't be used: it doesn't exist, isn't shared with you, "
                "or is archived.",
            )
        points = item.points if item.points is not None else found[1].points
        penalty = (
            item.negative_marks if item.negative_marks is not None else found[1].negative_marks
        )
        if penalty > points:
            raise _invalid(
                f"questions.{i}.negative_marks",
                f"Question {i + 1}: negative marks can't be more than its points.",
            )

    existing = {
        eq.question_id: eq
        for eq in await session.scalars(select(ExamQuestion).where(ExamQuestion.exam_id == exam.id))
    }
    # What changes, worked out before anything is touched.
    before = [qid for qid, _ in sorted(existing.items(), key=lambda kv: kv[1].order_index)]
    removed = [qid for qid in before if qid not in seen]
    added = [qid for qid in wanted if qid not in existing]
    changes: dict[str, Any] = {}
    if added:
        changes["added"] = [str(q) for q in added]
    if removed:
        changes["removed"] = [str(q) for q in removed]
    if [q for q in before if q in seen] != [q for q in wanted if q in existing]:
        changes["reordered"] = True
    if any(
        (existing[i.question_id].points, existing[i.question_id].negative_marks)
        != (i.points, i.negative_marks)
        for i in body.questions
        if i.question_id in existing
    ):
        changes["marks_changed"] = True
    if not changes:
        return await list_questions(session, principal, exam.id)

    if removed:
        # A draft's preview attempts point at its questions; they are the teacher's throwaway test
        # runs (a draft has no student attempts), so they go rather than block the removal.
        await session.execute(
            delete(ExamAttempt).where(ExamAttempt.exam_id == exam.id, ExamAttempt.is_preview)
        )
        await session.execute(
            delete(ExamQuestion).where(
                ExamQuestion.exam_id == exam.id, ExamQuestion.question_id.in_(removed)
            )
        )
    for index, item in enumerate(body.questions):
        row = existing.get(item.question_id)
        if row is None:
            session.add(
                ExamQuestion(
                    exam_id=exam.id,
                    question_id=item.question_id,
                    order_index=index,
                    points=item.points,
                    negative_marks=item.negative_marks,
                )
            )
        else:  # positions are checked for uniqueness at commit, so moves can pass each other
            row.order_index, row.points, row.negative_marks = (
                index,
                item.points,
                item.negative_marks,
            )
    record(
        session,
        "exam.questions_changed",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="exam",
        target_id=exam.id,
        changes=changes,
    )
    exam.updated_at = datetime.now(UTC)
    await session.commit()
    session.expire_all()  # answer with what was stored (e.g. 4 -> 4.00), like a fresh read
    return await list_questions(session, principal, exam_id)
