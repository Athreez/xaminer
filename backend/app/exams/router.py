"""Exam API: teachers manage their own exams; admins see a metadata-only list (PRD EX-01, EX-03,
EX-08; SECURITY_AND_ACCESS.md § 3)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.attempts import preview as previews
from app.attempts.attempt import AttemptView
from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.exams import assignments, composition, service
from app.exams import publish as publishing
from app.exams import publish_check as publish_checks
from app.exams.assignments import (
    Assignments,
    AssignRequest,
    AssignResult,
    StudentChoice,
)
from app.exams.composition import ExamQuestions, ExamQuestionsIn
from app.exams.publish_check import PublishCheck
from app.exams.schemas import AdminExamPage, ExamCreate, ExamPage, ExamStatus, ExamUpdate, ExamView
from app.images.router import AppStorage

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


@router.get("/{exam_id}/questions")
async def get_exam_questions(exam_id: uuid.UUID, principal: Author, db: TenantDB) -> ExamQuestions:
    """The exam's questions in order, with the marks each is worth here."""
    return await composition.get_questions(db, principal, exam_id)


@router.put("/{exam_id}/questions")
async def set_exam_questions(
    exam_id: uuid.UUID, body: ExamQuestionsIn, principal: Author, db: TenantDB
) -> ExamQuestions:
    """Replace the whole ordered list in one step: add, remove, reorder and set marks. Drafts
    only. Your own questions and those shared with the institution can be used."""
    return await composition.set_questions(db, principal, exam_id, body)


@router.get("/{exam_id}/assignments")
async def list_assignments(exam_id: uuid.UUID, principal: Author, db: TenantDB) -> Assignments:
    """Students who may take the exam."""
    return await assignments.list_assignments(db, principal, exam_id)


@router.post("/{exam_id}/assignments")
async def assign_students(
    exam_id: uuid.UUID, body: AssignRequest, principal: Author, db: TenantDB
) -> AssignResult:
    """Assign groups and/or students. A group adds each of its students; deactivated students are
    skipped and students already assigned are left alone. Not for archived exams."""
    return await assignments.assign(db, principal, exam_id, body)


@router.delete("/{exam_id}/assignments/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_student(
    exam_id: uuid.UUID, student_id: uuid.UUID, principal: Author, db: TenantDB
) -> None:
    await assignments.unassign(db, principal, exam_id, student_id)


@router.get("/{exam_id}/student-choices")
async def student_choices(
    exam_id: uuid.UUID,
    principal: Author,
    db: TenantDB,
    q: Annotated[str | None, Query(max_length=100, description="Name, email or roll no.")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[StudentChoice]:
    """Students who could be assigned to this exam, for the picker (name, email, roll no.)."""
    return await assignments.search_students(db, principal, exam_id, q, limit)


@router.get("/{exam_id}/publish-check")
async def publish_check(exam_id: uuid.UUID, principal: Author, db: TenantDB) -> PublishCheck:
    """What blocks publishing and what is only a warning (PRD § 6.4), each naming what to fix."""
    return await publish_checks.check_own(db, principal, exam_id)


@router.post("/{exam_id}/publish")
async def publish_exam(exam_id: uuid.UUID, principal: Author, db: TenantDB) -> ExamView:
    """Publish: refused with 409 `PUBLISH_BLOCKED` (listing each block) until the publish check
    passes. Pins and locks question versions and freezes the exam. Afterwards only the window's
    end and the assignments can change."""
    return await service.view(db, await publishing.publish(db, principal, exam_id))


@router.post("/{exam_id}/preview-attempt")
async def preview_attempt(
    exam_id: uuid.UUID, principal: Author, db: TenantDB, storage: AppStorage
) -> AttemptView:
    """Take your own exam as a student would (draft or published). Replaces your previous
    preview. Previews never count in results. Continue it with the usual /attempts endpoints."""
    return await previews.start_preview(db, principal, exam_id, storage)


@admin_router.get("")
async def list_exams_for_admin(
    principal: Annotated[Principal, Depends(require(P.EXAM_LIST_ALL))],
    db: TenantDB,
    status: ExamStatus | None = None,
    q: Search = None,
    limit: Limit = 50,
    cursor: str | None = None,
) -> AdminExamPage:
    """Every exam in the institution: title, owner, window and status only (admins)."""
    return await service.list_for_admin(db, status=status, q=q, limit=limit, cursor=cursor)
