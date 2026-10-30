"""Run Code during an exam (PRD EXE-02, EXE-03; TECHNICAL_ARCHITECTURE.md § 9.2; TCK-0808).

A student tries their code on the question's public test cases (or on input they type) without it
counting. Rules, checked with the attempt row locked so quick double clicks can't slip past:

- the attempt is theirs, in progress, and before its deadline (runs aren't graded: no grace);
- the question is a coding question, Run Code is on for the exam and for the question, and the
  language is one it allows;
- one run at a time, at least 8 s between runs, and at most 20 per question.

The job asks for public cases only, and the result consumer keeps public cases only, so a run can
never show anything hidden. Runs are deleted after 24 hours.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.attempt import snapshot_of
from app.attempts.models import ExamAttempt
from app.attempts.saving import open_attempt
from app.auth.tokens import Principal
from app.authz.ownership import get_owned
from app.core.errors import AppError
from app.core.storage import Storage
from app.db.session import SessionFactory, system_session
from app.execution import queue
from app.execution.models import CodeRun
from app.platform.models import Language
from app.questions import bundles
from app.questions.models import CodingConfig
from app.questions.validation import LINK_SECONDS, effective_limit_ms
from domain_core import timer
from workers import queues
from workers.exec_messages import ExecJob, LanguageSpec

RUN_GAP = timedelta(seconds=8)
MAX_RUNS_PER_QUESTION = 20
KEEP_FOR = timedelta(hours=24)
POLL_MS = 1000


class RunIn(BaseModel):
    language_key: str = Field(max_length=32)
    source: str = Field(min_length=1, max_length=262_144)
    custom_input: str | None = Field(
        default=None, max_length=65_536, description="Run on this input instead of the examples"
    )


class RunView(BaseModel):
    id: uuid.UUID
    status: str = Field(description="QUEUED, COMPLETED or FAILED (the platform couldn't run it)")
    language_key: str
    custom_input: bool
    created_at: datetime
    finished_at: datetime | None
    compile_output: str | None
    results: list[dict[str, Any]] | None = Field(
        description="Per public case: input, expected and actual output, passed, time. Custom "
        "input: the output only"
    )
    runs_left: int = Field(description="Runs still allowed on this question")
    poll_after_ms: int | None = Field(description="Ask again after this long while QUEUED")


def _refuse(code: str, message: str, status_code: int = 409, **details: Any) -> AppError:
    # A 429 always says how long to wait in the standard header too (SECURITY § 11).
    wait = details.get("retry_after_s")
    return AppError(
        code,
        message,
        status_code=status_code,
        details=[details] if details else None,
        headers={"Retry-After": str(wait)} if wait is not None else None,
    )


async def _count(session: AsyncSession, attempt_id: uuid.UUID, eq_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(CodeRun)
            .where(CodeRun.attempt_id == attempt_id, CodeRun.exam_question_id == eq_id)
        )
        or 0
    )


async def view(session: AsyncSession, run: CodeRun) -> RunView:
    used = await _count(session, run.attempt_id, run.exam_question_id)
    return RunView(
        id=run.id,
        status=run.status,
        language_key=run.language_key,
        custom_input=run.custom_input is not None,
        created_at=run.created_at,
        finished_at=run.finished_at,
        compile_output=run.compile_output,
        results=run.results,
        runs_left=max(0, MAX_RUNS_PER_QUESTION - used),
        poll_after_ms=POLL_MS if run.status == "QUEUED" else None,
    )


async def start(
    session: AsyncSession,
    principal: Principal,
    attempt_id: uuid.UUID,
    exam_question_id: uuid.UUID,
    body: RunIn,
    storage: Storage,
) -> RunView:
    now = datetime.now(UTC)
    attempt, questions = await open_attempt(session, principal, attempt_id, now)
    # One request at a time per attempt from here on: the checks below can't race.
    await session.execute(
        select(ExamAttempt.id).where(ExamAttempt.id == attempt.id).with_for_update()
    )
    if timer.seconds_left(attempt.deadline_at, now) <= 0:
        raise _refuse("TIME_UP", "Time is up: code can't be run any more.")
    question = questions.get(str(exam_question_id))
    if question is None:
        raise AppError("NOT_FOUND", "Not found.", status_code=404)
    settings = (await snapshot_of(session, attempt)).get("settings", {})
    coding = question.get("coding") or {}
    if question["type"] != "CODING":
        raise _refuse("NOT_CODING", "Only coding questions can be run.")
    if not settings.get("run_code_enabled", True) or not coding.get("run_code_allowed", True):
        raise _refuse("RUN_CODE_OFF", "Run Code isn't available for this question. Submit instead.")
    if body.language_key not in {lang["key"] for lang in coding.get("languages", [])}:
        raise _refuse("LANGUAGE_NOT_ALLOWED", "This question doesn't allow that language.", 422)

    in_flight = await session.scalar(
        select(func.count())
        .select_from(CodeRun)
        .where(CodeRun.attempt_id == attempt.id, CodeRun.status == "QUEUED")
    )
    if in_flight:
        raise _refuse("RUN_IN_PROGRESS", "Your last run is still going. Wait for its result.")
    last = await session.scalar(
        select(func.max(CodeRun.created_at)).where(CodeRun.attempt_id == attempt.id)
    )
    if last is not None and now - last < RUN_GAP:
        wait = int((RUN_GAP - (now - last)).total_seconds()) + 1
        raise _refuse(
            "RUN_TOO_SOON", f"Wait {wait} s before running again.", 429, retry_after_s=wait
        )
    if await _count(session, attempt.id, exam_question_id) >= MAX_RUNS_PER_QUESTION:
        raise _refuse(
            "RUN_LIMIT",
            f"You've used all {MAX_RUNS_PER_QUESTION} runs for this question. "
            "You can still submit.",
        )

    version_id = uuid.UUID(question["version_id"])
    config = await session.get(CodingConfig, version_id)
    language = await session.scalar(select(Language).where(Language.key == body.language_key))
    if config is None or language is None:
        raise AppError("INTERNAL_ERROR", "Coding setup missing.", status_code=500)
    bundle_key = config.bundle_key
    if body.custom_input is None and bundle_key is None:
        # A preview of a draft whose bundle isn't built yet (published versions always have one).
        locked = await session.scalar(
            select(CodingConfig).where(CodingConfig.version_id == version_id).with_for_update()
        )
        bundle_key = await bundles.ensure(session, storage, locked) if locked else None

    run = CodeRun(
        attempt_id=attempt.id,
        institution_id=attempt.institution_id,
        exam_question_id=exam_question_id,
        language_key=language.key,
        source=body.source,
        custom_input=body.custom_input,
        created_at=now,
    )
    session.add(run)
    await session.flush()
    job = ExecJob(
        job_id=str(run.id),
        kind="run",
        language=LanguageSpec(
            key=language.key,
            image=language.image,
            source_filename=language.source_filename,
            compile_cmd=language.compile_cmd,
            run_cmd=language.run_cmd,
        ),
        time_limit_ms=effective_limit_ms(config.time_limit_ms, language.time_multiplier),
        memory_limit_mb=config.memory_limit_mb,
        source=body.source,
        bundle_url=storage.internal_url(bundles.BUNDLES, bundle_key, LINK_SECONDS)
        if bundle_key and body.custom_input is None
        else None,
        bundle_sha256=bundle_key.rsplit("/", 1)[1].removesuffix(".tar")
        if bundle_key and body.custom_input is None
        else None,
        cases="public",
        custom_input=body.custom_input,
    )
    await session.commit()
    queue.send(job, queues.EXEC_RUN)  # after the commit, so the result finds the run
    return await view(session, run)


async def get_run(session: AsyncSession, principal: Principal, run_id: uuid.UUID) -> RunView:
    """The caller's own run (anyone else's is 404)."""
    run = await get_owned(session, CodeRun, run_id, principal, owned=lambda r: True)
    attempt = await session.get(ExamAttempt, run.attempt_id)
    if attempt is None or attempt.student_id != principal.user_id:
        raise AppError("NOT_FOUND", "Not found.", status_code=404)
    return await view(session, run)


async def delete_old_runs(factory: SessionFactory, now: datetime | None = None) -> int:
    """Runs are practice: deleted after 24 hours (all institutions)."""
    cutoff = (now or datetime.now(UTC)) - KEEP_FOR
    async with system_session(factory) as session:
        result = await session.execute(delete(CodeRun).where(CodeRun.created_at < cutoff))
        await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
