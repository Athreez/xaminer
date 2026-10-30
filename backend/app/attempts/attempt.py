"""Starting and resuming an attempt (PRD ATT-01..05, ATT-09; architecture § 9 "Start").

Start is safe to repeat: the same student gets the same attempt back, even when two "Start"
requests race (the database lets one insert win; the other returns the winner's attempt). The
deadline is fixed from the server's clock at that moment. The questions come from the exam's
frozen version, in this student's order, as the student view: never answers or rubrics.
"""

import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import Answer, AttemptQuestion, CodeDraft, ExamAttempt
from app.attempts.submit import finalize_if_overdue
from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import get_owned, not_found
from app.core.errors import AppError
from app.core.storage import Storage
from app.exams.models import Exam, ExamAssignment, ExamVersion
from app.exams.schemas import NavigationMode
from app.questions.student_view import StudentQuestion, from_snapshot
from domain_core import shuffle, timer


class SavedAnswer(BaseModel):
    selected_option_ids: list[uuid.UUID] | None
    text_answer: str | None
    client_revision: int


class SavedDraft(BaseModel):
    language_key: str
    source: str
    client_revision: int
    updated_at: datetime


class AttemptItem(BaseModel):
    exam_question_id: uuid.UUID
    position: int = Field(description="1 for the first question this student sees")
    marked_for_review: bool
    question: StudentQuestion
    answer: SavedAnswer | None
    drafts: list[SavedDraft] = Field(
        default=[], description="Coding questions: saved code per language, newest first"
    )


class AttemptView(BaseModel):
    """Everything the exam screen needs, in one response (architecture § 9)."""

    id: uuid.UUID
    exam_id: uuid.UUID
    title: str
    status: str
    started_at: datetime
    deadline_at: datetime
    server_time: datetime = Field(description="The timer counts from this, not the device clock")
    seconds_left: int
    navigation_mode: NavigationMode
    run_code_enabled: bool
    browser_checks: bool = Field(
        default=False, description="Fullscreen, staying on the page, pasting only from the exam"
    )
    counted_submission: Literal["BEST", "LAST"] = Field(
        description="Coding questions: which submission gives the score"
    )
    total_points: Decimal
    questions: list[AttemptItem]


def _refuse(code: str, message: str, status: int = 409, **detail: Any) -> AppError:
    return AppError(
        code,
        message,
        status_code=status,
        details=[{"field": "exam", "message": message, "type": code, **detail}],
    )


async def _load_exam(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID
) -> tuple[Exam, ExamVersion]:
    """The exam if the caller is assigned to it and it's published; anything else is 404."""
    row = (
        await session.execute(
            select(Exam, ExamVersion)
            .join(ExamAssignment, ExamAssignment.exam_id == Exam.id)
            .join(ExamVersion, ExamVersion.id == Exam.published_version_id)
            .where(
                Exam.id == exam_id,
                ExamAssignment.student_id == principal.user_id,
                Exam.status == "PUBLISHED",
            )
        )
    ).first()
    if row is None:
        raise not_found()
    return row[0], row[1]


async def _existing(
    session: AsyncSession, exam_id: uuid.UUID, student_id: uuid.UUID
) -> ExamAttempt | None:
    return await session.scalar(
        select(ExamAttempt).where(
            ExamAttempt.exam_id == exam_id,
            ExamAttempt.student_id == student_id,
            ExamAttempt.status != "VOIDED",
        )
    )


async def start(
    session: AsyncSession,
    principal: Principal,
    exam_id: uuid.UUID,
    storage: Storage,
    now: datetime | None = None,
) -> AttemptView:
    now = now or datetime.now(UTC)
    exam, version = await _load_exam(session, principal, exam_id)

    attempt = await _existing(session, exam.id, principal.user_id)
    if attempt is not None:
        await finalize_if_overdue(session, attempt, now)
    if attempt is None:
        if exam.open_at is None or exam.close_at is None or exam.duration_min is None:
            raise AppError("INTERNAL_ERROR", "A published exam has no schedule.", status_code=500)
        block = timer.start_block(exam.open_at, exam.close_at, now)
        if block is timer.StartBlock.NOT_OPEN:
            raise _refuse(
                "EXAM_NOT_OPEN", "The exam hasn't opened yet.", opens_at=exam.open_at.isoformat()
            )
        if block is timer.StartBlock.CLOSED:
            raise _refuse("EXAM_CLOSED", "The exam window has closed.")
        if block is timer.StartBlock.TOO_LATE:
            raise _refuse(
                "TOO_LATE_TO_START",
                "Less than 5 minutes of the window are left, so the exam can't be started.",
            )
        # Proctored exams also need recorded consent before starting: added with TCK-1001.
        attempt = await _create(session, principal, exam, version, now)

    if attempt.status in ("SUBMITTED", "AUTO_SUBMITTED"):
        raise _refuse(
            "ALREADY_SUBMITTED", "You have already submitted this exam.", attempt_id=str(attempt.id)
        )
    # Reload the version: if this request lost a race, the rollback expired what was loaded.
    fresh = await session.get(ExamVersion, attempt.exam_version_id, populate_existing=True)
    if fresh is None:
        raise not_found()
    return await view(session, attempt, fresh.snapshot, storage, now)


