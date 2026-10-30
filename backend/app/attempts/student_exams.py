"""The student's exams: what they can take now, what's coming, what's done (PRD ATT-01;
FRONTEND_SPEC § 5.6).

Only published exams the student is assigned to appear; archived ones only if the student took
them. Everything is judged by the server's clock. Content comes from the frozen published version,
so what the student is told matches what they will get.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import ExamAttempt
from app.auth.tokens import Principal
from app.authz.ownership import not_found
from app.core.errors import AppError
from app.exams.models import Exam, ExamAssignment, ExamVersion
from app.exams.schemas import NavigationMode, ProctoringMode
from app.users.models import User
from domain_core import timer

State = Literal["AVAILABLE", "IN_PROGRESS", "TOO_LATE", "UPCOMING", "SUBMITTED", "MISSED"]


class AttemptBrief(BaseModel):
    id: uuid.UUID
    status: Literal["IN_PROGRESS", "SUBMITTED", "AUTO_SUBMITTED"]
    started_at: datetime
    deadline_at: datetime
    submitted_at: datetime | None


class StudentExam(BaseModel):
    id: uuid.UUID
    title: str
    teacher_name: str
    open_at: datetime
    close_at: datetime
    duration_min: int
    question_count: int
    proctoring_mode: ProctoringMode
    state: State = Field(
        description="AVAILABLE: can start · IN_PROGRESS: can resume · TOO_LATE: open but under "
        "5 min left · UPCOMING · SUBMITTED · MISSED: closed without an attempt"
    )
    attempt: AttemptBrief | None


class StudentExams(BaseModel):
    available: list[StudentExam] = Field(description="Open now (start, resume, or too late)")
    upcoming: list[StudentExam] = Field(description="Not open yet, soonest first")
    completed: list[StudentExam] = Field(description="Submitted or missed, latest first")


class StudentExamDetail(StudentExam):
    """What the instructions page shows before starting (FRONTEND_SPEC § 5.6)."""

    instructions: str = Field(description="Markdown")
    navigation_mode: NavigationMode
    run_code_enabled: bool
    browser_checks: bool = False
    has_coding: bool
    total_points: str
    server_time: datetime = Field(description="For a countdown that ignores the device's clock")


_BY_BLOCK: dict[timer.StartBlock | None, State] = {
    None: "AVAILABLE",
    timer.StartBlock.NOT_OPEN: "UPCOMING",
    timer.StartBlock.TOO_LATE: "TOO_LATE",
    timer.StartBlock.CLOSED: "MISSED",
}


def _schedule(exam: Exam) -> tuple[datetime, datetime, int]:
    """A published exam's window and duration (publishing requires them)."""
    if exam.open_at is None or exam.close_at is None or exam.duration_min is None:
        raise AppError("INTERNAL_ERROR", "A published exam has no schedule.", status_code=500)
    return exam.open_at, exam.close_at, exam.duration_min


def _state(exam: Exam, attempt: ExamAttempt | None, now: datetime) -> State:
    if attempt is not None:
        if attempt.status == "IN_PROGRESS" and not timer.is_overdue(attempt.deadline_at, now):
            return "IN_PROGRESS"
        return "SUBMITTED"  # submitted, or overdue and about to be submitted automatically
    open_at, close_at, _ = _schedule(exam)
    return _BY_BLOCK[timer.start_block(open_at, close_at, now)]


async def _rows(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID | None = None
) -> list[tuple[Exam, ExamVersion, str, ExamAttempt | None]]:
    attempt = ExamAttempt
    query = (
        select(Exam, ExamVersion, User.full_name, attempt)
        .join(ExamAssignment, ExamAssignment.exam_id == Exam.id)
        .join(ExamVersion, ExamVersion.id == Exam.published_version_id)
        .join(User, User.id == Exam.owner_id)
        .outerjoin(
            attempt,
            (attempt.exam_id == Exam.id)
            & (attempt.student_id == principal.user_id)
            & (attempt.status != "VOIDED"),
        )
        .where(
            ExamAssignment.student_id == principal.user_id,
            Exam.status.in_(("PUBLISHED", "ARCHIVED")),
        )
    )
    if exam_id is not None:
        query = query.where(Exam.id == exam_id)
    rows: list[Any] = list((await session.execute(query)).all())
    # An archived exam only stays visible to students who took it.
    return [r for r in rows if r[0].status == "PUBLISHED" or r[3] is not None]


def _card(
    exam: Exam, version: ExamVersion, teacher: str, attempt: ExamAttempt | None, now: datetime
) -> dict[str, Any]:
    open_at, close_at, duration_min = _schedule(exam)
    return {
        "id": exam.id,
        "title": exam.title,
        "teacher_name": teacher,
        "open_at": open_at,
        "close_at": close_at,  # the live value: the teacher may have extended it
        "duration_min": duration_min,
        "question_count": len(version.snapshot.get("questions", [])),
        "proctoring_mode": exam.proctoring_mode,
        "state": _state(exam, attempt, now),
        "attempt": AttemptBrief(
            id=attempt.id,
            status=attempt.status,  # type: ignore[arg-type]
            started_at=attempt.started_at,
            deadline_at=attempt.deadline_at,
            submitted_at=attempt.submitted_at,
        )
        if attempt
        else None,
    }


async def list_exams(
    session: AsyncSession, principal: Principal, now: datetime | None = None
) -> StudentExams:
    now = now or datetime.now(UTC)
    cards = [StudentExam(**_card(*row, now)) for row in await _rows(session, principal)]
    return StudentExams(
        available=sorted(
            (c for c in cards if c.state in ("AVAILABLE", "IN_PROGRESS", "TOO_LATE")),
            key=lambda c: c.close_at,
        ),
        upcoming=sorted((c for c in cards if c.state == "UPCOMING"), key=lambda c: c.open_at),
        completed=sorted(
            (c for c in cards if c.state in ("SUBMITTED", "MISSED")),
            key=lambda c: c.close_at,
            reverse=True,
        ),
    )


async def get_exam(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID, now: datetime | None = None
) -> StudentExamDetail:
    """One of the student's exams; anything else (not assigned, draft, other institution) is 404."""
    now = now or datetime.now(UTC)
    rows = await _rows(session, principal, exam_id)
    if not rows:
        raise not_found()
    exam, version, teacher, attempt = rows[0]
    snapshot = version.snapshot
    return StudentExamDetail(
        **_card(exam, version, teacher, attempt, now),
        instructions=snapshot.get("instructions", ""),
        navigation_mode=snapshot["settings"]["navigation_mode"],
        run_code_enabled=snapshot["settings"]["run_code_enabled"],
        browser_checks=snapshot["settings"].get("browser_checks", False),
        has_coding=any(q["type"] == "CODING" for q in snapshot.get("questions", [])),
        total_points=str(snapshot.get("total_points", "0")),
        server_time=now,
    )
