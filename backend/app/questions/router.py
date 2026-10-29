"""Question bank API for teachers (PRD QB-01, QB-07, QB-09). Admins and students have no access."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.images.router import AppStorage
from app.questions import coding, service
from app.questions.schemas import (
    CodingIn,
    LanguageView,
    QuestionCreate,
    QuestionPage,
    QuestionType,
    QuestionUpdate,
    QuestionView,
    ReferenceIn,
    TestCaseIn,
    TestCaseOrder,
    TestCasePatch,
    TestCaseView,
)
from app.questions.student_view import StudentQuestion

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
async def create_question(
    body: QuestionCreate, principal: Writer, db: TenantDB, storage: AppStorage
) -> QuestionView:
    return await service.view(
        db, principal, await service.create_question(db, principal, body), storage
    )


@router.get("/{question_id}")
async def get_question(
    question_id: uuid.UUID, principal: Reader, db: TenantDB, storage: AppStorage
) -> QuestionView:
    """The full question with answer keys and rubric (teachers only)."""
    return await service.view(
        db, principal, await service.get_readable(db, principal, question_id), storage
    )


@router.patch("/{question_id}")
async def update_question(
    question_id: uuid.UUID,
    body: QuestionUpdate,
    principal: Writer,
    db: TenantDB,
    storage: AppStorage,
    response: Response,
) -> QuestionView:
    """Edit your question. If it's used by a published exam, content changes create a new version
    (the `X-New-Version: true` header says so); the exam keeps the old one."""
    question, new_version = await service.update_question(db, principal, question_id, body)
    if new_version:
        response.headers["X-New-Version"] = "true"
    return await service.view(db, principal, question, storage)


@router.get("/{question_id}/preview")
async def preview_question(
    question_id: uuid.UUID, principal: Reader, db: TenantDB, storage: AppStorage
) -> StudentQuestion:
    """The question exactly as a student sees it: no answer key, no rubric."""
    return await service.preview(db, principal, question_id, storage)


@router.post("/{question_id}/copy", status_code=status.HTTP_201_CREATED)
async def copy_question(
    question_id: uuid.UUID, principal: Copier, db: TenantDB, storage: AppStorage
) -> QuestionView:
    """Make your own private copy of a question you can see."""
    return await service.view(
        db, principal, await service.copy_question(db, principal, question_id), storage
    )


@router.post("/{question_id}/archive")
async def archive_question(
    question_id: uuid.UUID, principal: Writer, db: TenantDB, storage: AppStorage
) -> QuestionView:
    """Hide it from the bank. Exams that already use it are not affected."""
    return await service.view(
        db, principal, await service.set_archived(db, principal, question_id, True), storage
    )


@router.post("/{question_id}/restore")
async def restore_question(
    question_id: uuid.UUID, principal: Writer, db: TenantDB, storage: AppStorage
) -> QuestionView:
    return await service.view(
        db, principal, await service.set_archived(db, principal, question_id, False), storage
    )


# ----------------------------------------------------------------------------- coding (CQ-01..09)


def _new_version_header(response: Response, new_version: bool) -> None:
    if new_version:
        response.headers["X-New-Version"] = "true"


@router.put("/{question_id}/coding")
async def set_coding(
    question_id: uuid.UUID,
    body: CodingIn,
    principal: Writer,
    db: TenantDB,
    storage: AppStorage,
    response: Response,
) -> QuestionView:
    """Replace the coding setup: formats, languages and starter code, limits, comparison, scoring.
    Changes that affect results mark the question "needs validation" again."""
    question, new_version = await coding.set_coding(db, principal, question_id, body)
    _new_version_header(response, new_version)
    return await service.view(db, principal, question, storage)


@router.get("/{question_id}/test-cases")
async def list_test_cases(
    question_id: uuid.UUID, principal: Reader, db: TenantDB
) -> list[TestCaseView]:
    """Every test case of the current version, hidden ones included (teachers only)."""
    return await coding.list_cases(db, principal, question_id)


@router.post("/{question_id}/test-cases", status_code=status.HTTP_201_CREATED)
async def add_test_case(
    question_id: uuid.UUID, body: TestCaseIn, principal: Writer, db: TenantDB
) -> TestCaseView:
    """Add a test case at the end (50 at most). Public ones are the examples students see."""
    return await coding.add_case(db, principal, question_id, body)


@router.put("/{question_id}/test-cases/order")
async def reorder_test_cases(
    question_id: uuid.UUID, body: TestCaseOrder, principal: Writer, db: TenantDB
) -> list[TestCaseView]:
    """Set the order: every test case's id, once each."""
    return await coding.reorder_cases(db, principal, question_id, body)


@router.patch("/{question_id}/test-cases/{case_id}")
async def update_test_case(
    question_id: uuid.UUID,
    case_id: uuid.UUID,
    body: TestCasePatch,
    principal: Writer,
    db: TenantDB,
) -> TestCaseView:
    return await coding.update_case(db, principal, question_id, case_id, body)


@router.delete("/{question_id}/test-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case(
    question_id: uuid.UUID, case_id: uuid.UUID, principal: Writer, db: TenantDB
) -> None:
    await coding.delete_case(db, principal, question_id, case_id)


@router.put("/{question_id}/reference-solutions/{language_key}")
async def set_reference_solution(
    question_id: uuid.UUID,
    language_key: Annotated[str, Path(max_length=32)],
    body: ReferenceIn,
    principal: Writer,
    db: TenantDB,
    storage: AppStorage,
    response: Response,
) -> QuestionView:
    """Save your solution in one of the allowed languages; validation runs it on every test case."""
    question, new_version = await coding.set_reference(
        db, principal, question_id, language_key, body
    )
    _new_version_header(response, new_version)
    return await service.view(db, principal, question, storage)


@router.delete("/{question_id}/reference-solutions/{language_key}")
async def delete_reference_solution(
    question_id: uuid.UUID,
    language_key: Annotated[str, Path(max_length=32)],
    principal: Writer,
    db: TenantDB,
    storage: AppStorage,
    response: Response,
) -> QuestionView:
    question, new_version = await coding.delete_reference(db, principal, question_id, language_key)
    _new_version_header(response, new_version)
    return await service.view(db, principal, question, storage)


languages_router = APIRouter(prefix="/languages", tags=["questions"])


@languages_router.get("")
async def list_languages(principal: Reader, db: TenantDB) -> list[LanguageView]:
    """Languages a coding question can allow (PRD CQ-02), with their time multipliers."""
    return await coding.list_languages(db)
