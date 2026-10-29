"""What a teacher can do to a student's attempt (PRD MON-02, ATT-02; SECURITY `attempt:manage`).

Only the exam's owner, and every action needs a reason, which goes into the audit log.

- Extend: more minutes for an attempt still in progress. The deadline is recomputed with the same
  rule as at start, so it never passes the window's end; if that end is what stops it, the
  teacher is told to move the window first. The student sees it on their next heartbeat.
- Force-submit: end an attempt in progress now.
- Void: cancel any attempt (even a submitted one). The student may then start again.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import ExamAttempt
from app.attempts.submit import finalize, finalize_if_overdue
from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import not_found
from app.core.errors import AppError
from app.exams.models import Exam
from domain_core import timer

MAX_EXTRA_MINUTES = 600

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason = Field(description="Why; kept in the audit log")


class ExtendIn(ReasonIn):
    minutes: int = Field(ge=1, le=120)


class ManagedAttempt(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    status: Literal["IN_PROGRESS", "SUBMITTED", "AUTO_SUBMITTED", "VOIDED"]
    deadline_at: datetime
    extra_minutes: int
    submitted_at: datetime | None


def _view(attempt: ExamAttempt) -> ManagedAttempt:
    return ManagedAttempt(
        id=attempt.id,
        student_id=attempt.student_id,
        status=attempt.status,  # type: ignore[arg-type]
        deadline_at=attempt.deadline_at,
        extra_minutes=attempt.extra_minutes,
        submitted_at=attempt.submitted_at,
    )


def _conflict(code: str, message: str, field: str = "attempt") -> AppError:
    return AppError(
        code, message, status_code=409, details=[{"field": field, "message": message, "type": code}]
    )


async def _load(
    session: AsyncSession, principal: Principal, attempt_id: uuid.UUID
) -> tuple[ExamAttempt, Exam]:
    """The attempt if it belongs to one of the caller's exams; anything else is 404."""
    row = (
        await session.execute(
            select(ExamAttempt, Exam)
            .join(Exam, Exam.id == ExamAttempt.exam_id)
            .where(ExamAttempt.id == attempt_id, Exam.owner_id == principal.user_id)
        )
    ).first()
    if row is None or row[0].institution_id != principal.institution_id:
        raise not_found()
    return row[0], row[1]


def _audit(
    session: AsyncSession,
    principal: Principal,
    action: str,
    attempt: ExamAttempt,
    changes: dict[str, object],
) -> None:
    record(
        session,
        action,
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="attempt",
        target_id=attempt.id,
        changes=changes,
    )


async def extend(
    session: AsyncSession, principal: Principal, attempt_id: uuid.UUID, body: ExtendIn
) -> ManagedAttempt:
    now = datetime.now(UTC)
    attempt, exam = await _load(session, principal, attempt_id)
    await finalize_if_overdue(session, attempt, now)
    if attempt.status != "IN_PROGRESS":
        raise _conflict("ATTEMPT_ENDED", "This attempt has already ended, so it can't be extended.")
    extra = attempt.extra_minutes + body.minutes
    if extra > MAX_EXTRA_MINUTES:
        raise _conflict(
            "TOO_MUCH_EXTRA_TIME",
            f"An attempt can get at most {MAX_EXTRA_MINUTES} extra minutes in total.",
            "minutes",
        )
    if exam.duration_min is None or exam.close_at is None:
        raise AppError("INTERNAL_ERROR", "A published exam has no schedule.", status_code=500)
    deadline = timer.deadline(attempt.started_at, exam.duration_min, exam.close_at, extra)
    if deadline <= attempt.deadline_at:
        raise _conflict(
            "WINDOW_ENDS_FIRST",
            "The exam window closes before the extra time would end. Move the window's end first.",
            "close_at",
        )
    old = attempt.deadline_at
    attempt.extra_minutes, attempt.deadline_at = extra, deadline
    _audit(
        session,
        principal,
        "attempt.extended",
        attempt,
        {
            "reason": body.reason,
            "minutes": body.minutes,
            "deadline_at": {"old": old.isoformat(), "new": deadline.isoformat()},
        },
    )
    await session.commit()
    return _view(attempt)


async def force_submit(
    session: AsyncSession, principal: Principal, attempt_id: uuid.UUID, body: ReasonIn
) -> ManagedAttempt:
    now = datetime.now(UTC)
    attempt, _ = await _load(session, principal, attempt_id)
    await finalize_if_overdue(session, attempt, now)
    if attempt.status != "IN_PROGRESS":
        raise _conflict("ATTEMPT_ENDED", "This attempt has already ended.")
    if await finalize(
        session, attempt.id, attempt.institution_id, auto=True, now=now, actor=principal
    ):
        _audit(session, principal, "attempt.force_submitted", attempt, {"reason": body.reason})
    await session.commit()
    await session.refresh(attempt)
    return _view(attempt)


async def void(
    session: AsyncSession, principal: Principal, attempt_id: uuid.UUID, body: ReasonIn
) -> ManagedAttempt:
    """Cancel the attempt. The student may start the exam again (ATT-02)."""
    attempt, _ = await _load(session, principal, attempt_id)
    if attempt.status == "VOIDED":
        raise _conflict("ALREADY_VOIDED", "This attempt is already voided.")
    old = attempt.status
    attempt.status = "VOIDED"
    _audit(
        session,
        principal,
        "attempt.voided",
        attempt,
        {"reason": body.reason, "status": {"old": old, "new": "VOIDED"}},
    )
    await session.commit()
    return _view(attempt)
