"""Grading the last draft when an attempt ends (PRD EXE-06; TCK-0810).

When an attempt ends (submitted, time up, the sweeper, a teacher's force-submit), app-worker looks
at each coding question: if the student's latest saved draft (in an allowed language) is newer
than their last submission, or they never submitted, it is submitted and graded automatically. It
doesn't count against the submission limit (`is_auto`).

Safe to run twice: the second time, the draft is no longer newer than the last submission.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.attempts.attempt import snapshot_of
from app.attempts.models import CodeDraft, ExamAttempt
from app.core.storage import Storage
from app.db.session import SessionFactory, system_session
from app.execution import queue, submissions
from app.execution.models import CodingSubmission
from workers import queues
from workers.exec_messages import ExecJob

logger = logging.getLogger(__name__)
TASK = "execution.auto_submit"


def queue_auto_submit(attempt_id: uuid.UUID) -> None:
    """Ask app-worker to grade this ended attempt's unsubmitted drafts. Tests replace this."""
    from workers.celery_app import enqueue

    enqueue(TASK, queues.GRADING, attempt_id=str(attempt_id))


async def auto_submit(factory: SessionFactory, storage: Storage, attempt_id: uuid.UUID) -> int:
    """Submit each coding question's newer draft. Returns how many were submitted."""
    jobs: list[ExecJob] = []
    async with system_session(factory) as session:
        attempt = await session.scalar(
            select(ExamAttempt).where(ExamAttempt.id == attempt_id).with_for_update()
        )
        if attempt is None or attempt.status not in ("SUBMITTED", "AUTO_SUBMITTED"):
            return 0  # still going, voided or gone: nothing to do
        now = datetime.now(UTC)
        for question in (await snapshot_of(session, attempt))["questions"]:
            if question["type"] != "CODING":
                continue
            eq_id = uuid.UUID(question["exam_question_id"])
            allowed = {lang["key"] for lang in (question.get("coding") or {}).get("languages", [])}
            draft = next(
                (
                    d
                    for d in await session.scalars(
                        select(CodeDraft)
                        .where(
                            CodeDraft.attempt_id == attempt.id, CodeDraft.exam_question_id == eq_id
                        )
                        .order_by(CodeDraft.updated_at.desc())
                    )
                    if d.language_key in allowed and d.source.strip()
                ),
                None,
            )
            if draft is None:
                continue
            last = await session.scalar(
                select(func.max(CodingSubmission.created_at)).where(
                    CodingSubmission.attempt_id == attempt.id,
                    CodingSubmission.exam_question_id == eq_id,
                )
            )
            if last is not None and draft.updated_at <= last:
                continue  # already submitted (or submitted since)
            _, job = await submissions.create(
                session,
                attempt,
                question,
                language_key=draft.language_key,
                source=draft.source,
                storage=storage,
                now=now,
                auto=True,
            )
            jobs.append(job)
        await session.commit()
    for job in jobs:  # after the commit, so the results find their jobs
        queue.send(job, queues.EXEC_SUBMIT)
    if jobs:
        logger.info(
            "drafts submitted at attempt end",
            extra={"attempt_id": str(attempt_id), "count": len(jobs)},
        )
    return len(jobs)
