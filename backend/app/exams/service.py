"""Exams for their owner (PRD EX-01, EX-03, EX-08) and the admin's metadata list (SECURITY § 3).

Only the owner sees or changes an exam; anyone else gets 404. Drafts change freely. Once published,
only the window end may change (the rest is frozen in the exam version, PRD EX-06); archived exams
don't change at all. Only drafts can be deleted. Every change is audit-logged.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import ExamAttempt
from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import get_owned
from app.core.errors import AppError
from app.core.markdown import sanitize_markdown
from app.core.pagination import MAX_PAGE, decode_cursor, encode_cursor, like_pattern
from app.exams.models import Exam, ExamAssignment, ExamQuestion, ExamVersion
from app.exams.schemas import (
    AdminExamPage,
    AdminExamSummary,
    Detectors,
    ExamCreate,
    ExamPage,
    ExamSummary,
    ExamUpdate,
    ExamView,
)
from app.questions.models import Question, QuestionVersion
from app.users.models import User

SETTINGS = (
    "title",
    "instructions",
    "open_at",
    "close_at",
    "duration_min",
    "navigation_mode",
    "shuffle_questions",
    "shuffle_options",
    "run_code_enabled",
    "release_policy",
    "counted_submission",
    "pass_percent",
    "proctoring_mode",
    "proctoring_detectors",
    "consent_text",
)
NULLABLE = {"open_at", "close_at", "duration_min", "pass_percent", "consent_text"}
EDITABLE_WHEN_PUBLISHED = {"close_at"}


def _invalid(
    field: str, message: str, code: str = "VALIDATION_FAILED", status: int = 422
) -> AppError:
    return AppError(
        code,
        message,
        status_code=status,
        details=[{"field": field, "message": message, "type": "exam"}],
    )


def _audit(
    session: AsyncSession,
    principal: Principal,
    action: str,
    exam_id: uuid.UUID,
    changes: dict[str, Any] | None = None,
) -> None:
    record(
        session,
        action,
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="exam",
        target_id=exam_id,
        changes=changes,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _check_window(open_at: datetime | None, close_at: datetime | None) -> None:
    if open_at and close_at and close_at <= open_at:
        raise _invalid("close_at", "The window must close after it opens.")


# ----------------------------------------------------------------------------- reading


async def get_own(session: AsyncSession, principal: Principal, exam_id: uuid.UUID) -> Exam:
    """The caller's own exam; anyone else's is 404 (PRD ACC-03)."""
    return await get_owned(
        session, Exam, exam_id, principal, owned=lambda e: e.owner_id == principal.user_id
    )


def _question_count(exam_id: Any) -> Any:
    return select(func.count()).where(ExamQuestion.exam_id == exam_id).scalar_subquery()


def _has_coding(exam_id: Any) -> Any:
    return (
        select(ExamQuestion.id)
        .join(Question, Question.id == ExamQuestion.question_id)
        .where(ExamQuestion.exam_id == exam_id, Question.type == "CODING")
        .exists()
    )


def _assigned_count(exam_id: Any) -> Any:
    return select(func.count()).where(ExamAssignment.exam_id == exam_id).scalar_subquery()


async def view(session: AsyncSession, exam: Exam) -> ExamView:
    await session.refresh(exam)  # updated_at is set by the database
    # Points: the exam's own value if set, else the pinned version's (published) or current one's.
    total = await session.scalar(
        select(
            func.coalesce(func.sum(func.coalesce(ExamQuestion.points, QuestionVersion.points)), 0)
        )
        .select_from(ExamQuestion)
        .join(Question, Question.id == ExamQuestion.question_id)
        .join(
            QuestionVersion,
            QuestionVersion.id
            == func.coalesce(ExamQuestion.pinned_version_id, Question.current_version_id),
        )
        .where(ExamQuestion.exam_id == exam.id)
    )
    questions = await session.scalar(select(func.count()).where(ExamQuestion.exam_id == exam.id))
    assigned = await session.scalar(select(func.count()).where(ExamAssignment.exam_id == exam.id))
    version_no = None
    if exam.published_version_id:
        version_no = await session.scalar(
            select(ExamVersion.version_no).where(ExamVersion.id == exam.published_version_id)
        )
    return ExamView(
        id=exam.id,
        title=exam.title,
        status=exam.status,  # type: ignore[arg-type]
        instructions=exam.instructions,
        open_at=exam.open_at,
        close_at=exam.close_at,
        duration_min=exam.duration_min,
        navigation_mode=exam.navigation_mode,  # type: ignore[arg-type]
        shuffle_questions=exam.shuffle_questions,
        shuffle_options=exam.shuffle_options,
        run_code_enabled=exam.run_code_enabled,
        release_policy=exam.release_policy,  # type: ignore[arg-type]
        counted_submission=exam.counted_submission,  # type: ignore[arg-type]
        pass_percent=exam.pass_percent,
        proctoring_mode=exam.proctoring_mode,  # type: ignore[arg-type]
        proctoring_detectors=Detectors(**exam.proctoring_detectors),
        consent_text=exam.consent_text,
        question_count=questions or 0,
        total_points=Decimal(total or 0),
        assigned_count=assigned or 0,
        published_version_no=version_no,
        created_at=exam.created_at,
        updated_at=exam.updated_at,
    )


def _filtered[*Ts](
    query: Select[*Ts], *, status: str | None, q: str | None, cursor: str | None, limit: int
) -> Select[*Ts]:
    if status:
        query = query.where(Exam.status == status)
    if q and q.strip():
        query = query.where(Exam.title.ilike(like_pattern(q.strip()), escape="\\"))
    if cursor:
        query = query.where(Exam.id < decode_cursor(cursor))
    return query.order_by(Exam.id.desc()).limit(limit + 1)


async def list_own(
    session: AsyncSession,
    principal: Principal,
    *,
    status: str | None,
    q: str | None,
    limit: int,
    cursor: str | None,
) -> ExamPage:
    """The caller's exams, newest first."""
    limit = max(1, min(limit, MAX_PAGE))
    query = select(
        Exam, _question_count(Exam.id), _assigned_count(Exam.id), _has_coding(Exam.id)
    ).where(Exam.owner_id == principal.user_id)
    rows = (
        await session.execute(_filtered(query, status=status, q=q, cursor=cursor, limit=limit))
    ).all()
    page = rows[:limit]
    return ExamPage(
        data=[
            ExamSummary(
                id=e.id,
                title=e.title,
                status=e.status,
                open_at=e.open_at,
                close_at=e.close_at,
                duration_min=e.duration_min,
                question_count=nq,
                assigned_count=na,
                proctoring_mode=e.proctoring_mode,
                has_coding=coding,
                updated_at=e.updated_at,
            )
            for e, nq, na, coding in page
        ],
        next_cursor=encode_cursor(page[-1][0].id) if len(rows) > limit and page else None,
    )


