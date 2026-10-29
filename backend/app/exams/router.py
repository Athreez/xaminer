"""Exam API: teachers manage their own exams; admins see a metadata-only list (PRD EX-01, EX-03,
EX-08; SECURITY_AND_ACCESS.md § 3)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.core.errors import AppError
from app.exams import service
from app.exams.schemas import AdminExamPage, ExamCreate, ExamPage, ExamStatus, ExamUpdate, ExamView

router = APIRouter(prefix="/exams", tags=["exams"])
admin_router = APIRouter(prefix="/admin/exams", tags=["exams"])

# Only teachers hold exam:write, so these routes are the exam author's.
Author = Annotated[Principal, Depends(require(P.EXAM_WRITE))]
Search = Annotated[str | None, Query(max_length=100, description="Search titles")]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("")
async def list_exams(
    principal: Author,
    db: TenantDB,
    status: ExamStatus | None = None,
    q: Search = None,
    limit: Limit = 50,
    cursor: str | None = None,
) -> ExamPage:
    """Your exams, newest first."""
    return await service.list_own(db, principal, status=status, q=q, limit=limit, cursor=cursor)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_exam(body: ExamCreate, principal: Author, db: TenantDB) -> ExamView:
    """Create a draft. Settings not sent take their defaults (PRD § 6.3)."""
    return await service.view(db, await service.create_exam(db, principal, body))


@router.get("/{exam_id}")
async def get_exam(exam_id: uuid.UUID, principal: Author, db: TenantDB) -> ExamView:
    return await service.view(db, await service.get_own(db, principal, exam_id))


@router.patch("/{exam_id}")
async def update_exam(
    exam_id: uuid.UUID, body: ExamUpdate, principal: Author, db: TenantDB
) -> ExamView:
    """Change settings. Once published only `close_at` may change; other fields return 409
    `EXAM_PUBLISHED` naming the field."""
    return await service.view(db, await service.update_exam(db, principal, exam_id, body))


@router.delete("/{exam_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exam(exam_id: uuid.UUID, principal: Author, db: TenantDB) -> None:
    """Delete a draft. Published exams are archived instead, so their results stay."""
    await service.delete_exam(db, principal, exam_id)


@router.post("/{exam_id}/archive")
async def archive_exam(exam_id: uuid.UUID, principal: Author, db: TenantDB) -> ExamView:
    return await service.view(db, await service.archive_exam(db, principal, exam_id))


@admin_router.get("")
async def list_exams_for_admin(
    principal: Annotated[Principal, Depends(require(P.EXAM_READ))],
    db: TenantDB,
    status: ExamStatus | None = None,
    q: Search = None,
    limit: Limit = 50,
    cursor: str | None = None,
) -> AdminExamPage:
    """Every exam in the institution: title, owner, window and status only."""
    # Students also hold exam:read (for their assigned exams), so this list checks the role too.
    if principal.role != "ADMIN":
        raise AppError("FORBIDDEN", "You don't have permission to do this.", status_code=403)
    return await service.list_for_admin(db, status=status, q=q, limit=limit, cursor=cursor)
