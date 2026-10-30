"""Grading an attempt when it ends (PRD GRD-01, GRD-04; TCK-0902, TCK-0903).

Every MCQ, MSQ and True/False question of the attempt is scored against the exam's frozen copy
(the snapshot holds each question's points, negative marks and correct options), with
`domain_core.objective_score`. Each gets an `answer` row with `auto_score` and `score`, unanswered
ones too (0), so results never have to guess. Coding questions take their counted submission's
score; an unanswered descriptive one gets 0, the others wait for the teacher. Then the grading
status is worked out (`status.refresh`).

App-worker runs this right after auto-submitting the last drafts (the same job), so code still to
run is already queued and the status says so.

Safe to run again: the same answers and key always give the same scores.
"""

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.attempts.attempt import snapshot_of
from app.attempts.models import Answer, ExamAttempt
from app.db.session import SessionFactory, system_session
from app.execution.results import recount
from app.grading.status import ENDED, refresh, save_auto_score
from domain_core.objective_score import ZERO, question_score

logger = logging.getLogger(__name__)


async def grade(factory: SessionFactory, attempt_id: uuid.UUID) -> int:
    """Score an ended attempt's objective answers. Returns how many were scored."""
    async with system_session(factory) as session:
        attempt = await session.scalar(
            select(ExamAttempt).where(ExamAttempt.id == attempt_id).with_for_update()
        )
        if attempt is None or attempt.status not in ENDED:
            return 0  # still going, voided or gone
        answers = {
            a.exam_question_id: a
            for a in await session.scalars(select(Answer).where(Answer.attempt_id == attempt.id))
        }
        scored = 0
        for question in (await snapshot_of(session, attempt))["questions"]:
            eq_id = uuid.UUID(question["exam_question_id"])
            saved = answers.get(eq_id)
            if question["type"] == "CODING":
                await recount(session, attempt, eq_id)  # its score: the counted submission's
                continue
            if question["type"] == "DESCRIPTIVE":
                if saved is None or not (saved.text_answer or "").strip():
                    await save_auto_score(session, attempt, eq_id, ZERO)  # nothing to mark
                continue
            value = question_score(
                question["type"],
                selected=[str(o) for o in (saved.selected_option_ids or [])] if saved else [],
                correct=[o["id"] for o in question["options"] if o["is_correct"]],
                points=Decimal(str(question["points"])),
                negative_marks=Decimal(str(question.get("negative_marks") or "0")),
                msq_scoring=question.get("msq_scoring") or "ALL_OR_NOTHING",
            )
            await save_auto_score(session, attempt, eq_id, value)
            scored += 1
        status = await refresh(session, attempt)
        await session.commit()
    logger.info(
        "attempt graded",
        extra={"attempt_id": str(attempt_id), "objective": scored, "status": status},
    )
    return scored