async def _create(
    session: AsyncSession, principal: Principal, exam: Exam, version: ExamVersion, now: datetime
) -> ExamAttempt:
    if exam.close_at is None or exam.duration_min is None:  # checked by the caller already
        raise AppError("INTERNAL_ERROR", "A published exam has no schedule.", status_code=500)
    exam_id, student_id = exam.id, principal.user_id  # kept: a rollback below expires the objects
    attempt = ExamAttempt(
        exam_id=exam.id,
        exam_version_id=version.id,
        student_id=principal.user_id,
        started_at=now,
        deadline_at=timer.deadline(now, exam.duration_min, exam.close_at),
        shuffle_seed=secrets.randbits(62),
    )
    session.add(attempt)
    try:
        await session.flush()
    except IntegrityError:
        # Another "Start" for this student won the race: hand back that attempt.
        await session.rollback()
        winner = await _existing(session, exam_id, student_id)
        if winner is None:
            raise
        return winner

    write_order(session, attempt, version.snapshot)
    record(
        session,
        "attempt.started",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="attempt",
        target_id=attempt.id,
        changes={"exam_id": str(exam.id), "deadline_at": attempt.deadline_at.isoformat()},
    )
    await session.commit()
    return attempt


def write_order(session: AsyncSession, attempt: ExamAttempt, snapshot: dict[str, Any]) -> None:
    """This attempt's question order and option orders (shuffled if the exam says so, ATT-05)."""
    settings = snapshot["settings"]
    questions = snapshot["questions"]
    if settings["shuffle_questions"]:
        questions = shuffle.shuffled(
            attempt.shuffle_seed, questions, key=lambda q: q["exam_question_id"]
        )
    for position, q in enumerate(questions, start=1):
        option_order = None
        if settings["shuffle_options"] and q["type"] in ("MCQ", "MSQ") and q["options"]:
            option_order = shuffle.permutation(
                attempt.shuffle_seed, q["exam_question_id"], len(q["options"])
            )
        session.add(
            AttemptQuestion(
                attempt_id=attempt.id,
                exam_question_id=uuid.UUID(q["exam_question_id"]),
                position=position,
                option_order=option_order,
            )
        )


async def snapshot_of(session: AsyncSession, attempt: ExamAttempt) -> dict[str, Any]:
    """The frozen exam this attempt was taken from: the published version, or a preview's copy."""
    if attempt.preview_snapshot is not None:
        return attempt.preview_snapshot
    version = await session.get(ExamVersion, attempt.exam_version_id)
    if version is None:
        raise not_found()
    return version.snapshot


async def view(
    session: AsyncSession,
    attempt: ExamAttempt,
    snapshot: dict[str, Any],
    storage: Storage,
    now: datetime,
) -> AttemptView:
    by_id = {q["exam_question_id"]: q for q in snapshot["questions"]}
    order = list(
        await session.scalars(
            select(AttemptQuestion)
            .where(AttemptQuestion.attempt_id == attempt.id)
            .order_by(AttemptQuestion.position)
        )
    )
    answers = {
        a.exam_question_id: a
        for a in await session.scalars(select(Answer).where(Answer.attempt_id == attempt.id))
    }
    drafts: dict[uuid.UUID, list[SavedDraft]] = {}
    for d in await session.scalars(
        select(CodeDraft)
        .where(CodeDraft.attempt_id == attempt.id)
        .order_by(CodeDraft.updated_at.desc())
    ):
        drafts.setdefault(d.exam_question_id, []).append(
            SavedDraft(
                language_key=d.language_key,
                source=d.source,
                client_revision=d.client_revision,
                updated_at=d.updated_at,
            )
        )
    # Image links last until the attempt can no longer change, plus a little slack.
    image_seconds = max(60, int((attempt.deadline_at + timer.GRACE - now).total_seconds()) + 60)
    items = []
    for aq in order:
        saved = answers.get(aq.exam_question_id)
        items.append(
            AttemptItem(
                exam_question_id=aq.exam_question_id,
                position=aq.position,
                marked_for_review=aq.marked_for_review,
                question=from_snapshot(
                    by_id[str(aq.exam_question_id)],
                    aq.option_order,
                    attempt.institution_id,
                    storage,
                    image_seconds,
                ),
                answer=SavedAnswer(
                    selected_option_ids=saved.selected_option_ids,
                    text_answer=saved.text_answer,
                    client_revision=saved.client_revision,
                )
                if saved
                else None,
                drafts=drafts.get(aq.exam_question_id, []),
            )
        )
    return AttemptView(
        id=attempt.id,
        exam_id=attempt.exam_id,
        title=snapshot["title"],
        status=attempt.status,
        started_at=attempt.started_at,
        deadline_at=attempt.deadline_at,
        server_time=now,
        seconds_left=timer.seconds_left(attempt.deadline_at, now),
        navigation_mode=snapshot["settings"]["navigation_mode"],
        run_code_enabled=snapshot["settings"]["run_code_enabled"],
        # Exams published before the setting existed had none.
        browser_checks=snapshot["settings"].get("browser_checks", False),
        counted_submission=snapshot["settings"].get("counted_submission", "BEST"),
        total_points=Decimal(snapshot["total_points"]),
        questions=items,
    )


async def resume(
    session: AsyncSession,
    principal: Principal,
    attempt_id: uuid.UUID,
    storage: Storage,
    now: datetime | None = None,
) -> AttemptView:
    """The student's own attempt, as it was left (ATT-09). Anyone else's is 404."""
    now = now or datetime.now(UTC)
    attempt = await get_owned(
        session,
        ExamAttempt,
        attempt_id,
        principal,
        owned=lambda a: a.student_id == principal.user_id,
    )
    if attempt.status == "VOIDED":
        raise not_found()
    await finalize_if_overdue(session, attempt, now)
    if attempt.status in ("SUBMITTED", "AUTO_SUBMITTED"):
        raise _refuse(
            "ALREADY_SUBMITTED", "You have already submitted this exam.", attempt_id=str(attempt.id)
        )
    return await view(session, attempt, await snapshot_of(session, attempt), storage, now)
