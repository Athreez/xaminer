"""Student-facing exam API: the student's exams, starting, resuming and saving (PRD ATT-01..09).

Submitting joins in a later ticket."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from redis.asyncio import Redis

from app.attempts import attempt, saving, student_exams
from app.attempts import heartbeat as heartbeats
from app.attempts.attempt import AttemptView
from app.attempts.heartbeat import HeartbeatIn, HeartbeatOut
from app.attempts.saving import AnswersIn, DraftIn, DraftResult, FlagIn, SaveResult
from app.attempts.student_exams import StudentExamDetail, StudentExams
from app.auth.dependencies import TenantDB, redis_of, settings_of
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.core.config import Settings
from app.images.router import AppStorage

router = APIRouter(prefix="/student/exams", tags=["student"])
attempts_router = APIRouter(prefix="/attempts", tags=["attempts"])

# attempt:take: students, and teachers for their own preview attempts. Everything here is scoped
# to the caller's assignments, so a teacher simply sees nothing.
Taker = Annotated[Principal, Depends(require(P.ATTEMPT_TAKE))]


@router.get("")
async def my_exams(principal: Taker, db: TenantDB) -> StudentExams:
    """Your exams: available now, upcoming and completed."""
    return await student_exams.list_exams(db, principal)


@router.get("/{exam_id}")
async def my_exam(exam_id: uuid.UUID, principal: Taker, db: TenantDB) -> StudentExamDetail:
    """One of your exams, for the instructions page."""
    return await student_exams.get_exam(db, principal, exam_id)


@router.post("/{exam_id}/attempts")
async def start_attempt(
    exam_id: uuid.UUID, principal: Taker, db: TenantDB, storage: AppStorage
) -> AttemptView:
    """Start the exam, or get your attempt back if it's already started (safe to repeat).

    Refused with 409 `EXAM_NOT_OPEN`, `EXAM_CLOSED`, `TOO_LATE_TO_START` (under 5 min left) or
    `ALREADY_SUBMITTED`. The response has every question in your order, without answers.
    """
    return await attempt.start(db, principal, exam_id, storage)


@attempts_router.get("/{attempt_id}")
async def get_attempt(
    attempt_id: uuid.UUID, principal: Taker, db: TenantDB, storage: AppStorage
) -> AttemptView:
    """Your attempt as you left it: same questions, order, answers and deadline (resume)."""
    return await attempt.resume(db, principal, attempt_id, storage)


@attempts_router.put("/{attempt_id}/answers")
async def save_answers(
    attempt_id: uuid.UUID, body: AnswersIn, principal: Taker, db: TenantDB
) -> SaveResult:
    """Save a batch of answers. Each has a `client_revision`; an older or repeated one changes
    nothing and is listed as stale. Refused with 409 `TIME_UP` after the deadline plus 60 s."""
    return await saving.save_answers(db, principal, attempt_id, body)


@attempts_router.put("/{attempt_id}/flags/{exam_question_id}", status_code=204)
async def set_flag(
    attempt_id: uuid.UUID, exam_question_id: uuid.UUID, body: FlagIn, principal: Taker, db: TenantDB
) -> None:
    """Mark or unmark a question for review."""
    await saving.set_flag(db, principal, attempt_id, exam_question_id, body)


@attempts_router.put("/{attempt_id}/drafts/{exam_question_id}")
async def save_draft(
    attempt_id: uuid.UUID,
    exam_question_id: uuid.UUID,
    body: DraftIn,
    principal: Taker,
    db: TenantDB,
) -> DraftResult:
    """Save unsubmitted code for a coding question (one draft per language)."""
    return await saving.save_draft(db, principal, attempt_id, exam_question_id, body)


@attempts_router.post("/{attempt_id}/heartbeat")
async def heartbeat(
    attempt_id: uuid.UUID,
    body: HeartbeatIn,
    principal: Taker,
    db: TenantDB,
    redis: Annotated[Redis, Depends(redis_of)],
    settings: Annotated[Settings, Depends(settings_of)],
) -> HeartbeatOut:
    """Every few seconds from the exam screen: status, deadline and server time (to react to
    teacher actions and keep the timer honest), and a fresh token for proctoring uploads."""
    return await heartbeats.beat(
        db, redis, principal, attempt_id, body, settings.jwt_secret.get_secret_value()
    )
