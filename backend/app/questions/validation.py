"""Validating a coding question with the teacher's reference solutions (PRD CQ-08, CQ-09; TCK-0705).

`start` runs every reference solution against every test case on the exec-worker: one
`exec.validation` job per language. `apply_result` (app-worker) compares the outputs. The question
passes only when every reference passes every case; the report shows each case's time and warns
about any case using more than half the time limit (it may fail for students on a slower day).

Each run has its own id, part of the job ids. A result for an older run, or one arriving after an
edit reset the status to NEEDS_VALIDATION, is ignored; so is a repeat.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.auth.tokens import Principal
from app.core.errors import AppError
from app.core.storage import Storage
from app.execution import queue
from app.platform.models import Language
from app.questions import bundles, coding, service
from app.questions.models import CodingConfig, Question, ReferenceSolution
from app.questions.test_cases import all_test_cases
from domain_core.coding_score import CaseOutcome, case_outcome
from domain_core.compare import matches
from workers import queues
from workers.exec_messages import ExecJob, ExecResult, LanguageSpec

LINK_SECONDS = 300  # the bundle link the exec-worker gets (SECURITY_AND_ACCESS.md § 7.2)
SLOW_SHARE = 0.5  # a case using more than half the time limit gets a warning (CQ-08)
KEPT_OUTPUT = 2048


def job_id(version_id: uuid.UUID, run: str, language: str) -> str:
    return f"validation:{version_id}:{run}:{language}"


def effective_limit_ms(base_ms: int, multiplier: Decimal) -> int:
    """The time limit a language really gets (PRD CQ-03)."""
    return int(Decimal(base_ms) * multiplier)


async def start(
    session: AsyncSession, principal: Principal, question_id: uuid.UUID, storage: Storage
) -> Question:
    """Queue a validation run of the current version. Refused while something blocks it."""
    question = await service.get_writable(session, principal, question_id)
    version = await coding.readable(session, principal, question_id)
    if version.is_locked:
        raise AppError(
            "QUESTION_LOCKED",
            "This version is used by a published exam and was validated then. Edit the question "
            "to make a new version, then validate that.",
            status_code=409,
        )
    blocks = (await coding.view(session, version)).blocks
    if blocks:
        raise AppError(
            "VALIDATION_BLOCKED",
            blocks[0],
            status_code=409,
            details=[{"message": b} for b in blocks],
        )
    config = await session.scalar(
        select(CodingConfig).where(CodingConfig.version_id == version.id).with_for_update()
    )
    if config is None:  # coding.view creates one; this can't happen
        raise AppError("INTERNAL_ERROR", "Coding setup missing.", status_code=500)
    allowed = {c["language_key"] for c in config.allowed_languages}
    references = [
        r
        for r in await session.scalars(
            select(ReferenceSolution).where(ReferenceSolution.version_id == version.id)
        )
        if r.language_key in allowed
    ]
    languages = {
        lang.key: lang
        for lang in await session.scalars(
            select(Language).where(Language.key.in_([r.language_key for r in references]))
        )
    }
    key = await bundles.ensure(session, storage, config)
    run = uuid.uuid4().hex[:12]
    config.validation_status = "VALIDATING"
    config.validation_report = {
        "run": run,
        "started_at": datetime.now(UTC).isoformat(),
        "pending": sorted(languages),
        "languages": {},
    }
    jobs = []
    for reference in references:
        language = languages[reference.language_key]
        jobs.append(
            ExecJob(
                job_id=job_id(version.id, run, language.key),
                kind="validation",
                language=LanguageSpec(
                    key=language.key,
                    image=language.image,
                    source_filename=language.source_filename,
                    compile_cmd=language.compile_cmd,
                    run_cmd=language.run_cmd,
                ),
                time_limit_ms=effective_limit_ms(config.time_limit_ms, language.time_multiplier),
                memory_limit_mb=config.memory_limit_mb,
                source=reference.source,
                bundle_url=storage.internal_url(bundles.BUNDLES, key, LINK_SECONDS),
                bundle_sha256=key.rsplit("/", 1)[1].removesuffix(".tar"),
            )
        )
    record(
        session,
        "question.validation_started",
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="question",
        target_id=question.id,
        changes={"languages": sorted(languages)},
    )
    await session.commit()
    for job in jobs:  # after the commit, so a fast result finds the run
        queue.send(job, queues.EXEC_VALIDATION)
    return question


async def apply_result(session: AsyncSession, result: ExecResult) -> str:
    """Record one language's validation result; decide when the last one is in."""
    try:
        _, version_text, run, language_key = result.job_id.split(":")
        version_id = uuid.UUID(version_text)
    except ValueError:
        return "ignored"
    config = await session.scalar(
        select(CodingConfig).where(CodingConfig.version_id == version_id).with_for_update()
    )
    report = config.validation_report if config else None
    if (
        config is None
        or report is None
        or config.validation_status != "VALIDATING"
        or report.get("run") != run
        or language_key in report.get("languages", {})
    ):
        return "ignored"  # stale (edited since, newer run) or a repeat

    language = await session.scalar(select(Language).where(Language.key == language_key))
    limit = effective_limit_ms(
        config.time_limit_ms, language.time_multiplier if language else Decimal(1)
    )
    entry = _language_report(result, await all_test_cases(session, version_id), config, limit)

    languages = {**report.get("languages", {}), language_key: entry}
    pending = [k for k in report.get("pending", []) if k != language_key]
    updated: dict[str, Any] = {**report, "languages": languages, "pending": pending}
    if not pending:
        passed = all(e["status"] == "PASSED" for e in languages.values())
        config.validation_status = "PASSED" if passed else "FAILED"
        updated["finished_at"] = datetime.now(UTC).isoformat()
        updated["warnings"] = [w for e in languages.values() for w in e["warnings"]]
    config.validation_report = updated  # a new dict, so the change is saved
    return "validated" if not pending else "recorded"


