"""A teacher's preview attempt (PRD EX-07): take your own exam exactly as a student would.

Works on a draft (from a fresh frozen copy, built the same way publishing builds one but without
pinning or locking anything) or on a published exam (from its published version). Each new
preview replaces the teacher's previous one, so edits show up straight away. The window is
ignored; the duration is the exam's, or 60 minutes if not set yet. Previews are marked
`is_preview` and never appear in results, the monitor or analytics.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.attempt import AttemptView, view, write_order
from app.attempts.models import ExamAttempt
from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import get_owned
from app.core.errors import AppError
from app.core.storage import Storage
from app.exams.models import Exam, ExamVersion
from app.exams.publish import build_snapshot

DEFAULT_MINUTES = 60


def _refuse(code: str, message: str) -> AppError:
    return AppError(
        code,
        message,
        status_code=409,
        details=[{"field": "exam", "message": message, "type": code}],
    )


async def start_preview(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID, storage: Storage
) -> AttemptView:
    now = datetime.now(UTC)
    exam = await get_owned(
        session, Exam, exam_id, principal, owned=lambda e: e.owner_id == principal.user_id
    )
    if exam.status == "ARCHIVED":
        raise _refuse("EXAM_ARCHIVED", "This exam is archived.")

    version_id = None
    if exam.status == "PUBLISHED" and exam.published_version_id:
        version = await session.get(ExamVersion, exam.published_version_id)
        if version is None:
            raise AppError("INTERNAL_ERROR", "The published version is missing.", status_code=500)
        snapshot, version_id, preview_copy = version.snapshot, version.id, None
    else:
        snapshot, count = await build_snapshot(session, exam, publishing=False)
        if count == 0:
            raise _refuse("NO_QUESTIONS", "Add questions to the exam before previewing it.")
        preview_copy = snapshot

    # Each preview replaces the previous one (one active attempt per person per exam).
    await session.execute(
        update(ExamAttempt)
        .where(
            ExamAttempt.exam_id == exam.id,
            ExamAttempt.student_id == principal.user_id,
            ExamAttempt.is_preview.is_(True),
            ExamAttempt.status != "VOIDED",
        )
        .values(status="VOIDED")
    )
    minutes = snapshot["settings"].get("duration_min") or DEFAULT_MINUTES
    attempt = ExamAttempt(
        exam_id=exam.id,
        exam_version_id=version_id,
        preview_snapshot=preview_copy,
        student_id=principal.user_id,
        started_at=now,
        deadline_at=now + timedelta(minutes=minutes),
        shuffle_seed=secrets.randbits(62),
        is_preview=True,
    )
    session.add(attempt)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if "uq_exam_attempt_one_active" not in str(exc):
            raise  # a real fault, not a race: let it surface
        # A second click started one at the same moment.
        raise _refuse("PREVIEW_STARTING", "A preview is already starting. Try again.") from exc
    write_order(session, attempt, snapshot)
    record(
        session,
        "attempt.preview_started",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="attempt",
        target_id=attempt.id,
        changes={"exam_id": str(exam.id), "exam_status": exam.status},
    )
    await session.commit()
    return await view(session, attempt, snapshot, storage, now)
