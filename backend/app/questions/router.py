"""Question bank API for teachers (PRD QB-01, QB-07, QB-09). Admins and students have no access."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.questions import service
from app.questions.schemas import (
    QuestionCreate,
    QuestionPage,
    QuestionType,
    QuestionUpdate,
    QuestionView,
)

router = APIRouter(prefix="/questions", tags=["questions"])

Reader = Annotated[Principal, Depends(require(P.QUESTION_READ))]
Writer = Annotated[Principal, Depends(require(P.QUESTION_WRITE))]
Copier = Annotated[Principal, Depends(require(P.QUESTION_COPY))]


@router.get("")
async def list_questions(
    principal: Reader,
    db: TenantDB,
    q: Annotated[str | None, Query(max_length=200, description="Search the text and tags")] = None,
    type: QuestionType | None = None,
    tag: Annotated[str | None, Query(max_length=50)] = None,
    owner: Annotated[
        Literal["mine", "shared", "all"],
        Query(description="mine, shared by others in the institution, or both"),
    ] = "all",
    archived: Annotated[bool, Query(description="Show archived questions instead")] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> QuestionPage:
    """The question bank, newest first."""
    return await service.list_questions(
        db,
        principal,
        q=q,
        type=type,
        tag=tag,
        owner=owner,
        archived=archived,
        limit=limit,
        cursor=cursor,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_question(body: QuestionCreate, principal: Writer, db: TenantDB) -> QuestionView:
    return await service.view(db, principal, await service.create_question(db, principal, body))


@router.get("/{question_id}")
async def get_question(question_id: uuid.UUID, principal: Reader, db: TenantDB) -> QuestionView:
    """The full question with answer keys and rubric (teachers only)."""
    return await service.view(db, principal, await service.get_readable(db, principal, question_id))


@router.patch("/{question_id}")
async def update_question(
    question_id: uuid.UUID,
    body: QuestionUpdate,
    principal: Writer,
    db: TenantDB,
    response: Response,
) -> QuestionView:
    """Edit your question. If it's used by a published exam, content changes create a new version
    (the `X-New-Version: true` header says so); the exam keeps the old one."""
    question, new_version = await service.update_question(db, principal, question_id, body)
    if new_version:
        response.headers["X-New-Version"] = "true"
    return await service.view(db, principal, question)


@router.post("/{question_id}/copy", status_code=status.HTTP_201_CREATED)
async def copy_question(question_id: uuid.UUID, principal: Copier, db: TenantDB) -> QuestionView:
    """Make your own private copy of a question you can see."""
    return await service.view(
        db, principal, await service.copy_question(db, principal, question_id)
    )


@router.post("/{question_id}/archive")
async def archive_question(question_id: uuid.UUID, principal: Writer, db: TenantDB) -> QuestionView:
    """Hide it from the bank. Exams that already use it are not affected."""
    return await service.view(
        db, principal, await service.set_archived(db, principal, question_id, True)
    )


@router.post("/{question_id}/restore")
async def restore_question(question_id: uuid.UUID, principal: Writer, db: TenantDB) -> QuestionView:
    return await service.view(
        db, principal, await service.set_archived(db, principal, question_id, False)
    )
