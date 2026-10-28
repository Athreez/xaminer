"""The question bank for teachers (PRD QB-01, QB-07, QB-09; SECURITY_AND_ACCESS.md § 3).

Teachers read and copy their own questions and those shared with the institution; only the owner
edits or archives. Content lives in versions: editing a locked version (one a published exam uses)
adds a new version instead, so grades stay explainable. Every change is audit-logged.
"""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import get_owned
from app.core.errors import AppError
from app.core.pagination import MAX_PAGE, decode_cursor, encode_cursor, like_pattern
from app.questions.models import Question, QuestionOption, QuestionVersion
from app.questions.schemas import (
    OptionIn,
    OptionView,
    Owner,
    QuestionCreate,
    QuestionPage,
    QuestionSummary,
    QuestionUpdate,
    QuestionView,
    VersionView,
)
from app.users.models import User

# Fields that belong to a version (content), as opposed to the question row (visibility, tags).
CONTENT_FIELDS = ("body", "points", "negative_marks", "msq_scoring", "max_answer_length", "rubric")


def _unique_tags(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(tags))


def _audit(
    session: AsyncSession,
    principal: Principal,
    action: str,
    question: Question,
    changes: dict[str, Any] | None = None,
) -> None:
    record(
        session,
        action,
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="question",
        target_id=question.id,
        changes=changes,
    )


# ----------------------------------------------------------------------------- loading


def _readable(principal: Principal):  # type: ignore[no-untyped-def]
    return lambda q: q.owner_id == principal.user_id or q.visibility == "INSTITUTION"


async def get_readable(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID
) -> Question:
    """Own questions and those shared with the institution; anything else is 404."""
    return await get_owned(session, Question, question_id, principal, owned=_readable(principal))


async def get_writable(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID
) -> Question:
    """Only the owner may change a question. A shared one is visible, so that's a 403, not a 404."""
    question = await get_readable(session, principal, question_id)
    if question.owner_id != principal.user_id:
        raise AppError(
            "NOT_OWNER",
            "Only the owner can change this question. Copy it to edit your own.",
            status_code=403,
        )
    return question


async def _current(session: AsyncSession, question: Question) -> QuestionVersion:
    version = await session.get(QuestionVersion, question.current_version_id)
    if version is None:  # every question is created with a version; this is a broken row
        raise AppError("INTERNAL_ERROR", "Question has no version.", status_code=500)
    return version


async def _options(session: AsyncSession, version_id: uuid.UUID) -> list[QuestionOption]:
    rows = await session.scalars(
        select(QuestionOption)
        .where(QuestionOption.version_id == version_id)
        .order_by(QuestionOption.order_index)
    )
    return list(rows)


async def view(session: AsyncSession, principal: Principal, question: Question) -> QuestionView:
    await session.refresh(question)  # updated_at is set by the database on every change
    version = await _current(session, question)
    owner = await session.get(User, question.owner_id)
    return QuestionView(
        id=question.id,
        type=question.type,  # type: ignore[arg-type]
        visibility=question.visibility,  # type: ignore[arg-type]
        tags=question.tags,
        owner=Owner(id=question.owner_id, full_name=owner.full_name if owner else ""),
        is_mine=question.owner_id == principal.user_id,
        archived_at=question.archived_at,
        created_at=question.created_at,
        updated_at=question.updated_at,
        version=VersionView(
            id=version.id,
            version_no=version.version_no,
            body=version.body,
            points=version.points,
            negative_marks=version.negative_marks,
            msq_scoring=version.msq_scoring,  # type: ignore[arg-type]
            max_answer_length=version.max_answer_length,
            rubric=version.rubric,
            is_locked=version.is_locked,
            created_at=version.created_at,
            options=[
                OptionView(
                    id=o.id, label=o.label, is_correct=o.is_correct, order_index=o.order_index
                )
                for o in await _options(session, version.id)
            ],
        ),
    )


# ----------------------------------------------------------------------------- listing

_MARKDOWN_NOISE = re.compile(r"[#*_`>~\[\]!|]|^\s*[-+]\s+|\(\S+\)")


