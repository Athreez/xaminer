"""Student-facing exam API: the student's exams, starting, resuming and saving (PRD ATT-01..09).

Submitting joins in a later ticket."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis

from app.attempts import attempt, manage, saving, student_exams
from app.attempts import heartbeat as heartbeats
from app.attempts import submit as submitting
from app.attempts.attempt import AttemptView
from app.attempts.heartbeat import HeartbeatIn, HeartbeatOut
from app.attempts.manage import ExtendIn, ManagedAttempt, ReasonIn
from app.attempts.saving import AnswersIn, DraftIn, DraftResult, FlagIn, SaveResult
from app.attempts.student_exams import StudentExamDetail, StudentExams
from app.attempts.submit import Receipt
from app.auth.dependencies import TenantDB, redis_of, settings_of
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.core.config import Settings
from app.execution import runs
from app.execution.runs import RunIn, RunView
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


@attempts_router.post("/{attempt_id}/submit")
async def submit_attempt(attempt_id: uuid.UUID, principal: Taker, db: TenantDB) -> Receipt:
    """Submit your exam. Safe to repeat: a second submit returns the same receipt."""
    return await submitting.submit(db, principal, attempt_id)


@attempts_router.get("/{attempt_id}/receipt")
async def attempt_receipt(attempt_id: uuid.UUID, principal: Taker, db: TenantDB) -> Receipt:
    """The receipt of your submitted attempt (404 while it's still in progress)."""
    return await submitting.get_receipt(db, principal, attempt_id)


@attempts_router.post(
    "/{attempt_id}/questions/{exam_question_id}/runs", status_code=status.HTTP_202_ACCEPTED
)
async def run_code(
    attempt_id: uuid.UUID,
    exam_question_id: uuid.UUID,
    body: RunIn,
    principal: Taker,
    db: TenantDB,
    storage: AppStorage,
) -> RunView:
    """Run Code (PRD EXE-02, EXE-03): your code on the public test cases, or on `custom_input`.
    Never graded. One at a time, 8 s apart, 20 per question; poll GET /runs/{id} for the result."""
    return await runs.start(db, principal, attempt_id, exam_question_id, body, storage)


runs_router = APIRouter(prefix="/runs", tags=["attempts"])


@runs_router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, principal: Taker, db: TenantDB) -> RunView:
    """A run's status and, when done, its results (public cases only)."""
    return await runs.get_run(db, principal, run_id)


# ----------------------------------------------------------------------------- teacher actions

Manager = Annotated[Principal, Depends(require(P.ATTEMPT_MANAGE))]


@attempts_router.post("/{attempt_id}/extend")
async def extend_attempt(
    attempt_id: uuid.UUID, body: ExtendIn, principal: Manager, db: TenantDB
) -> ManagedAttempt:
    """Give extra minutes (reason required). Never past the window's end: 409
    `WINDOW_ENDS_FIRST` says to move it first. The student sees it on the next heartbeat."""
    return await manage.extend(db, principal, attempt_id, body)


@attempts_router.post("/{attempt_id}/force-submit")
async def force_submit_attempt(
    attempt_id: uuid.UUID, body: ReasonIn, principal: Manager, db: TenantDB
) -> ManagedAttempt:
    """End an attempt in progress now (reason required)."""
    return await manage.force_submit(db, principal, attempt_id, body)


@attempts_router.post("/{attempt_id}/void")
async def void_attempt(
    attempt_id: uuid.UUID, body: ReasonIn, principal: Manager, db: TenantDB
) -> ManagedAttempt:
    """Cancel an attempt (reason required). The student may then start the exam again."""
    return await manage.void(db, principal, attempt_id, body)
