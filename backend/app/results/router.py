"""Results API (PRD GRD-05..09): teachers on own exams; students on their own, released only."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.results import dashboard, service
from app.results.dashboard import TeacherDashboard
from app.results.service import AttemptResult, ExamResults, StudentResults, TeacherAttemptResult

router = APIRouter(tags=["results"])

Reader = Annotated[Principal, Depends(require(P.RESULT_READ))]
Releaser = Annotated[Principal, Depends(require(P.RESULT_RELEASE))]


@router.get("/exams/{exam_id}/results")
async def exam_results(exam_id: uuid.UUID, principal: Releaser, db: TenantDB) -> ExamResults:
    """Every attempt's score and grading status, and whether results can be released (and why
    not)."""
    return await service.exam_results(db, principal, exam_id)


@router.post("/exams/{exam_id}/results/release")
async def release_results(exam_id: uuid.UUID, principal: Releaser, db: TenantDB) -> ExamResults:
    """Release every computed result not released yet. 409 `RESULTS_NOT_READY` while an attempt
    is in progress or still being graded."""
    return await service.release(db, principal, exam_id)


@router.get("/exams/{exam_id}/results/{attempt_id}")
async def attempt_result(
    exam_id: uuid.UUID, attempt_id: uuid.UUID, principal: Releaser, db: TenantDB
) -> TeacherAttemptResult:
    """One attempt in full: each answer with its score, the key, feedback and coding outcome."""
    return await service.teacher_attempt(db, principal, exam_id, attempt_id)


@router.get("/student/results")
async def my_results(principal: Reader, db: TenantDB) -> StudentResults:
    """The caller's past exams; scores only on released results."""
    return await service.student_results(db, principal)


@router.get("/student/results/{attempt_id}")
async def my_result(attempt_id: uuid.UUID, principal: Reader, db: TenantDB) -> AttemptResult:
    """A released result of the caller's. Not released (or not theirs): 404."""
    return await service.student_result(db, principal, attempt_id)


@router.get("/teacher/dashboard")
async def teacher_dashboard(principal: Releaser, db: TenantDB) -> TeacherDashboard:
    """The caller's published exams with what needs doing (answers to mark, results to release),
    and how many drafts and questions they have."""
    return await dashboard.dashboard(db, principal)
