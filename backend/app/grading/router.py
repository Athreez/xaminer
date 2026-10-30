"""Grading API (PRD GRD-03, EXE-09): marking queue, marks, re-evaluation. Teachers, own exams."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.execution import reevaluate
from app.execution.reevaluate import ReEvaluateIn, ReEvaluation
from app.grading import manual
from app.grading.manual import GradingQueue, Mark, MarkIn
from app.images.router import AppStorage

router = APIRouter(tags=["grading"])

Grader = Annotated[Principal, Depends(require(P.GRADING_WRITE))]
ReEvaluator = Annotated[Principal, Depends(require(P.SUBMISSION_RE_EVALUATE))]


@router.get("/exams/{exam_id}/grading")
async def grading_queue(
    exam_id: uuid.UUID, principal: Grader, db: TenantDB, show_names: bool = False
) -> GradingQueue:
    """Descriptive questions with the answers to mark. Students are "Student n" unless
    `show_names` is set."""
    return await manual.queue(db, principal, exam_id, show_names=show_names)


@router.put("/attempts/{attempt_id}/answers/{exam_question_id}/mark")
async def mark_answer(
    attempt_id: uuid.UUID,
    exam_question_id: uuid.UUID,
    body: MarkIn,
    principal: Grader,
    db: TenantDB,
) -> Mark:
    """Mark a descriptive answer (0 to the question's points, optional feedback). Audited."""
    return await manual.mark(db, principal, attempt_id, exam_question_id, body)


@router.post("/exams/{exam_id}/re-evaluate")
async def re_evaluate(
    exam_id: uuid.UUID,
    body: ReEvaluateIn,
    principal: ReEvaluator,
    db: TenantDB,
    storage: AppStorage,
) -> ReEvaluation:
    """Run every submission to one coding question again, with the question's current
    (validated) test cases. 409 `NOT_VALIDATED` or `STILL_RUNNING`. Audited."""
    return await reevaluate.re_evaluate(db, storage, principal, exam_id, body)
