"""Coding questions for teachers: problem setup, test cases, reference solutions (PRD CQ-01..09).

Everything goes through the question's owner and its current version. If that version is locked
(a published exam uses it), the first change copies the whole coding setup into a new version, the
same way other question edits do (QB-07). Any change that could change results (limits, languages,
comparison, test cases, reference solutions) marks the question "needs validation" again (CQ-09).

Hidden test cases are teacher-only data: nothing here is ever used to build a student view.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.auth.tokens import Principal
from app.core.errors import AppError
from app.core.markdown import sanitize_markdown
from app.platform.models import Language
from app.questions import service
from app.questions.models import (
    MAX_CASE_BYTES,
    MAX_SOURCE_BYTES,
    CodingConfig,
    Question,
    QuestionVersion,
    ReferenceSolution,
    TestCase,
)
from app.questions.schemas import (
    MAX_STARTER_BYTES,
    MAX_TEST_CASES,
    CodingIn,
    CodingView,
    LanguageChoice,
    LanguageView,
    ReferenceIn,
    ReferenceView,
    TestCaseIn,
    TestCaseOrder,
    TestCasePatch,
    TestCaseView,
)

# Settings that can't change a run's outcome, so changing them keeps the validation.
NO_REVALIDATION = {
    "input_format",
    "output_format",
    "constraints",
    "partial_scoring",
    "run_code_allowed",
    "max_submissions",
}


# ----------------------------------------------------------------------------- loading


def _refuse(code: str, message: str, status_code: int = 409, field: str | None = None) -> AppError:
    details = [{"field": field, "message": message, "type": "coding_rule"}] if field else None
    return AppError(code, message, status_code=status_code, details=details)


def _audit(
    session: AsyncSession,
    principal: Principal,
    action: str,
    question: Question,
    changes: dict[str, Any],
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


def _coding_only(question: Question) -> None:
    if question.type != "CODING":
        raise _refuse("NOT_CODING", "Only coding questions have test cases and languages.")


async def _config(session: AsyncSession, version_id: uuid.UUID) -> CodingConfig:
    config = await session.get(CodingConfig, version_id)
    if config is None:  # every coding version gets one when it's created
        config = CodingConfig(version_id=version_id)
        session.add(config)
        await session.flush()
    return config


async def _cases(session: AsyncSession, version_id: uuid.UUID) -> list[TestCase]:
    rows = await session.scalars(
        select(TestCase).where(TestCase.version_id == version_id).order_by(TestCase.order_index)
    )
    return list(rows)


async def _references(session: AsyncSession, version_id: uuid.UUID) -> list[ReferenceSolution]:
    rows = await session.scalars(
        select(ReferenceSolution)
        .where(ReferenceSolution.version_id == version_id)
        .order_by(ReferenceSolution.language_key)
    )
    return list(rows)


async def readable(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID
) -> QuestionVersion:
    """The current version of a coding question the caller can see (own or shared)."""
    question = await service.get_readable(session, principal, question_id)
    _coding_only(question)
    return await service.current_version(session, question)


async def editable(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID
) -> tuple[Question, QuestionVersion, bool]:
    """The owner's current version, ready to change. A locked one is copied into a new version
    first (with its coding setup); the bool says whether that happened."""
    question = await service.get_writable(session, principal, question_id)
    _coding_only(question)
    version = await service.current_version(session, question)
    if not version.is_locked:
        return question, version, False
    latest = await session.scalar(
        select(func.max(QuestionVersion.version_no)).where(
            QuestionVersion.question_id == question.id
        )
    )
    fresh = QuestionVersion(
        question_id=question.id,
        version_no=(latest or 0) + 1,
        created_by=principal.user_id,
        **{field: getattr(version, field) for field in service.CONTENT_FIELDS},
    )
    session.add(fresh)
    await session.flush()
    await copy_setup(session, version.id, fresh.id)
    question.current_version_id = fresh.id
    return question, fresh, True


async def copy_setup(session: AsyncSession, source_id: uuid.UUID, target_id: uuid.UUID) -> None:
    """Copy a version's coding setup, test cases and references onto another version. The copy
    starts unvalidated: validation belongs to the version that was run."""
    config = await session.get(CodingConfig, source_id)
    if config is None:
        session.add(CodingConfig(version_id=target_id))
        return
    copied = {
        column.key: getattr(config, column.key)
        for column in CodingConfig.__table__.columns
        if column.key
        not in (
            "version_id",
            "institution_id",
            "validation_status",
            "validation_report",
            "bundle_key",
        )
    }
    session.add(CodingConfig(version_id=target_id, **copied))
    for case in await _cases(session, source_id):
        session.add(
            TestCase(
                version_id=target_id,
                visibility=case.visibility,
                weight=case.weight,
                input=case.input,
                expected_output=case.expected_output,
                order_index=case.order_index,
            )
        )
    for ref in await _references(session, source_id):
        session.add(
            ReferenceSolution(
                version_id=target_id, language_key=ref.language_key, source=ref.source
            )
        )
    await session.flush()


def _needs_validation(config: CodingConfig) -> None:
    config.validation_status = "NEEDS_VALIDATION"
    config.validation_report = None


def _touch(question: Question) -> None:
    question.updated_at = datetime.now(UTC)  # the change is in another table


# ----------------------------------------------------------------------------- view


async def view(session: AsyncSession, version: QuestionVersion) -> CodingView:
    config = await _config(session, version.id)
    cases = await _cases(session, version.id)
    references = await _references(session, version.id)
    allowed = [LanguageChoice(**choice) for choice in config.allowed_languages]
    hidden = sum(c.visibility == "HIDDEN" for c in cases)
    allowed_keys = {c.language_key for c in allowed}

    blocks: list[str] = []
    if not allowed:
        blocks.append("Choose at least one language.")
    if not hidden:
        blocks.append("Add at least one hidden test case.")
    if not any(r.language_key in allowed_keys for r in references):
        blocks.append("Add a reference solution in one of the allowed languages.")
    return CodingView(
        input_format=config.input_format,
        output_format=config.output_format,
        constraints=config.constraints,
        allowed_languages=allowed,
        time_limit_ms=config.time_limit_ms,
        memory_limit_mb=config.memory_limit_mb,
        comparison_mode=config.comparison_mode,  # type: ignore[arg-type]
        partial_scoring=config.partial_scoring,
        run_code_allowed=config.run_code_allowed,
        max_submissions=config.max_submissions,
        validation_status=config.validation_status,  # type: ignore[arg-type]
        validation_report=config.validation_report,
        test_case_count=len(cases),
        hidden_test_case_count=hidden,
        reference_solutions=[
            ReferenceView(language_key=r.language_key, source=r.source) for r in references
        ],
        blocks=blocks,
    )


def case_view(case: TestCase) -> TestCaseView:
    return TestCaseView(
        id=case.id,
        visibility=case.visibility,  # type: ignore[arg-type]
        weight=case.weight,
        input=case.input,
        expected_output=case.expected_output,
        order_index=case.order_index,
    )


async def list_languages(session: AsyncSession) -> list[LanguageView]:
    rows = await session.scalars(
        select(Language).where(Language.enabled).order_by(Language.display_name)
    )
    return [
        LanguageView(
            key=r.key, display_name=r.display_name, time_multiplier=float(r.time_multiplier)
        )
        for r in rows
    ]


# ----------------------------------------------------------------------------- setup


async def set_coding(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID, body: CodingIn
) -> tuple[Question, bool]:
    question, version, new_version = await editable(session, principal, question_id)
    config = await _config(session, version.id)

    keys = [c.language_key for c in body.allowed_languages]
    if len(set(keys)) != len(keys):
        raise _refuse(
            "VALIDATION_FAILED", "Each language can be chosen once.", 422, "allowed_languages"
        )
    known = set(
        await session.scalars(select(Language.key).where(Language.enabled, Language.key.in_(keys)))
    )
    for i, key in enumerate(keys):
        if key not in known:
            raise _refuse(
                "VALIDATION_FAILED",
                f"Unknown language: {key}.",
                422,
                f"allowed_languages.{i}.language_key",
            )
    for i, choice in enumerate(body.allowed_languages):
        if len(choice.starter_code.encode()) > MAX_STARTER_BYTES:
            raise _refuse(
                "VALIDATION_FAILED",
                "Starter code is too long (64 KB at most).",
                422,
                f"allowed_languages.{i}.starter_code",
            )

    new = body.model_dump()
    for field in ("input_format", "output_format", "constraints"):
        new[field] = sanitize_markdown(new[field]).strip()
    changes: dict[str, Any] = {
        field: {"old": getattr(config, field), "new": value}
        for field, value in new.items()
        if getattr(config, field) != value
    }
    if not changes:
        return question, new_version
    for field, value in new.items():
        setattr(config, field, value)
    if set(changes) - NO_REVALIDATION:
        _needs_validation(config)
    # A reference in a language that's no longer allowed can't be used: remove it.
    dropped = await session.execute(
        delete(ReferenceSolution)
        .where(
            ReferenceSolution.version_id == version.id, ReferenceSolution.language_key.not_in(keys)
        )
        .returning(ReferenceSolution.language_key)
    )
    removed = list(dropped.scalars())
    if removed:
        changes["reference_solutions_removed"] = removed
    if "allowed_languages" in changes:
        changes["allowed_languages"] = {
            "old": [c["language_key"] for c in changes["allowed_languages"]["old"]],
            "new": keys,
        }
    _touch(question)
    _audit(session, principal, "question.coding_updated", question, changes)
    await session.commit()
    return question, new_version


# ----------------------------------------------------------------------------- test cases


def _check_size(field: str, value: str) -> None:
    if len(value.encode()) > MAX_CASE_BYTES:
        raise _refuse("VALIDATION_FAILED", "Too long: 1 MB at most.", 422, field)


async def list_cases(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID
) -> list[TestCaseView]:
    version = await readable(session, principal, question_id)
    return [case_view(c) for c in await _cases(session, version.id)]


async def add_case(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID, body: TestCaseIn
) -> TestCaseView:
    question, version, _ = await editable(session, principal, question_id)
    _check_size("input", body.input)
    _check_size("expected_output", body.expected_output)
    cases = await _cases(session, version.id)
    if len(cases) >= MAX_TEST_CASES:
        raise _refuse("TOO_MANY_TEST_CASES", f"A question has {MAX_TEST_CASES} test cases at most.")
    case = TestCase(
        version_id=version.id,
        visibility=body.visibility,
        weight=body.weight,
        input=body.input,
        expected_output=body.expected_output,
        order_index=(cases[-1].order_index + 1) if cases else 0,
    )
    session.add(case)
    _needs_validation(await _config(session, version.id))
    _touch(question)
    await session.flush()
    _audit(
        session,
        principal,
        "question.test_case_added",
        question,
        {"test_case": str(case.id), "visibility": case.visibility},
    )
    await session.commit()
    return case_view(case)


async def _case_of(session: AsyncSession, version: QuestionVersion, case_id: uuid.UUID) -> TestCase:
    """A test case of this version. After a locked version was copied, the id the teacher sent
    belongs to the old version: the copy at the same position is meant."""
    case = await session.get(TestCase, case_id)
    if case is None:
        raise AppError("NOT_FOUND", "Test case not found.", status_code=404)
    if case.version_id == version.id:
        return case
    copy = await session.scalar(
        select(TestCase).where(
            TestCase.version_id == version.id, TestCase.order_index == case.order_index
        )
    )
    question_version = await session.get(QuestionVersion, case.version_id)
    if (
        copy is None
        or question_version is None
        or question_version.question_id != version.question_id
    ):
        raise AppError("NOT_FOUND", "Test case not found.", status_code=404)
    return copy


async def update_case(
    session: AsyncSession,
    principal: Principal,
    question_id: uuid.UUID,
    case_id: uuid.UUID,
    body: TestCasePatch,
) -> TestCaseView:
    question, version, _ = await editable(session, principal, question_id)
    case = await _case_of(session, version, case_id)
    changes: dict[str, Any] = {}
    for field in body.model_fields_set:
        value = getattr(body, field)
        if value is None:
            continue
        if field in ("input", "expected_output"):
            _check_size(field, value)
        if getattr(case, field) != value:
            changes[field] = (
                {"old": getattr(case, field), "new": value}
                if field in ("visibility", "weight")
                else "changed"
            )
            setattr(case, field, value)
    if changes:
        _needs_validation(await _config(session, version.id))
        _touch(question)
        _audit(
            session,
            principal,
            "question.test_case_updated",
            question,
            {"test_case": str(case.id), **changes},
        )
        await session.commit()
    return case_view(case)


async def delete_case(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID, case_id: uuid.UUID
) -> None:
    question, version, _ = await editable(session, principal, question_id)
    case = await _case_of(session, version, case_id)
    await session.delete(case)
    await session.flush()
    for i, rest in enumerate(await _cases(session, version.id)):  # close the gap
        rest.order_index = i
    _needs_validation(await _config(session, version.id))
    _touch(question)
    _audit(session, principal, "question.test_case_deleted", question, {"test_case": str(case_id)})
    await session.commit()


async def reorder_cases(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID, body: TestCaseOrder
) -> list[TestCaseView]:
    question, version, _ = await editable(session, principal, question_id)
    cases = await _cases(session, version.id)
    wanted = [(await _case_of(session, version, case_id)).id for case_id in body.ids]
    if sorted(wanted) != sorted(c.id for c in cases):
        raise _refuse("VALIDATION_FAILED", "List every test case exactly once.", 422, "ids")
    by_id = {c.id: c for c in cases}
    if wanted != [c.id for c in cases]:
        for i, case_id in enumerate(wanted):
            by_id[case_id].order_index = i  # the unique check waits for the commit
        _touch(question)
        _audit(
            session, principal, "question.test_cases_reordered", question, {"count": len(wanted)}
        )
        await session.commit()
    return [case_view(by_id[i]) for i in wanted]


# ----------------------------------------------------------------------------- reference solutions


async def set_reference(
    session: AsyncSession,
    principal: Principal,
    question_id: uuid.UUID,
    language_key: str,
    body: ReferenceIn,
) -> tuple[Question, bool]:
    question, version, new_version = await editable(session, principal, question_id)
    config = await _config(session, version.id)
    if language_key not in {c["language_key"] for c in config.allowed_languages}:
        raise _refuse(
            "LANGUAGE_NOT_ALLOWED",
            "Allow this language for the question first.",
            422,
            "language_key",
        )
    if len(body.source.encode()) > MAX_SOURCE_BYTES:
        raise _refuse(
            "VALIDATION_FAILED", "The solution is too long (256 KB at most).", 422, "source"
        )
    reference = await session.scalar(
        select(ReferenceSolution).where(
            ReferenceSolution.version_id == version.id,
            ReferenceSolution.language_key == language_key,
        )
    )
    if reference is not None and reference.source == body.source:
        return question, new_version
    if reference is None:
        session.add(
            ReferenceSolution(version_id=version.id, language_key=language_key, source=body.source)
        )
    else:
        reference.source = body.source
    _needs_validation(config)
    _touch(question)
    _audit(session, principal, "question.reference_saved", question, {"language": language_key})
    await session.commit()
    return question, new_version


async def delete_reference(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID, language_key: str
) -> tuple[Question, bool]:
    question, version, new_version = await editable(session, principal, question_id)
    result = await session.execute(
        delete(ReferenceSolution).where(
            ReferenceSolution.version_id == version.id,
            ReferenceSolution.language_key == language_key,
        )
    )
    if result.rowcount:  # type: ignore[attr-defined]
        _needs_validation(await _config(session, version.id))
        _touch(question)
        _audit(
            session, principal, "question.reference_deleted", question, {"language": language_key}
        )
    await session.commit()
    return question, new_version