def title_of(body: str, limit: int = 120) -> str:
    """The first non-empty line, with Markdown symbols removed, cut at `limit` characters."""
    line = next((ln for ln in body.splitlines() if ln.strip()), "")
    plain = " ".join(_MARKDOWN_NOISE.sub("", line).split())
    return plain if len(plain) <= limit else plain[: limit - 1].rstrip() + "…"


async def list_questions(
    session: AsyncSession,
    principal: Principal,
    *,
    q: str | None,
    type: str | None,
    tag: str | None,
    owner: str,
    archived: bool,
    limit: int,
    cursor: str | None,
) -> QuestionPage:
    """Newest first. `owner`: "mine", "shared" (others' shared questions) or "all" (both)."""
    limit = max(1, min(limit, MAX_PAGE))
    query: Select[Question, QuestionVersion, str] = (
        select(Question, QuestionVersion, User.full_name)
        .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
        .join(User, User.id == Question.owner_id)
        .order_by(Question.id.desc())
        .limit(limit + 1)
    )
    mine = Question.owner_id == principal.user_id
    shared = (Question.visibility == "INSTITUTION") & (Question.owner_id != principal.user_id)
    query = query.where({"mine": mine, "shared": shared}.get(owner, or_(mine, shared)))
    query = query.where(
        Question.archived_at.is_not(None) if archived else Question.archived_at.is_(None)
    )
    if type:
        query = query.where(Question.type == type)
    if tag and tag.strip():
        query = query.where(Question.tags.contains([tag.strip().lower()]))
    if q and q.strip():
        text = q.strip()
        # Whole words through the full-text index, and any part of a word through ILIKE.
        words = func.to_tsvector("simple", QuestionVersion.body).op("@@")(
            func.websearch_to_tsquery("simple", text)
        )
        query = query.where(
            or_(
                words,
                QuestionVersion.body.ilike(like_pattern(text), escape="\\"),
                func.array_to_string(Question.tags, " ").ilike(like_pattern(text), escape="\\"),
            )
        )
    if cursor:
        query = query.where(Question.id < decode_cursor(cursor))
    rows = (await session.execute(query)).all()
    page, more = rows[:limit], len(rows) > limit
    return QuestionPage(
        data=[
            QuestionSummary(
                id=question.id,
                type=question.type,  # type: ignore[arg-type]
                visibility=question.visibility,  # type: ignore[arg-type]
                tags=question.tags,
                owner=Owner(id=question.owner_id, full_name=owner_name),
                is_mine=question.owner_id == principal.user_id,
                title=title_of(version.body),
                points=version.points,
                version_no=version.version_no,
                is_locked=version.is_locked,
                archived_at=question.archived_at,
                updated_at=question.updated_at,
            )
            for question, version, owner_name in page
        ],
        next_cursor=encode_cursor(page[-1][0].id) if more and page else None,
    )


# ----------------------------------------------------------------------------- changing


def _add_options(session: AsyncSession, version_id: uuid.UUID, options: list[OptionIn]) -> None:
    session.add_all(
        QuestionOption(version_id=version_id, label=o.label, is_correct=o.is_correct, order_index=i)
        for i, o in enumerate(options)
    )


async def _new_question(
    session: AsyncSession,
    principal: Principal,
    *,
    type: str,
    visibility: str,
    tags: list[str],
    content: dict[str, Any],
    options: list[OptionIn],
) -> Question:
    question = Question(
        owner_id=principal.user_id, type=type, visibility=visibility, tags=_unique_tags(tags)
    )
    session.add(question)
    await session.flush()
    version = QuestionVersion(
        question_id=question.id, version_no=1, created_by=principal.user_id, **content
    )
    session.add(version)
    await session.flush()
    _add_options(session, version.id, options)
    question.current_version_id = version.id
    return question


