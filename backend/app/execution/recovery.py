"""Stuck execution jobs (PRD EXE-07, EXE-08; TCK-0811).

Submissions are never dropped, even when the system is busy: a job waiting in a long queue is
left alone. A job is stuck when an exec-worker started it and never reported back (it crashed or
was killed mid-job), or when it was never even picked up for an hour (the message was lost).

Every 5 minutes app-worker sends stuck submission jobs again, with a fresh bundle link. A job that
started 3 times without a result (code that keeps killing the worker) gets INTERNAL_ERROR and no
score, never 0: the platform failing is never a grade. Run Code and validation are retried by the
person, so theirs are only marked failed, freeing the student to run again.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.attempt import snapshot_of
from app.attempts.models import ExamAttempt
from app.core.storage import Storage
from app.db.session import SessionFactory, system_session
from app.execution import queue
from app.execution.models import CodeRun, CodingEvaluation, CodingSubmission
from app.execution.results import after_evaluation
from app.execution.submissions import job_for
from app.questions.models import CodingConfig
from domain_core.coding_score import Verdict
from workers import queues
from workers.exec_messages import ExecJob

logger = logging.getLogger(__name__)

STUCK_AFTER = timedelta(minutes=15)  # started, no result: the worker died mid-job
LOST_AFTER = timedelta(hours=1)  # never started: the message was lost
MAX_STARTS = 3
VALIDATION_STUCK_AFTER = timedelta(minutes=30)


async def started(factory: SessionFactory, job_id: str, kind: str) -> None:
    """An exec-worker picked a job up."""
    try:
        row_id = uuid.UUID(job_id)
    except ValueError:
        return  # validation jobs have their own ids; they're timed by their report
    now = datetime.now(UTC)
    async with system_session(factory) as session:
        if kind == "submit":
            evaluation = await session.scalar(
                select(CodingEvaluation).where(CodingEvaluation.id == row_id).with_for_update()
            )
            if evaluation is not None and evaluation.status == "QUEUED":
                evaluation.started_at = now
                evaluation.starts += 1
        elif kind == "run":
            run = await session.get(CodeRun, row_id)
            if run is not None and run.status == "QUEUED":
                run.started_at = now
        await session.commit()


async def sweep(
    factory: SessionFactory, storage: Storage, now: datetime | None = None
) -> dict[str, int]:
    """Send stuck jobs again or give them up. Returns counts, for the log."""
    now = now or datetime.now(UTC)
    counts = {"resent": 0, "failed": 0, "runs_failed": 0, "validations_failed": 0}
    jobs: list[ExecJob] = []
    async with system_session(factory) as session:
        stuck = await session.scalars(
            select(CodingEvaluation)
            .where(
                CodingEvaluation.status == "QUEUED",
                or_(
                    CodingEvaluation.started_at < now - STUCK_AFTER,
                    (CodingEvaluation.started_at.is_(None))
                    & (CodingEvaluation.sent_at < now - LOST_AFTER),
                ),
            )
            .with_for_update(skip_locked=True)
        )
        for evaluation in list(stuck):
            if evaluation.starts >= MAX_STARTS:
                await _give_up(session, evaluation)
                counts["failed"] += 1
                continue
            job = await _job_again(session, storage, evaluation)
            if job is None:
                await _give_up(session, evaluation)
                counts["failed"] += 1
                continue
            evaluation.started_at, evaluation.sent_at = None, now
            jobs.append(job)
            counts["resent"] += 1

        runs = await session.scalars(
            select(CodeRun)
            .where(CodeRun.status == "QUEUED", CodeRun.created_at < now - STUCK_AFTER)
            .with_for_update(skip_locked=True)
        )
        for run in runs:
            run.status, run.finished_at = "FAILED", now
            counts["runs_failed"] += 1

        configs = await session.scalars(
            select(CodingConfig)
            .where(CodingConfig.validation_status == "VALIDATING")
            .with_for_update(skip_locked=True)
        )
        for config in configs:
            report: dict[str, Any] = dict(config.validation_report or {})
            begun = report.get("started_at")
            if begun and datetime.fromisoformat(begun) < now - VALIDATION_STUCK_AFTER:
                languages = dict(report.get("languages", {}))
                for key in report.get("pending", []):
                    languages[key] = {
                        "status": "ERROR",
                        "error": "The platform didn't finish in time. Validate again.",
                        "time_limit_ms": 0,
                        "compile_output": None,
                        "cases": [],
                        "warnings": [],
                    }
                config.validation_status = "FAILED"
                config.validation_report = {
                    **report,
                    "languages": languages,
                    "pending": [],
                    "finished_at": now.isoformat(),
                }
                counts["validations_failed"] += 1
        await session.commit()
    for job in jobs:  # after the commit
        queue.send(job, queues.EXEC_SUBMIT)
    if any(counts.values()):
        logger.info("stuck execution jobs handled", extra=counts)
    return counts


async def _job_again(
    session: AsyncSession, storage: Storage, evaluation: CodingEvaluation
) -> ExecJob | None:
    submission = await session.get(CodingSubmission, evaluation.submission_id)
    attempt = await session.get(ExamAttempt, submission.attempt_id) if submission else None
    if submission is None or attempt is None:
        return None
    question = next(
        (
            q
            for q in (await snapshot_of(session, attempt))["questions"]
            if q["exam_question_id"] == str(submission.exam_question_id)
        ),
        None,
    )
    if question is None:
        return None
    return await job_for(
        session,
        storage,
        question,
        language_key=submission.language_key,
        source=submission.source,
        job_id=str(evaluation.id),
        version_id=evaluation.version_id,
    )


async def _give_up(session: AsyncSession, evaluation: CodingEvaluation) -> None:
    """No score: the platform failed, not the student (EXE-08). A teacher can re-evaluate."""
    evaluation.status, evaluation.verdict, evaluation.score = "FAILED", Verdict.INTERNAL_ERROR, None
    evaluation.evaluated_at = datetime.now(UTC)
    submission = await session.get_one(CodingSubmission, evaluation.submission_id)
    submission.status = "FAILED"
    attempt = await session.get_one(ExamAttempt, submission.attempt_id)
    await after_evaluation(session, submission, attempt, {})
