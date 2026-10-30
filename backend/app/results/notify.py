"""Telling students about their results (PRD NOT-02, NOT-03, GRD-08; TCK-1301, TCK-1303): a
released result (in-app and by email) and a released result whose score changed (in-app)."""

import uuid
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import ExamAttempt
from app.core.config import get_settings
from app.exams.models import Exam
from app.notifications.emails import Email, result_released_email
from app.notifications.inbox import notify
from app.users.models import User


def _path(attempt_id: uuid.UUID) -> str:
    return f"/student/results/{attempt_id}"


async def released(session: AsyncSession, exam: Exam, attempt_ids: Iterable[uuid.UUID]) -> None:
    base = get_settings().public_base_url.rstrip("/")
    for attempt_id, student_id in await session.execute(
        select(ExamAttempt.id, ExamAttempt.student_id).where(ExamAttempt.id.in_(list(attempt_ids)))
    ):
        link = base + _path(attempt_id)

        def email(user: User, link: str = link) -> Email:
            return result_released_email(
                to=user.email, full_name=user.full_name, exam_title=exam.title, link=link
            )

        await notify(
            session,
            institution_id=exam.institution_id,
            user_ids=[student_id],
            kind="RESULT_RELEASED",
            title=f"Result out: {exam.title}",
            body="Your score, each question and your teacher's feedback.",
            link=_path(attempt_id),
            email=email,
        )


async def changed(
    session: AsyncSession, attempt: ExamAttempt, old: Decimal, new: Decimal, reason: str
) -> None:
    exam = await session.get_one(Exam, attempt.exam_id)
    await notify(
        session,
        institution_id=attempt.institution_id,
        user_ids=[attempt.student_id],
        kind="RESULT_CHANGED",
        title=f"Score changed: {exam.title}",
        body=f"{old} → {new}. {reason}",
        link=_path(attempt.id),
    )