async def create_question(
    session: AsyncSession, principal: Principal, body: QuestionCreate
) -> Question:
    question = await _new_question(
        session,
        principal,
        type=body.type,
        visibility=body.visibility,
        tags=body.tags,
        content={field: getattr(body, field) for field in CONTENT_FIELDS},
        options=body.options,
    )
    _audit(session, principal, "question.created", question, {"type": body.type})
    await session.commit()
    return question


def _jsonable(value: Any) -> Any:
    return (
        str(value)
        if value is not None and not isinstance(value, str | int | bool | list)
        else value
    )


async def update_question(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID, body: QuestionUpdate
) -> tuple[Question, bool]:
    """Apply the changes. Returns the question and whether a new version was created."""
    question = await get_writable(session, principal, question_id)
    version = await _current(session, question)
    sent = body.model_fields_set
    changes: dict[str, Any] = {}

    if "visibility" in sent and body.visibility and body.visibility != question.visibility:
        changes["visibility"] = {"old": question.visibility, "new": body.visibility}
        question.visibility = body.visibility
    if "tags" in sent and body.tags is not None:
        tags = _unique_tags(body.tags)
        if tags != question.tags:
            changes["tags"] = {"old": question.tags, "new": tags}
            question.tags = tags

    content = {field: getattr(version, field) for field in CONTENT_FIELDS}
    for field in CONTENT_FIELDS:
        if field in sent and (
            field in ("msq_scoring", "max_answer_length", "rubric")
            or getattr(body, field) is not None
        ):
            new = getattr(body, field)
            if new != content[field]:
                changes[field] = {"old": _jsonable(content[field]), "new": _jsonable(new)}
                content[field] = new
    old_options = await _options(session, version.id)
    options = [OptionIn(label=o.label, is_correct=o.is_correct) for o in old_options]
    if "options" in sent and body.options is not None and body.options != options:
        changes["options"] = {"old": len(options), "new": len(body.options)}
        options = body.options

    if not changes:
        return question, False
    content_changed = any(f in changes for f in (*CONTENT_FIELDS, "options"))
    new_version = content_changed and version.is_locked
    if new_version:
        latest = await session.scalar(
            select(func.max(QuestionVersion.version_no)).where(
                QuestionVersion.question_id == question.id
            )
        )
        version = QuestionVersion(
            question_id=question.id,
            version_no=(latest or 0) + 1,
            created_by=principal.user_id,
            **content,
        )
        session.add(version)
        await session.flush()
        _add_options(session, version.id, options)
        question.current_version_id = version.id
        changes["version_no"] = {"old": version.version_no - 1, "new": version.version_no}
    elif content_changed:
        for field, value in content.items():
            setattr(version, field, value)
        if "options" in changes:
            await session.execute(
                delete(QuestionOption).where(QuestionOption.version_id == version.id)
            )
            _add_options(session, version.id, options)
    if content_changed:
        question.updated_at = datetime.now(UTC)  # the row itself may not have changed
    _audit(session, principal, "question.updated", question, changes)
    await session.commit()
    return question, new_version


async def copy_question(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID
) -> Question:
    """A private copy owned by the caller, starting at version 1 (PRD QB-09)."""
    source = await get_readable(session, principal, question_id)
    version = await _current(session, source)
    options = [
        OptionIn(label=o.label, is_correct=o.is_correct)
        for o in await _options(session, version.id)
    ]
    copy = await _new_question(
        session,
        principal,
        type=source.type,
        visibility="PRIVATE",
        tags=source.tags,
        content={field: getattr(version, field) for field in CONTENT_FIELDS},
        options=options,
    )
    _audit(
        session,
        principal,
        "question.copied",
        copy,
        {"from_question": str(source.id), "from_version": version.version_no},
    )
    await session.commit()
    return copy


async def set_archived(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID, archived: bool
) -> Question:
    """Archived questions leave the bank list; exams that use them keep working (PRD QB-09)."""
    question = await get_writable(session, principal, question_id)
    if (question.archived_at is not None) == archived:
        return question
    question.archived_at = datetime.now(UTC) if archived else None
    _audit(session, principal, "question.archived" if archived else "question.restored", question)
    await session.commit()
    return question
