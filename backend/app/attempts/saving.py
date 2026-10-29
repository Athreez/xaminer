"""Autosave during an attempt (PRD ATT-07, ATT-08, ATT-11; architecture § 9).

The exam screen saves on the device first and sends batches every few seconds, so saves can arrive
late, twice, or out of order. Each carries the device's `client_revision`; the database keeps a
save only if its revision is newer than the stored one, in the same statement, so nothing old ever
overwrites something new. Saves count until the deadline plus the 60 s grace; later ones are
refused. Every answer is checked against the exam's frozen version.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.attempt import snapshot_of
from app.attempts.models import MAX_TEXT_ANSWER, Answer, AttemptQuestion, CodeDraft, ExamAttempt
from app.attempts.submit import finalize_if_overdue
from app.auth.tokens import Principal
from app.authz.ownership import get_owned, not_found
from app.core.errors import AppError
from app.platform.models import Language
from domain_core import timer

MAX_BATCH = 200


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exam_question_id: uuid.UUID
    selected_option_ids: list[uuid.UUID] | None = Field(
        default=None, max_length=10, description="Choice questions; [] clears the answer"
    )
    text_answer: Annotated[str, StringConstraints(max_length=MAX_TEXT_ANSWER)] | None = Field(
        default=None, description="Descriptive questions; null clears the answer"
    )
    client_revision: int = Field(ge=1, description="Increases with every change on the device")


class AnswersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[AnswerIn] = Field(min_length=1, max_length=MAX_BATCH)


class SaveResult(BaseModel):
    saved: list[uuid.UUID] = Field(description="Questions whose answer was stored")
    stale: list[uuid.UUID] = Field(
        description="Ignored: the server already had this revision or a newer one"
    )
    server_time: datetime
    seconds_left: int


class FlagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marked: bool


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language_key: str = Field(max_length=32)
    source: str = Field(max_length=262_144)
    client_revision: int = Field(ge=1)


class DraftResult(BaseModel):
    saved: bool = Field(description="False: the server already had this revision or a newer one")
    server_time: datetime
    seconds_left: int


def _invalid(field: str, message: str) -> AppError:
    return AppError(
        "VALIDATION_FAILED",
        message,
        status_code=422,
        details=[{"field": field, "message": message, "type": "answer"}],
    )


async def _open_attempt(
    session: AsyncSession, principal: Principal, attempt_id: uuid.UUID, now: datetime
) -> tuple[ExamAttempt, dict[str, dict[str, Any]]]:
    """The caller's attempt if it still takes saves, with its questions from the frozen version."""
    attempt = await get_owned(
        session,
        ExamAttempt,
        attempt_id,
        principal,
        owned=lambda a: a.student_id == principal.user_id,
    )
    if attempt.status == "VOIDED":
        raise not_found()
    if await finalize_if_overdue(session, attempt, now):
        raise AppError("TIME_UP", "Time is up: answers can't be changed any more.", status_code=409)
    if attempt.status != "IN_PROGRESS":
        raise AppError(
            "ATTEMPT_SUBMITTED", "This exam has already been submitted.", status_code=409
        )
    if not timer.accepts_saves(attempt.deadline_at, now):
        raise AppError(
            "TIME_UP",
            "Time is up: answers can't be changed any more.",
            status_code=409,
        )
    snapshot = await snapshot_of(session, attempt)
    # Only questions in this attempt (the order rows) can be answered.
    in_attempt = {
        str(eq)
        for eq in await session.scalars(
            select(AttemptQuestion.exam_question_id).where(AttemptQuestion.attempt_id == attempt.id)
        )
    }
    questions = {
        q["exam_question_id"]: q
        for q in snapshot["questions"]
        if q["exam_question_id"] in in_attempt
    }
    return attempt, questions


def _check(index: int, answer: AnswerIn, question: dict[str, Any] | None) -> dict[str, Any]:
    """The values to store for this answer, or a 422 naming the problem."""
    field = f"answers.{index}"
    if question is None:
        raise _invalid(f"{field}.exam_question_id", "This question isn't part of your exam.")
    kind = question["type"]
    if kind in ("MCQ", "MSQ", "TRUE_FALSE"):
        if answer.text_answer is not None:
            raise _invalid(f"{field}.text_answer", "A choice question takes options, not text.")
        chosen = list(dict.fromkeys(answer.selected_option_ids or []))
        allowed = {o["id"] for o in question["options"]}
        if any(str(o) not in allowed for o in chosen):
            raise _invalid(
                f"{field}.selected_option_ids", "An option isn't one of this question's."
            )
        if kind != "MSQ" and len(chosen) > 1:
            raise _invalid(f"{field}.selected_option_ids", "Choose only one option.")
        return {"selected_option_ids": chosen or None, "text_answer": None}
    if kind == "DESCRIPTIVE":
        if answer.selected_option_ids:
            raise _invalid(f"{field}.selected_option_ids", "This question takes a written answer.")
        text = answer.text_answer
        limit = question.get("max_answer_length")
        if text is not None and limit and len(text) > limit:
            raise _invalid(f"{field}.text_answer", f"The answer is longer than {limit} characters.")
        return {"selected_option_ids": None, "text_answer": text or None}
    raise _invalid(
        f"{field}.exam_question_id", "Coding answers are saved as drafts and submissions."
    )