async def list_for_admin(
    session: AsyncSession, *, status: str | None, q: str | None, limit: int, cursor: str | None
) -> AdminExamPage:
    """Every exam in the institution: title, owner, window, status. Never content."""
    limit = max(1, min(limit, MAX_PAGE))
    query = select(Exam, User.full_name, _assigned_count(Exam.id)).join(
        User, User.id == Exam.owner_id
    )
    rows = (
        await session.execute(_filtered(query, status=status, q=q, cursor=cursor, limit=limit))
    ).all()
    page = rows[:limit]
    return AdminExamPage(
        data=[
            AdminExamSummary(
                id=e.id,
                title=e.title,
                owner_name=owner,
                status=e.status,
                open_at=e.open_at,
                close_at=e.close_at,
                duration_min=e.duration_min,
                assigned_count=na,
            )
            for e, owner, na in page
        ],
        next_cursor=encode_cursor(page[-1][0].id) if len(rows) > limit and page else None,
    )


# ----------------------------------------------------------------------------- changing


def _clean(field: str, value: Any) -> Any:
    if field in ("instructions", "consent_text") and isinstance(value, str):
        cleaned = sanitize_markdown(value).strip()
        return cleaned or (None if field == "consent_text" else "")
    if field == "proctoring_detectors" and isinstance(value, Detectors):
        return value.model_dump()
    return value


async def create_exam(session: AsyncSession, principal: Principal, body: ExamCreate) -> Exam:
    values = {field: _clean(field, getattr(body, field)) for field in SETTINGS}
    _check_window(values["open_at"], values["close_at"])
    exam = Exam(owner_id=principal.user_id, **values)
    session.add(exam)
    await session.flush()
    _audit(session, principal, "exam.created", exam.id, {"title": exam.title})
    await session.commit()
    return exam


async def update_exam(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID, body: ExamUpdate
) -> Exam:
    exam = await get_own(session, principal, exam_id)
    if exam.status == "ARCHIVED":
        raise _invalid(
            "status", "This exam is archived and can't be changed.", "EXAM_ARCHIVED", 409
        )
    sent = body.model_fields_set
    changes: dict[str, Any] = {}
    for field in SETTINGS:
        if field not in sent:
            continue
        value = getattr(body, field)
        if value is None and field not in NULLABLE:
            continue  # null for a required setting means "leave it"
        new, old = _clean(field, value), getattr(exam, field)
        if new == old:
            continue
        if exam.status == "PUBLISHED" and field not in EDITABLE_WHEN_PUBLISHED:
            raise _invalid(
                field,
                f"The exam is published, so {field.replace('_', ' ')} can't change. Only the "
                "window's end can.",
                "EXAM_PUBLISHED",
                409,
            )
        changes[field] = {"old": _jsonable(old), "new": _jsonable(new)}
        setattr(exam, field, new)
    if not changes:
        return exam
    _check_window(exam.open_at, exam.close_at)
    if exam.status == "PUBLISHED" and "close_at" in changes:
        if exam.close_at is None or exam.close_at <= datetime.now(UTC):
            raise _invalid("close_at", "A published exam's window must end in the future.")
    _audit(session, principal, "exam.updated", exam.id, changes)
    await session.commit()
    return exam


async def delete_exam(session: AsyncSession, principal: Principal, exam_id: uuid.UUID) -> None:
    """Only drafts: a published exam is kept for its results; archive it instead."""
    exam = await get_own(session, principal, exam_id)
    if exam.status != "DRAFT":
        raise _invalid(
            "status", "Only draft exams can be deleted. Archive it instead.", "EXAM_NOT_DRAFT", 409
        )
    _audit(session, principal, "exam.deleted", exam.id, {"title": exam.title})
    # A draft only has the teacher's preview attempts; they go with it.
    await session.execute(delete(ExamAttempt).where(ExamAttempt.exam_id == exam.id))
    await session.execute(delete(Exam).where(Exam.id == exam.id))
    await session.commit()


async def archive_exam(session: AsyncSession, principal: Principal, exam_id: uuid.UUID) -> Exam:
    """Hide it from the active list. Results and records stay (PRD EX-08)."""
    exam = await get_own(session, principal, exam_id)
    if exam.status == "ARCHIVED":
        return exam
    _audit(
        session,
        principal,
        "exam.archived",
        exam.id,
        {"status": {"old": exam.status, "new": "ARCHIVED"}},
    )
    exam.status = "ARCHIVED"
    await session.commit()
    return exam
