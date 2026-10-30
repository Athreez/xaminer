"""Grading API (PRD GRD-03): the exam's marking queue and a mark per answer. Teachers, own exams."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.grading import manual
from app.grading.manual import GradingQueue, Mark, MarkIn

router = APIRouter(tags=["grading"])

Grader = Annotated[Principal, Depends(require(P.GRADING_WRITE))]


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
