"""Grading objective answers when an attempt ends (PRD GRD-01; TCK-0902).

Every MCQ, MSQ and True/False question of the attempt is scored against the exam's frozen copy
(the snapshot holds each question's points, negative marks and correct options), with
`domain_core.objective_score`. Each gets an `answer` row with `auto_score` and `score`, unanswered
ones too (0), so results never have to guess. Descriptive and coding questions are left to their
own grading.

Safe to run again: the same answers and key always give the same scores.
"""

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.attempts.attempt import snapshot_of
from app.attempts.models import Answer, ExamAttempt
from app.db.session import SessionFactory, system_session
from domain_core.objective_score import question_score
from workers import queues

logger = logging.getLogger(__name__)
TASK = "grading.objective"
OBJECTIVE = ("MCQ", "MSQ", "TRUE_FALSE")


def queue_grading(attempt_id: uuid.UUID) -> None:
    """Ask app-worker to grade this ended attempt's objective answers. Tests replace this."""
    from workers.celery_app import enqueue

    enqueue(TASK, queues.GRADING, attempt_id=str(attempt_id))


async def grade(factory: SessionFactory, attempt_id: uuid.UUID) -> int:
    """Score the objective answers of an ended attempt. Returns how many were scored."""
    async with system_session(factory) as session:
        attempt = await session.scalar(
            select(ExamAttempt).where(ExamAttempt.id == attempt_id).with_for_update()
        )
        if attempt is None or attempt.status not in ("SUBMITTED", "AUTO_SUBMITTED"):
            return 0  # still going, voided or gone
        answers = {
            a.exam_question_id: a
            for a in await session.scalars(select(Answer).where(Answer.attempt_id == attempt.id))
        }
        now = datetime.now(UTC)
        scored = 0
        for question in (await snapshot_of(session, attempt))["questions"]:
            if question["type"] not in OBJECTIVE:
                continue
            eq_id = uuid.UUID(question["exam_question_id"])
            saved = answers.get(eq_id)
            value = question_score(
                question["type"],
                selected=[str(o) for o in (saved.selected_option_ids or [])] if saved else [],
                correct=[o["id"] for o in question["options"] if o["is_correct"]],
                points=Decimal(str(question["points"])),
                negative_marks=Decimal(str(question.get("negative_marks") or "0")),
                msq_scoring=question.get("msq_scoring") or "ALL_OR_NOTHING",
            )
            # Upsert: an unanswered question gets its row (and its 0) too.
            await session.execute(
                insert(Answer)
                .values(
                    attempt_id=attempt.id,
                    exam_question_id=eq_id,
                    institution_id=attempt.institution_id,
                    auto_score=value,
                    score=value,
                    graded_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["attempt_id", "exam_question_id"],
                    # A grader's override, if one was ever made, still wins.
                    set_={
                        "auto_score": value,
                        "score": func.coalesce(Answer.manual_score, value),
                        "graded_at": now,
                    },
                )
            )
            scored += 1
        await session.commit()
    logger.info("objective answers graded", extra={"attempt_id": str(attempt_id), "count": scored})
    return scored
