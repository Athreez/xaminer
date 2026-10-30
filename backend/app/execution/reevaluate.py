"""Re-evaluating a coding question's submissions (PRD EXE-09; TCK-0814).

A teacher re-runs every submission to one coding question of their published exam, usually after
fixing a test case. Fixing a test case of a question a published exam uses makes a new version
(the exam keeps the old one), so the re-run uses the question's **current** version, which must
have passed validation. Points stay the exam's.

Each submission gets a new evaluation (QUEUED, with that version and the teacher's reason); the
attempts go back to "awaiting code evaluation" until the results arrive. Then the counted
submission and the score are worked out again as usual, and a released result that changes
keeps a revision with the reason (GRD-08). Only ended attempts, never previews. Audited.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import ExamAttempt
from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import get_owned, not_found
from app.core.errors import AppError
from app.core.storage import Storage
from app.exams.models import Exam, ExamVersion
from app.execution import queue
from app.execution.models import CodingEvaluation, CodingSubmission
from app.execution.submissions import job_for
from app.grading.status import ENDED, refresh
from app.questions.models import CodingConfig, Question, QuestionVersion
from workers import queues
from workers.exec_messages import ExecJob


class ReEvaluateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exam_question_id: uuid.UUID
    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)
    ] = Field(description="Why; kept in the audit log and in any changed result's revision")


class ReEvaluation(BaseModel):
    queued: int = Field(description="Submissions sent to run again")
    version_no: int = Field(description="The question version whose test cases grade them")


def _refuse(code: str, message: str) -> AppError:
    return AppError(
        code,
        message,
        status_code=409,
        details=[{"field": "exam_question_id", "message": message, "type": code}],
    )


async def re_evaluate(
    session: AsyncSession,
    storage: Storage,
    principal: Principal,
    exam_id: uuid.UUID,
    body: ReEvaluateIn,
) -> ReEvaluation:
    exam = await get_owned(
        session, Exam, exam_id, principal, owned=lambda e: e.owner_id == principal.user_id
    )
    published = (
        await session.get(ExamVersion, exam.published_version_id)
        if exam.published_version_id
        else None
    )
    if published is None:
        raise _refuse("EXAM_NOT_PUBLISHED", "Only a published exam's submissions can be re-run.")
    question = next(
        (
            q
            for q in published.snapshot["questions"]
            if q["exam_question_id"] == str(body.exam_question_id) and q["type"] == "CODING"
        ),
        None,
    )
    if question is None:
        raise not_found()  # not a coding question of this exam

    current = await session.scalar(
        select(QuestionVersion)
        .join(Question, Question.current_version_id == QuestionVersion.id)
        .where(Question.id == uuid.UUID(question["question_id"]))
    )
    config = await session.get(CodingConfig, current.id) if current else None
    if current is None or config is None or config.validation_status != "PASSED":
        raise _refuse(
            "NOT_VALIDATED",
            "Validate the question's current version first: its reference solution must pass "
            "every test case.",
        )
    if await session.scalar(
        select(func.count())
        .select_from(CodingEvaluation)
        .join(CodingSubmission, CodingSubmission.id == CodingEvaluation.submission_id)
        .join(ExamAttempt, ExamAttempt.id == CodingSubmission.attempt_id)
        .where(
            ExamAttempt.exam_id == exam.id,
            CodingSubmission.exam_question_id == body.exam_question_id,
            CodingEvaluation.status == "QUEUED",
        )
    ):
        raise _refuse(
            "STILL_RUNNING", "Some submissions to this question are still running. Try again soon."
        )

    rows = (
        await session.execute(
            select(CodingSubmission, ExamAttempt)
            .join(ExamAttempt, ExamAttempt.id == CodingSubmission.attempt_id)
            .where(
                ExamAttempt.exam_id == exam.id,
                ExamAttempt.is_preview.is_(False),
                ExamAttempt.status.in_(ENDED),
                CodingSubmission.exam_question_id == body.exam_question_id,
            )
            .order_by(CodingSubmission.created_at)
        )
    ).tuples()
    now = datetime.now(UTC)
    exam_version = uuid.UUID(question["version_id"])
    version_id = None if current.id == exam_version else current.id
    jobs: list[ExecJob] = []
    attempts: dict[uuid.UUID, ExamAttempt] = {}
    for submission, attempt in rows:
        number = await session.scalar(
            select(func.max(CodingEvaluation.evaluation_no)).where(
                CodingEvaluation.submission_id == submission.id
            )
        )
        evaluation = CodingEvaluation(
            submission_id=submission.id,
            institution_id=submission.institution_id,
            evaluation_no=(number or 0) + 1,
            max_score=Decimal(str(question["points"])),
            sent_at=now,
            version_id=version_id,
            reason=body.reason,
        )
        session.add(evaluation)
        await session.flush()
        submission.status = "QUEUED"
        jobs.append(
            await job_for(
                session,
                storage,
                question,
                language_key=submission.language_key,
                source=submission.source,
                job_id=str(evaluation.id),
                version_id=current.id,
            )
        )
        attempts[attempt.id] = attempt
    for attempt in attempts.values():
        await refresh(session, attempt)  # awaiting code evaluation until the results arrive
    record(
        session,
        "question.re_evaluated",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="exam",
        target_id=exam.id,
        changes={
            "exam_question_id": str(body.exam_question_id),
            "version_no": current.version_no,
            "submissions": len(jobs),
            "reason": body.reason,
        },
    )
    await session.commit()
    for job in jobs:
        queue.send(job, queues.EXEC_SUBMIT)  # after the commit, so each result finds its row
    return ReEvaluation(queued=len(jobs), version_no=current.version_no)