def _language_report(
    result: ExecResult, cases: list[Any], config: CodingConfig, limit_ms: int
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "time_limit_ms": limit_ms,
        "compile_output": (
            (result.compile.stderr or result.compile.stdout)[-KEPT_OUTPUT:]
            if result.compile
            else None
        ),
        "cases": [],
        "warnings": [],
    }
    if result.status == "FAILED":
        entry |= {"status": "ERROR", "error": "The platform couldn't run it. Try again."}
        return entry
    if not result.compiled:
        entry["status"] = "FAILED"
        entry["warnings"].append(
            f"{result.job_id.rsplit(':', 1)[1]}: the reference didn't compile."
        )
        return entry
    by_name = {c.name: c for c in result.cases}
    all_passed = True
    for i, case in enumerate(cases, start=1):
        name = f"{i:03d}"
        step = by_name.get(name)
        if step is None:
            entry |= {"status": "ERROR", "error": "Results don't match the test cases. Try again."}
            return entry
        outcome = case_outcome(
            timed_out=step.timed_out,
            memory_exceeded=step.memory_exceeded,
            output_exceeded=step.output_exceeded,
            exit_code=step.exit_code,
            output_matches=matches(config.comparison_mode, case.expected_output, step.stdout),  # type: ignore[arg-type]
        )
        slow = step.time_ms > SLOW_SHARE * limit_ms
        all_passed &= outcome == CaseOutcome.PASSED
        entry["cases"].append(
            {
                "name": name,
                "test_case_id": str(case.id),
                "hidden": case.visibility == "HIDDEN",
                "outcome": outcome,
                "time_ms": step.time_ms,
                "slow": slow,
                "stdout": step.stdout[:KEPT_OUTPUT] if outcome != CaseOutcome.PASSED else None,
                "stderr": step.stderr[-KEPT_OUTPUT:] or None,
            }
        )
        if slow:
            language = result.job_id.rsplit(":", 1)[1]
            entry["warnings"].append(
                f"{language}: test {i} took {step.time_ms} ms, over half the {limit_ms} ms limit."
            )
    entry["status"] = "PASSED" if all_passed else "FAILED"
    return entry
