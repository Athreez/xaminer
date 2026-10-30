"""Results for teachers and students (PRD GRD-05..07, GRD-09; TCK-0905, TCK-0906).

Teachers (own exams): every attempt's result and grading status, one attempt in detail, and
release. Release is refused until every attempt has ended and is fully graded; it can be pressed
again later for attempts graded since.

Students: their own results, **released only**. An unreleased result answers 404, exactly like
one that doesn't exist. A student's view has their own answers and scores, teacher feedback and
coding verdicts with passed counts, never correct answers, rubrics, hidden test cases or
proctoring events (SECURITY_AND_ACCESS.md § 4.2, 4.3).
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.attempt import snapshot_of
from app.attempts.models import Answer, ExamAttempt
from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import get_owned, not_found
from app.core.errors import AppError
from app.exams.models import Exam
from app.execution.models import CodingEvaluation, CodingSubmission
from app.results.models import Result, ResultRevision
from app.users.models import User

# ----------------------------------------------------------------------------- shapes


class ResultRow(BaseModel):
    attempt_id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    student_email: str
    status: str
    grading_status: str
    submitted_at: datetime | None
    total_score: Decimal | None
    max_score: Decimal | None
    percentage: Decimal | None
    passed: bool | None
    integrity_outcome: str | None
    released_at: datetime | None


class ExamResults(BaseModel):
    exam_id: uuid.UUID
    title: str
    release_policy: str
    pass_percent: Decimal | None
    rows: list[ResultRow]
    can_release: bool
    blocked_reason: str | None = Field(description="Why release is not possible right now")
    unreleased: int = Field(description="Computed results not released yet")


class CodingOutcome(BaseModel):
    submission_id: uuid.UUID
    language_key: str
    verdict: str | None
    passed_weight: int | None
    total_weight: int | None
    score: Decimal | None


class QuestionResult(BaseModel):
    exam_question_id: uuid.UUID
    position: int
    type: str
    body: str
    points: Decimal
    score: Decimal | None
    feedback: str | None
    selected_labels: list[str] = []
    text_answer: str | None = None
    coding: CodingOutcome | None = None


class TeacherQuestionResult(QuestionResult):
    auto_score: Decimal | None
    manual_score: Decimal | None
    correct_labels: list[str] = []
    rubric: str | None = None


class Revision(BaseModel):
    old_score: Decimal
    new_score: Decimal
    reason: str
    created_at: datetime


class AttemptResult(BaseModel):
    """What a student sees for a released result."""

    attempt_id: uuid.UUID
    exam_id: uuid.UUID
    exam_title: str
    submitted_at: datetime | None
    total_score: Decimal
    max_score: Decimal
    percentage: Decimal
    passed: bool | None
    integrity_outcome: str | None
    released_at: datetime
    questions: list[QuestionResult]
    revisions: list[Revision]


class TeacherAttemptResult(BaseModel):
    attempt_id: uuid.UUID
    student_name: str
    student_email: str
    status: str
    grading_status: str
    submitted_at: datetime | None
    result: ResultRow
    questions: list[TeacherQuestionResult]
    revisions: list[Revision]


class StudentResultItem(BaseModel):
    attempt_id: uuid.UUID
    exam_id: uuid.UUID
    exam_title: str
    submitted_at: datetime | None
    released: bool
    total_score: Decimal | None = None
    max_score: Decimal | None = None
    percentage: Decimal | None = None
    passed: bool | None = None


class StudentResults(BaseModel):
    items: list[StudentResultItem]


# ----------------------------------------------------------------------------- teacher


async def _own_exam(session: AsyncSession, principal: Principal, exam_id: uuid.UUID) -> Exam:
    return await get_owned(
        session, Exam, exam_id, principal, owned=lambda e: e.owner_id == principal.user_id
    )


def _row(attempt: ExamAttempt, student: User, result: Result | None) -> ResultRow:
    return ResultRow(
        attempt_id=attempt.id,
        student_id=student.id,
        student_name=student.full_name,
        student_email=student.email,
        status=attempt.status,
        grading_status=attempt.grading_status,
        submitted_at=attempt.submitted_at,
        total_score=result.total_score if result else None,
        max_score=result.max_score if result else None,
        percentage=result.percentage if result else None,
        passed=result.passed if result else None,
        integrity_outcome=result.integrity_outcome if result else None,
        released_at=result.released_at if result else None,
    )


async def exam_results(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID
) -> ExamResults:
    exam = await _own_exam(session, principal, exam_id)
    rows = (
        await session.execute(
            select(ExamAttempt, User, Result)
            .join(User, User.id == ExamAttempt.student_id)
            .outerjoin(Result, Result.attempt_id == ExamAttempt.id)
            .where(
                ExamAttempt.exam_id == exam.id,
                ExamAttempt.is_preview.is_(False),
                ExamAttempt.status != "VOIDED",
            )
            .order_by(User.full_name, ExamAttempt.id)
        )
    ).tuples()
    out = [_row(a, u, r) for a, u, r in rows]
    blocked = _blocked_reason(out)
    unreleased = sum(r.total_score is not None and r.released_at is None for r in out)
    return ExamResults(
        exam_id=exam.id,
        title=exam.title,
        release_policy=exam.release_policy,
        pass_percent=exam.pass_percent,
        rows=out,
        can_release=blocked is None,
        blocked_reason=blocked,
        unreleased=unreleased,
    )


def _blocked_reason(rows: list[ResultRow]) -> str | None:
    def count(n: int, what: str) -> str:
        return f"{n} {what}" if n != 1 else f"1 {what.replace('attempts are', 'attempt is')}"

    in_progress = sum(r.status == "IN_PROGRESS" for r in rows)
    grading = sum(r.status != "IN_PROGRESS" and r.grading_status != "COMPLETE" for r in rows)
    if in_progress:
        return f"{count(in_progress, 'attempts are')} still in progress."
    if grading:
        return f"{count(grading, 'attempts are')} still being graded."
    if not any(r.released_at is None and r.total_score is not None for r in rows):
        return "Nothing to release." if rows else "No one has submitted yet."
    return None


async def release(session: AsyncSession, principal: Principal, exam_id: uuid.UUID) -> ExamResults:
    exam = await _own_exam(session, principal, exam_id)
    current = await exam_results(session, principal, exam_id)
    if current.blocked_reason is not None:
        raise AppError(
            "RESULTS_NOT_READY",
            current.blocked_reason,
            status_code=409,
            details=[{"field": "exam", "message": current.blocked_reason, "type": "grading"}],
        )
    now = datetime.now(UTC)
    ids = [r.attempt_id for r in current.rows if r.released_at is None]
    for result in await session.scalars(
        select(Result).where(Result.attempt_id.in_(ids)).with_for_update()
    ):
        result.released_at = now
    record(
        session,
        "results.released",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="exam",
        target_id=exam.id,
        changes={"attempts": len(ids)},
    )
    await session.commit()
    return await exam_results(session, principal, exam_id)


async def teacher_attempt(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID, attempt_id: uuid.UUID
) -> TeacherAttemptResult:
    exam = await _own_exam(session, principal, exam_id)
    found = (
        await session.execute(
            select(ExamAttempt, User, Result)
            .join(User, User.id == ExamAttempt.student_id)
            .outerjoin(Result, Result.attempt_id == ExamAttempt.id)
            .where(ExamAttempt.id == attempt_id, ExamAttempt.exam_id == exam.id)
        )
    ).first()
    if found is None:
        raise not_found()
    attempt, student, result = found
    questions = await _questions(session, attempt, teacher=True)
    return TeacherAttemptResult(
        attempt_id=attempt.id,
        student_name=student.full_name,
        student_email=student.email,
        status=attempt.status,
        grading_status=attempt.grading_status,
        submitted_at=attempt.submitted_at,
        result=_row(attempt, student, result),
        questions=questions,
        revisions=await _revisions(session, attempt.id),
    )


# ----------------------------------------------------------------------------- student


async def student_results(session: AsyncSession, principal: Principal) -> StudentResults:
    rows = (
        await session.execute(
            select(ExamAttempt, Exam, Result)
            .join(Exam, Exam.id == ExamAttempt.exam_id)
            .outerjoin(Result, Result.attempt_id == ExamAttempt.id)
            .where(
                ExamAttempt.student_id == principal.user_id,
                ExamAttempt.is_preview.is_(False),
                ExamAttempt.status.in_(("SUBMITTED", "AUTO_SUBMITTED")),
            )
            .order_by(ExamAttempt.submitted_at.desc())
        )
    ).tuples()
    items = []
    for attempt, exam, result in rows:
        released = result is not None and result.released_at is not None
        item = StudentResultItem(
            attempt_id=attempt.id,
            exam_id=exam.id,
            exam_title=exam.title,
            submitted_at=attempt.submitted_at,
            released=released,
        )
        if released and result is not None:
            item.total_score, item.max_score = result.total_score, result.max_score
            item.percentage, item.passed = result.percentage, result.passed
        items.append(item)
    return StudentResults(items=items)


async def student_result(
    session: AsyncSession, principal: Principal, attempt_id: uuid.UUID
) -> AttemptResult:
    found = (
        await session.execute(
            select(ExamAttempt, Exam, Result)
            .join(Exam, Exam.id == ExamAttempt.exam_id)
            .join(Result, Result.attempt_id == ExamAttempt.id)
            .where(
                ExamAttempt.id == attempt_id,
                ExamAttempt.student_id == principal.user_id,
                ExamAttempt.institution_id == principal.institution_id,
                Result.released_at.is_not(None),
            )
        )
    ).first()
    if found is None:
        raise not_found()  # someone else's, or not released: the same answer
    attempt, exam, result = found
    return AttemptResult(
        attempt_id=attempt.id,
        exam_id=exam.id,
        exam_title=exam.title,
        submitted_at=attempt.submitted_at,
        total_score=result.total_score,
        max_score=result.max_score,
        percentage=result.percentage,
        passed=result.passed,
        integrity_outcome=result.integrity_outcome,
        released_at=result.released_at or datetime.now(UTC),  # never None: filtered above
        questions=await _questions(session, attempt, teacher=False),
        revisions=await _revisions(session, attempt.id),
    )


# ----------------------------------------------------------------------------- shared


async def _revisions(session: AsyncSession, attempt_id: uuid.UUID) -> list[Revision]:
    rows = await session.scalars(
        select(ResultRevision)
        .where(ResultRevision.attempt_id == attempt_id)
        .order_by(ResultRevision.created_at)
    )
    return [
        Revision(
            old_score=r.old_score, new_score=r.new_score, reason=r.reason, created_at=r.created_at
        )
        for r in rows
    ]


async def _counted(session: AsyncSession, attempt_id: uuid.UUID) -> dict[uuid.UUID, CodingOutcome]:
    latest = (
        select(
            CodingEvaluation.submission_id,
            func.max(CodingEvaluation.evaluation_no).label("evaluation_no"),
        )
        .group_by(CodingEvaluation.submission_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(CodingSubmission, CodingEvaluation)
            .join(latest, latest.c.submission_id == CodingSubmission.id)
            .join(
                CodingEvaluation,
                (CodingEvaluation.submission_id == latest.c.submission_id)
                & (CodingEvaluation.evaluation_no == latest.c.evaluation_no),
            )
            .where(CodingSubmission.attempt_id == attempt_id, CodingSubmission.is_counted)
        )
    ).tuples()
    return {
        s.exam_question_id: CodingOutcome(
            submission_id=s.id,
            language_key=s.language_key,
            verdict=e.verdict,
            passed_weight=e.passed_weight,
            total_weight=e.total_weight,
            score=e.score,
        )
        for s, e in rows
    }


async def _questions(session: AsyncSession, attempt: ExamAttempt, *, teacher: bool) -> list[Any]:
    snapshot = await snapshot_of(session, attempt)
    answers = {
        a.exam_question_id: a
        for a in await session.scalars(select(Answer).where(Answer.attempt_id == attempt.id))
    }
    coding = await _counted(session, attempt.id)
    out: list[Any] = []
    for position, q in enumerate(snapshot["questions"], start=1):
        eq_id = uuid.UUID(q["exam_question_id"])
        answer = answers.get(eq_id)
        picked = {str(o) for o in (answer.selected_option_ids or [])} if answer else set()
        common: dict[str, Any] = {
            "exam_question_id": eq_id,
            "position": position,
            "type": q["type"],
            "body": q["body"],
            "points": Decimal(str(q["points"])),
            "score": answer.score if answer else None,
            "feedback": answer.feedback if answer else None,
            "selected_labels": [o["label"] for o in q["options"] if str(o["id"]) in picked],
            "text_answer": answer.text_answer if answer else None,
            "coding": coding.get(eq_id),
        }
        if teacher:
            out.append(
                TeacherQuestionResult(
                    **common,
                    auto_score=answer.auto_score if answer else None,
                    manual_score=answer.manual_score if answer else None,
                    correct_labels=[o["label"] for o in q["options"] if o["is_correct"]],
                    rubric=q.get("rubric"),
                )
            )
        else:
            out.append(QuestionResult(**common))
    return out
