"""Telling students about an exam they've been given (PRD NOT-02; TCK-1301). Sent when the exam
is published, and to students assigned to it after that (never for a draft: they can't see it)."""

import uuid
from collections.abc import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.exams.models import Exam
from app.notifications.emails import Email, exam_assigned_email
from app.notifications.inbox import notify
from app.platform.models import Institution
from app.users.models import User


def _duration(minutes: int | None) -> str:
    if not minutes:
        return "the time set by your teacher"
    hours, rest = divmod(minutes, 60)
    parts = ([f"{hours} hour{'s' if hours > 1 else ''}"] if hours else []) + (
        [f"{rest} minutes"] if rest else []
    )
    return " ".join(parts)


async def exam_assigned(session: AsyncSession, exam: Exam, student_ids: Iterable[uuid.UUID]) -> int:
    institution = await session.get_one(Institution, exam.institution_id)
    zone = ZoneInfo(institution.timezone)
    when = (
        exam.open_at.astimezone(zone).strftime("%a %d %b %Y, %H:%M") + f" ({institution.timezone})"
        if exam.open_at
        else "soon"
    )
    duration = _duration(exam.duration_min)
    path = f"/student/exams/{exam.id}"
    link = get_settings().public_base_url.rstrip("/") + path

    def email(user: User) -> Email:
        return exam_assigned_email(
            to=user.email,
            full_name=user.full_name,
            exam_title=exam.title,
            when=when,
            duration=duration,
            link=link,
        )

    return await notify(
        session,
        institution_id=exam.institution_id,
        user_ids=student_ids,
        kind="EXAM_ASSIGNED",
        title=f"New exam: {exam.title}",
        body=f"Opens {when} · {duration}",
        link=path,
        email=email,
    )
