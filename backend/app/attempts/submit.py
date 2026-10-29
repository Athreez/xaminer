"""Ending an attempt (PRD ATT-10, ATT-11; architecture § 9 "Submit").

Every way an attempt ends goes through `finalize`: one guarded UPDATE that only changes an attempt
still IN_PROGRESS. A double click, two tabs, or a submit racing the sweeper can't conflict: the
first wins and the rest find it already done. Three ways in:

- the student submits (SUBMITTED);
- any request that touches an attempt past its deadline + grace ends it first (AUTO_SUBMITTED);
- the sweeper ends untouched overdue attempts every 30 s, e.g. a closed browser (AUTO_SUBMITTED).

Coding drafts newer than their last submission are submitted for grading too; that arrives with
code execution (E08).
"""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import Answer, AttemptQuestion, ExamAttempt
from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import get_owned, not_found
from app.db.session import SessionFactory, system_session
from domain_core import timer

SWEEP_BATCH = 500


class Receipt(BaseModel):
    """Proof of submission the student can keep (FRONTEND_SPEC § 9 ALREADY_SUBMITTED)."""

    attempt_id: uuid.UUID
    exam_id: uuid.UUID
    status: Literal["SUBMITTED", "AUTO_SUBMITTED"]
    submitted_at: datetime
    answered: int
    total: int
    code: str = Field(description="Short code identifying this submission, e.g. 4F2A-91C3-0B7E")


async def finalize(
    session: AsyncSession,
    attempt_id: uuid.UUID,
    institution_id: uuid.UUID,
    *,
    auto: bool,
    now: datetime,
    actor: Principal | None = None,
) -> bool:
    """End the attempt if it's still in progress. True if this call ended it. Caller commits."""
    status = "AUTO_SUBMITTED" if auto else "SUBMITTED"
    ended = await session.execute(
        update(ExamAttempt)
        .where(ExamAttempt.id == attempt_id, ExamAttempt.status == "IN_PROGRESS")
        .values(status=status, submitted_at=now)
        .returning(ExamAttempt.id)
    )
    if ended.first() is None:
        return False
    record(
        session,
        "attempt.auto_submitted" if auto else "attempt.submitted",
        institution_id=institution_id,
        actor_id=actor.user_id if actor else None,
        actor_role=actor.role if actor else None,
        target_type="attempt",
        target_id=attempt_id,
        changes={"status": status, "submitted_at": now.isoformat()},
    )
    return True


async def finalize_if_overdue(session: AsyncSession, attempt: ExamAttempt, now: datetime) -> bool:
    """Lazy finalisation: an attempt past its deadline + grace is ended before anything else
    happens to it. True if it was ended now (the attempt object is refreshed)."""
    if attempt.status != "IN_PROGRESS" or not timer.is_overdue(attempt.deadline_at, now):
        return False
    ended = await finalize(session, attempt.id, attempt.institution_id, auto=True, now=now)
    await session.commit()
    await session.refresh(attempt)
    return ended


async def receipt(session: AsyncSession, attempt: ExamAttempt) -> Receipt:
    if attempt.status not in ("SUBMITTED", "AUTO_SUBMITTED") or attempt.submitted_at is None:
        raise not_found()
    answered = await session.scalar(
        select(func.count())
        .select_from(Answer)
        .where(
            Answer.attempt_id == attempt.id,
            (func.cardinality(Answer.selected_option_ids) > 0) | Answer.text_answer.is_not(None),
        )
    )
    total = await session.scalar(
        select(func.count())
        .select_from(AttemptQuestion)
        .where(AttemptQuestion.attempt_id == attempt.id)
    )
    digest = (
        hashlib.sha256(f"{attempt.id}:{attempt.submitted_at.isoformat()}:{answered}".encode())
        .hexdigest()[:12]
        .upper()
    )
    return Receipt(
        attempt_id=attempt.id,
        exam_id=attempt.exam_id,
        status=attempt.status,  # type: ignore[arg-type]
        submitted_at=attempt.submitted_at,
        answered=answered or 0,
        total=total or 0,
        code="-".join(digest[i : i + 4] for i in range(0, 12, 4)),
    )


async def submit(session: AsyncSession, principal: Principal, attempt_id: uuid.UUID) -> Receipt:
    """The student submits. Safe to repeat: a second submit returns the same receipt."""
    now = datetime.now(UTC)
    attempt = await get_owned(
        session,
        ExamAttempt,
        attempt_id,
        principal,
        owned=lambda a: a.student_id == principal.user_id,
    )
    if attempt.status == "VOIDED":
        raise not_found()
    if attempt.status == "IN_PROGRESS":
        # After the deadline the time ran out: the exam screen submits by itself at zero, so it
        # counts as automatic. Past the grace it was over already: the system ends it.
        await finalize(
            session,
            attempt.id,
            attempt.institution_id,
            auto=now >= attempt.deadline_at,
            now=now,
            actor=None if timer.is_overdue(attempt.deadline_at, now) else principal,
        )
        await session.commit()
        await session.refresh(attempt)
    return await receipt(session, attempt)


async def get_receipt(
    session: AsyncSession, principal: Principal, attempt_id: uuid.UUID
) -> Receipt:
    attempt = await get_owned(
        session,
        ExamAttempt,
        attempt_id,
        principal,
        owned=lambda a: a.student_id == principal.user_id,
    )
    await finalize_if_overdue(session, attempt, datetime.now(UTC))
    return await receipt(session, attempt)


async def sweep(factory: SessionFactory, now: datetime | None = None) -> int:
    """End every attempt past its deadline + grace (all institutions). Returns how many ended.

    Runs every 30 s from the scheduler. Uses the partial index on open attempts' deadlines.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timer.GRACE
    ended = 0
    async with system_session(factory) as session:
        overdue = (
            await session.execute(
                select(ExamAttempt.id, ExamAttempt.institution_id)
                .where(ExamAttempt.status == "IN_PROGRESS", ExamAttempt.deadline_at < cutoff)
                .order_by(ExamAttempt.deadline_at)
                .limit(SWEEP_BATCH)
            )
        ).all()
        for attempt_id, institution_id in overdue:
            if await finalize(session, attempt_id, institution_id, auto=True, now=now):
                ended += 1
        await session.commit()
    return ended
