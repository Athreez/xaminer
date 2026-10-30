"""Working out an attempt's result (PRD GRD-05, GRD-06, GRD-08; TCK-0905, TCK-0907).

Once every question of an attempt has a score (`grading_status = COMPLETE`) the `result` row is
computed from the answers' scores and the frozen exam: total (never below 0), maximum,
percentage, and pass/fail when the exam has a pass mark. It is computed again whenever a score
changes. An exam released "on submit" releases each result as soon as it's computed.

If a released result's total changes, a `result_revision` keeps the old and new score, the reason
and who made the change (GRD-08).
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.attempt import snapshot_of
from app.attempts.models import Answer, ExamAttempt
from app.results.models import Result, ResultRevision
from domain_core.objective_score import total


async def compute(
    session: AsyncSession,
    attempt: ExamAttempt,
    *,
    reason: str | None = None,
    changed_by: uuid.UUID | None = None,
) -> Result:
    snapshot = await snapshot_of(session, attempt)
    scores = {
        a.exam_question_id: a.score
        for a in await session.scalars(select(Answer).where(Answer.attempt_id == attempt.id))
    }
    per_question = []
    for position, q in enumerate(snapshot["questions"], start=1):
        score = scores.get(uuid.UUID(q["exam_question_id"])) or Decimal("0.00")
        per_question.append(
            {
                "exam_question_id": q["exam_question_id"],
                "position": position,
                "type": q["type"],
                "points": str(q["points"]),
                "score": str(score),
            }
        )
    settings = snapshot.get("settings", {})
    worked = total(
        (Decimal(p["score"]) for p in per_question),
        Decimal(str(snapshot["total_points"])),
    )
    pass_percent = settings.get("pass_percent")
    passed = None if pass_percent is None else worked.percentage >= Decimal(str(pass_percent))
    now = datetime.now(UTC)

    result = await session.get(Result, attempt.id, with_for_update=True)
    if result is None:
        result = Result(attempt_id=attempt.id, institution_id=attempt.institution_id)
        session.add(result)
        if settings.get("release_policy") == "ON_SUBMIT" and not attempt.is_preview:
            result.released_at = now
    elif result.released_at is not None and result.total_score != worked.score:
        session.add(
            ResultRevision(
                attempt_id=attempt.id,
                institution_id=attempt.institution_id,
                old_score=result.total_score,
                new_score=worked.score,
                reason=reason or "Score recalculated",
                changed_by=changed_by,
            )
        )
    result.total_score, result.max_score = worked.score, worked.max_score
    result.percentage, result.passed = worked.percentage, passed
    result.per_question = per_question
    result.computed_at = now
    await session.flush()
    return result
