"""Student-facing exam API (PRD ATT-01). Attempts, answers and submitting join in later tickets."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.attempts import attempt, student_exams
from app.attempts.attempt import AttemptView
from app.attempts.student_exams import StudentExamDetail, StudentExams
from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
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
