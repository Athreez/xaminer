"""The teacher's dashboard: what needs doing across their own exams, in one request.

Per published exam: students assigned, attempts started and submitted, written answers still to
mark and graded results not released yet. Plus how many drafts and questions they have.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import Answer, ExamAttempt
from app.auth.tokens import Principal
from app.exams.models import Exam, ExamAssignment
from app.questions.models import Question
from app.results.models import Result

ENDED = ("SUBMITTED", "AUTO_SUBMITTED")


class DashboardExam(BaseModel):
    id: uuid.UUID
    title: str
    open_at: datetime | None
    close_at: datetime | None
    duration_min: int | None
    assigned: int
    started: int
    submitted: int
    to_mark: int
    to_release: int


class TeacherDashboard(BaseModel):
    exams: list[DashboardExam]
    drafts: int
    questions: int


async def dashboard(session: AsyncSession, principal: Principal) -> TeacherDashboard:
    mine = Exam.owner_id == principal.user_id
    exams = list(
        await session.scalars(
            select(Exam).where(mine, Exam.status == "PUBLISHED").order_by(Exam.open_at.desc())
        )
    )
    ids = [e.id for e in exams]

    def per_exam(query) -> dict[uuid.UUID, int]:  # type: ignore[no-untyped-def]
        return {exam_id: count for exam_id, count in query}

    real = and_(ExamAttempt.exam_id.in_(ids), ExamAttempt.is_preview.is_(False))
    assigned = per_exam(
        await session.execute(
            select(ExamAssignment.exam_id, func.count())
            .where(ExamAssignment.exam_id.in_(ids))
            .group_by(ExamAssignment.exam_id)
        )
    )
    started = per_exam(
        await session.execute(
            select(ExamAttempt.exam_id, func.count())
            .where(real, ExamAttempt.status != "VOIDED")
            .group_by(ExamAttempt.exam_id)
        )
    )
    submitted = per_exam(
        await session.execute(
            select(ExamAttempt.exam_id, func.count())
            .where(real, ExamAttempt.status.in_(ENDED))
            .group_by(ExamAttempt.exam_id)
        )
    )
    # Written answers are the only ones with text; blank ones were scored 0 automatically.
    to_mark = per_exam(
        await session.execute(
            select(ExamAttempt.exam_id, func.count())
            .join(Answer, Answer.attempt_id == ExamAttempt.id)
            .where(
                real,
                ExamAttempt.status.in_(ENDED),
                Answer.manual_score.is_(None),
                func.length(func.trim(func.coalesce(Answer.text_answer, ""))) > 0,
            )
            .group_by(ExamAttempt.exam_id)
        )
    )
    to_release = per_exam(
        await session.execute(
            select(ExamAttempt.exam_id, func.count())
            .join(Result, Result.attempt_id == ExamAttempt.id)
            .where(real, ExamAttempt.status.in_(ENDED), Result.released_at.is_(None))
            .group_by(ExamAttempt.exam_id)
        )
    )
    drafts = await session.scalar(
        select(func.count()).select_from(Exam).where(mine, Exam.status == "DRAFT")
    )
    questions = await session.scalar(
        select(func.count())
        .select_from(Question)
        .where(Question.owner_id == principal.user_id, Question.archived_at.is_(None))
    )
    return TeacherDashboard(
        exams=[
            DashboardExam(
                id=e.id,
                title=e.title,
                open_at=e.open_at,
                close_at=e.close_at,
                duration_min=e.duration_min,
                assigned=assigned.get(e.id, 0),
                started=started.get(e.id, 0),
                submitted=submitted.get(e.id, 0),
                to_mark=to_mark.get(e.id, 0),
                to_release=to_release.get(e.id, 0),
            )
            for e in exams
        ],
        drafts=drafts or 0,
        questions=questions or 0,
    )
