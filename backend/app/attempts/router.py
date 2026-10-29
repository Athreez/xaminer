"""Student-facing exam API (PRD ATT-01). Attempts, answers and submitting join in later tickets."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.attempts import student_exams
from app.attempts.student_exams import StudentExamDetail, StudentExams
from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P

router = APIRouter(prefix="/student/exams", tags=["student"])

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