async def save_answers(
    session: AsyncSession, principal: Principal, attempt_id: uuid.UUID, body: AnswersIn
) -> SaveResult:
    now = datetime.now(UTC)
    attempt, questions = await _open_attempt(session, principal, attempt_id, now)
    # One answer per question per batch: the newest revision in the batch wins.
    latest: dict[uuid.UUID, tuple[int, AnswerIn]] = {}
    for i, answer in enumerate(body.answers):
        current = latest.get(answer.exam_question_id)
        if current is None or answer.client_revision > current[1].client_revision:
            latest[answer.exam_question_id] = (i, answer)

    saved: list[uuid.UUID] = []
    for qid, (index, answer) in latest.items():
        values = _check(index, answer, questions.get(str(qid)))
        statement = (
            insert(Answer)
            .values(
                attempt_id=attempt.id,
                exam_question_id=qid,
                institution_id=attempt.institution_id,
                client_revision=answer.client_revision,
                **values,
            )
            .on_conflict_do_update(
                index_elements=["attempt_id", "exam_question_id"],
                set_={**values, "client_revision": answer.client_revision, "updated_at": now},
                # Only a newer revision replaces what's stored (late or repeated saves are no-ops).
                where=Answer.client_revision < answer.client_revision,
            )
            .returning(Answer.exam_question_id)
        )
        if (await session.execute(statement)).first() is not None:
            saved.append(qid)
    await session.commit()
    return SaveResult(
        saved=saved,
        stale=[qid for qid in latest if qid not in saved],
        server_time=now,
        seconds_left=timer.seconds_left(attempt.deadline_at, now),
    )


async def set_flag(
    session: AsyncSession,
    principal: Principal,
    attempt_id: uuid.UUID,
    exam_question_id: uuid.UUID,
    body: FlagIn,
) -> None:
    """Mark or unmark a question for review (ATT-07)."""
    now = datetime.now(UTC)
    attempt, questions = await _open_attempt(session, principal, attempt_id, now)
    if str(exam_question_id) not in questions:
        raise not_found()
    await session.execute(
        update(AttemptQuestion)
        .where(
            AttemptQuestion.attempt_id == attempt.id,
            AttemptQuestion.exam_question_id == exam_question_id,
        )
        .values(marked_for_review=body.marked)
    )
    await session.commit()


async def save_draft(
    session: AsyncSession,
    principal: Principal,
    attempt_id: uuid.UUID,
    exam_question_id: uuid.UUID,
    body: DraftIn,
) -> DraftResult:
    """Unsubmitted code for a coding question, per language (only newer revisions are kept)."""
    now = datetime.now(UTC)
    attempt, questions = await _open_attempt(session, principal, attempt_id, now)
    question = questions.get(str(exam_question_id))
    if question is None:
        raise not_found()
    if question["type"] != "CODING":
        raise _invalid("exam_question_id", "Only coding questions have code drafts.")
    # Per-question language lists arrive with coding questions (E07); until then, any enabled one.
    enabled = await session.scalar(
        select(Language.key).where(Language.key == body.language_key, Language.enabled.is_(True))
    )
    if enabled is None:
        raise _invalid("language_key", "This language isn't available.")
    statement = (
        insert(CodeDraft)
        .values(
            attempt_id=attempt.id,
            exam_question_id=exam_question_id,
            language_key=body.language_key,
            institution_id=attempt.institution_id,
            source=body.source,
            client_revision=body.client_revision,
        )
        .on_conflict_do_update(
            index_elements=["attempt_id", "exam_question_id", "language_key"],
            set_={
                "source": body.source,
                "client_revision": body.client_revision,
                "updated_at": now,
            },
            where=CodeDraft.client_revision < body.client_revision,
        )
        .returning(CodeDraft.attempt_id)
    )
    stored = (await session.execute(statement)).first() is not None
    await session.commit()
    return DraftResult(
        saved=stored, server_time=now, seconds_left=timer.seconds_left(attempt.deadline_at, now)
    )
