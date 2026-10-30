"""Teachers marking descriptive answers (PRD GRD-03; TCK-0904).

The grading queue lists the exam's descriptive questions, each with the answers to mark. Students
are anonymous by default ("Student 14", numbered in the order they started); names come only when
the teacher asks. A blank answer scored 0 automatically and isn't in the queue.

A mark is 0 to the question's points, with optional feedback. It goes on the answer
(`manual_score`, which `score` follows), the audit log keeps the old and new mark, and the
attempt's grading status is worked out again.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.attempt import snapshot_of
from app.attempts.models import Answer, ExamAttempt
from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import get_owned, not_found
from app.core.errors import AppError
from app.exams.models import Exam, ExamVersion
from app.grading.status import ENDED, refresh
from app.users.models import User

Feedback = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]


class MarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: Decimal = Field(ge=0, decimal_places=2, description="0 to the question's points")
    feedback: Feedback | None = None


class Mark(BaseModel):
    attempt_id: uuid.UUID
    exam_question_id: uuid.UUID
    score: Decimal
    feedback: str | None
    graded_at: datetime
    grading_status: str


class AnswerToMark(BaseModel):
    attempt_id: uuid.UUID
    student_label: str = Field(description='"Student 14": stable within this exam')
    student_name: str | None = Field(description="Only when names were asked for")
    text_answer: str
    score: Decimal | None = Field(description="The teacher's mark; null until marked")
    feedback: str | None


class QuestionToMark(BaseModel):
    exam_question_id: uuid.UUID
    position: int
    body: str
    points: Decimal
    rubric: str | None
    marked: int
    answers: list[AnswerToMark]


class GradingQueue(BaseModel):
    questions: list[QuestionToMark]
    marked: int
    total: int


def _invalid(message: str) -> AppError:
    return AppError(
        "VALIDATION_ERROR",
        message,
        status_code=422,
        details=[{"field": "score", "message": message, "type": "MARK_OUT_OF_RANGE"}],
    )


async def queue(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID, *, show_names: bool
) -> GradingQueue:
    exam = await get_owned(
        session, Exam, exam_id, principal, owned=lambda e: e.owner_id == principal.user_id
    )
    version = (
        await session.get(ExamVersion, exam.published_version_id)
        if exam.published_version_id
        else None
    )
    if version is None:
        return GradingQueue(questions=[], marked=0, total=0)
    attempts = list(
        await session.scalars(
            select(ExamAttempt)
            .where(
                ExamAttempt.exam_id == exam.id,
                ExamAttempt.is_preview.is_(False),
                ExamAttempt.status.in_(ENDED),
            )
            .order_by(ExamAttempt.started_at, ExamAttempt.id)
        )
    )
    label = {a.id: f"Student {n}" for n, a in enumerate(attempts, start=1)}
    names: dict[uuid.UUID, str] = {}
    if show_names and attempts:
        students = {a.student_id for a in attempts}
        rows = await session.execute(select(User.id, User.full_name).where(User.id.in_(students)))
        by_user = {uid: name for uid, name in rows.tuples()}
        names = {a.id: by_user.get(a.student_id, "") for a in attempts}
    answers = (
        list(
            await session.scalars(
                select(Answer).where(Answer.attempt_id.in_([a.id for a in attempts]))
            )
        )
        if attempts
        else []
    )
    by_question: dict[uuid.UUID, list[Answer]] = {}
    for answer in answers:
        if (answer.text_answer or "").strip():
            by_question.setdefault(answer.exam_question_id, []).append(answer)

    questions: list[QuestionToMark] = []
    for position, q in enumerate(version.snapshot["questions"], start=1):
        if q["type"] != "DESCRIPTIVE":
            continue
        rows_ = sorted(
            by_question.get(uuid.UUID(q["exam_question_id"]), []),
            key=lambda a: int(label[a.attempt_id].split()[1]),
        )
        questions.append(
            QuestionToMark(
                exam_question_id=q["exam_question_id"],
                position=position,
                body=q["body"],
                points=Decimal(str(q["points"])),
                rubric=q.get("rubric"),
                marked=sum(a.manual_score is not None for a in rows_),
                answers=[
                    AnswerToMark(
                        attempt_id=a.attempt_id,
                        student_label=label[a.attempt_id],
                        student_name=names.get(a.attempt_id) if show_names else None,
                        text_answer=a.text_answer or "",
                        score=a.manual_score,
                        feedback=a.feedback,
                    )
                    for a in rows_
                ],
            )
        )
    return GradingQueue(
        questions=questions,
        marked=sum(q.marked for q in questions),
        total=sum(len(q.answers) for q in questions),
    )


async def mark(
    session: AsyncSession,
    principal: Principal,
    attempt_id: uuid.UUID,
    exam_question_id: uuid.UUID,
    body: MarkIn,
) -> Mark:
    row = (
        await session.execute(
            select(ExamAttempt)
            .join(Exam, Exam.id == ExamAttempt.exam_id)
            .where(ExamAttempt.id == attempt_id, Exam.owner_id == principal.user_id)
            .with_for_update(of=ExamAttempt)
        )
    ).scalar_one_or_none()
    if row is None or row.institution_id != principal.institution_id:
        raise not_found()
    attempt = row
    question = _question(await snapshot_of(session, attempt), exam_question_id)
    if attempt.status not in ENDED:
        raise AppError(
            "ATTEMPT_NOT_ENDED", "This attempt hasn't been submitted yet.", status_code=409
        )
    points = Decimal(str(question["points"]))
    if body.score > points:
        raise _invalid(f"A mark is between 0 and {points}.")
    answer = await session.scalar(
        select(Answer)
        .where(Answer.attempt_id == attempt.id, Answer.exam_question_id == exam_question_id)
        .with_for_update()
    )
    if answer is None or not (answer.text_answer or "").strip():
        raise AppError("NOTHING_TO_MARK", "The student left this question blank.", status_code=409)
    old = answer.manual_score
    now = datetime.now(UTC)
    value = body.score.quantize(Decimal("0.01"))
    answer.manual_score = answer.score = value
    answer.feedback = body.feedback or None
    answer.graded_by, answer.graded_at = principal.user_id, now
    record(
        session,
        "answer.marked",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="attempt",
        target_id=attempt.id,
        changes={
            "exam_question_id": str(exam_question_id),
            "score": {"old": None if old is None else str(old), "new": str(value)},
        },
    )
    status = await refresh(session, attempt)
    await session.commit()
    return Mark(
        attempt_id=attempt.id,
        exam_question_id=exam_question_id,
        score=value,
        feedback=answer.feedback,
        graded_at=now,
        grading_status=status,
    )


def _question(snapshot: dict[str, Any], exam_question_id: uuid.UUID) -> dict[str, Any]:
    for q in snapshot["questions"]:
        if q["exam_question_id"] == str(exam_question_id) and q["type"] == "DESCRIPTIVE":
            return q  # type: ignore[no-any-return]
    raise not_found()  # not in this attempt, or not a question a teacher marks
