"""An attempt's grading status (PRD GRD-04; TCK-0903), worked out from what is still unscored:

- PENDING: the attempt hasn't ended, or its objective answers aren't scored yet.
- AWAITING_CODING: code is waiting to run, or a coding question has no score yet.
- AWAITING_MANUAL: a descriptive answer is waiting for the teacher.
- COMPLETE: every question has a score.

`refresh` runs after objective grading, after each coding result and after each teacher's mark;
once complete it computes the result.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.attempt import snapshot_of
from app.attempts.models import Answer, ExamAttempt
from app.execution.models import CodingEvaluation, CodingSubmission
from app.results.compute import compute

ENDED = ("SUBMITTED", "AUTO_SUBMITTED")
OBJECTIVE = ("MCQ", "MSQ", "TRUE_FALSE")


async def save_auto_score(
    session: AsyncSession, attempt: ExamAttempt, exam_question_id: uuid.UUID, value: Decimal
) -> None:
    """Set a question's automatic score, creating its answer row if there's none (unanswered).
    A grader's override, if one was ever made, still wins."""
    now = datetime.now(UTC)
    await session.execute(
        insert(Answer)
        .values(
            attempt_id=attempt.id,
            exam_question_id=exam_question_id,
            institution_id=attempt.institution_id,
            auto_score=value,
            score=value,
            graded_at=now,
        )
        .on_conflict_do_update(
            index_elements=["attempt_id", "exam_question_id"],
            set_={
                "auto_score": value,
                "score": func.coalesce(Answer.manual_score, value),
                "graded_at": now,
            },
        )
    )


async def refresh(
    session: AsyncSession,
    attempt: ExamAttempt,
    *,
    reason: str | None = None,
    changed_by: uuid.UUID | None = None,
) -> str:
    """Work out and store the attempt's grading status. Once complete, the result is computed
    (again); `reason` and `changed_by` go into a revision if a released score changes."""
    if attempt.status not in ENDED:
        return attempt.grading_status
    await session.flush()
    scored = set(
        await session.scalars(
            select(Answer.exam_question_id).where(
                Answer.attempt_id == attempt.id, Answer.score.is_not(None)
            )
        )
    )
    waiting = await session.scalar(
        select(func.count())
        .select_from(CodingEvaluation)
        .join(CodingSubmission, CodingSubmission.id == CodingEvaluation.submission_id)
        .where(CodingSubmission.attempt_id == attempt.id, CodingEvaluation.status == "QUEUED")
    )
    questions = (await snapshot_of(session, attempt))["questions"]

    def unscored(*kinds: str) -> bool:
        return any(
            q["type"] in kinds and uuid.UUID(q["exam_question_id"]) not in scored for q in questions
        )

    if unscored(*OBJECTIVE):
        status = "PENDING"
    elif waiting or unscored("CODING"):
        status = "AWAITING_CODING"
    elif unscored("DESCRIPTIVE"):
        status = "AWAITING_MANUAL"
    else:
        status = "COMPLETE"
    attempt.grading_status = status
    if status == "COMPLETE":
        await compute(session, attempt, reason=reason, changed_by=changed_by)
    return status
