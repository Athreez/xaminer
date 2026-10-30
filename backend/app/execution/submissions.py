"""Submit Code (PRD EXE-04, EXE-05, EXE-07; TCK-0809).

An official, graded submission. Rules, checked with the attempt row locked so concurrent
requests can't get past them (the counter can never go over the limit):

- the attempt is the student's and still takes saves (deadline plus 60 s grace, like answers);
- a coding question in an allowed language;
- at least 5 s between submissions, and the question's limit (automatic ones at the end don't
  count, EXE-06).

Submissions are never dropped when the system is busy: they wait on `exec.submit`. What a student
sees of the result: verdict, score, passed/total; public cases in full; hidden cases as "Hidden
test N: Passed / Failed" only, never their input, output, timing or errors (CQ-05, FRONTEND_SPEC
§ 7.4).
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.attempt import snapshot_of
from app.attempts.models import ExamAttempt
from app.attempts.saving import open_attempt
from app.auth.tokens import Principal
from app.authz.ownership import get_owned
from app.core.errors import AppError
from app.core.storage import Storage
from app.exams.models import Exam
from app.execution import queue
from app.execution.models import CodingEvaluation, CodingSubmission, TestCaseResult
from app.platform.models import Language
from app.questions import bundles
from app.questions.models import CodingConfig
from app.questions.test_cases import positions, public_examples
from app.questions.validation import LINK_SECONDS, effective_limit_ms
from workers import queues
from workers.exec_messages import ExecJob, LanguageSpec

SUBMIT_GAP = timedelta(seconds=5)
POLL_MS = 1500


class SubmitIn(BaseModel):
    language_key: str = Field(max_length=32)
    source: str = Field(min_length=1, max_length=262_144)


class CaseShown(BaseModel):
    """One test case as the student may see it. Hidden ones carry only their number and whether
    they passed."""

    number: int
    hidden: bool
    passed: bool
    outcome: str | None = Field(description="Public cases only, e.g. WRONG_ANSWER")
    input: str | None = None
    expected_output: str | None = None
    stdout: str | None = None
    time_ms: int | None = None


class SubmissionView(BaseModel):
    id: uuid.UUID
    submission_no: int
    language_key: str
    source: str
    created_at: datetime
    status: str = Field(description="QUEUED, EVALUATED or FAILED (the platform couldn't grade it)")
    is_counted: bool = Field(description="This one gives the question's score (EXE-05)")
    is_auto: bool = Field(description="Submitted automatically when the attempt ended")
    verdict: str | None
    score: Decimal | None
    max_score: Decimal | None
    passed_cases: int | None
    total_cases: int | None
    compile_output: str | None
    cases: list[CaseShown]
    poll_after_ms: int | None


class SubmissionHistory(BaseModel):
    submissions: list[SubmissionView] = Field(description="Newest first")
    submissions_left: int
    max_submissions: int


def _refuse(code: str, message: str, status_code: int = 409, **details: Any) -> AppError:
    return AppError(code, message, status_code=status_code, details=[details] if details else None)


async def _latest_evaluation(
    session: AsyncSession, submission_id: uuid.UUID
) -> CodingEvaluation | None:
    return await session.scalar(
        select(CodingEvaluation)
        .where(CodingEvaluation.submission_id == submission_id)
        .order_by(CodingEvaluation.evaluation_no.desc())
        .limit(1)
    )


async def view(
    session: AsyncSession, submission: CodingSubmission, version_id: uuid.UUID
) -> SubmissionView:
    evaluation = await _latest_evaluation(session, submission.id)
    cases: list[CaseShown] = []
    passed = total = None
    if evaluation is not None and evaluation.status == "DONE":
        results = list(
            await session.scalars(
                select(TestCaseResult).where(TestCaseResult.evaluation_id == evaluation.id)
            )
        )
        public = {c.id: c for c in await public_examples(session, version_id)}
        place = await positions(session, [r.test_case_id for r in results])
        for r in sorted(results, key=lambda r: place.get(r.test_case_id, 0)):
            shown = public.get(r.test_case_id)
            ok = r.outcome == "PASSED"
            if shown is None:  # hidden: number and pass/fail only
                cases.append(
                    CaseShown(
                        number=place.get(r.test_case_id, 0), hidden=True, passed=ok, outcome=None
                    )
                )
            else:
                cases.append(
                    CaseShown(
                        number=place.get(r.test_case_id, 0),
                        hidden=False,
                        passed=ok,
                        outcome=r.outcome,
                        input=shown.input,
                        expected_output=shown.expected_output,
                        stdout=r.stdout,
                        time_ms=r.time_ms,
                    )
                )
        passed, total = sum(c.passed for c in cases), len(cases)
        if evaluation.verdict == "COMPILE_ERROR":
            passed, total = 0, None
    return SubmissionView(
        id=submission.id,
        submission_no=submission.submission_no,
        language_key=submission.language_key,
        source=submission.source,
        created_at=submission.created_at,
        status=submission.status,
        is_counted=submission.is_counted,
        is_auto=submission.is_auto,
        verdict=evaluation.verdict if evaluation else None,
        score=evaluation.score if evaluation else None,
        max_score=evaluation.max_score if evaluation else None,
        passed_cases=passed,
        total_cases=total,
        compile_output=evaluation.compile_output if evaluation else None,
        cases=cases,
        poll_after_ms=POLL_MS if submission.status == "QUEUED" else None,
    )


async def _question(
    session: AsyncSession, attempt: ExamAttempt, eq_id: uuid.UUID
) -> dict[str, Any]:
    for q in (await snapshot_of(session, attempt))["questions"]:
        if q["exam_question_id"] == str(eq_id):
            return q  # type: ignore[no-any-return]
    raise AppError("NOT_FOUND", "Not found.", status_code=404)


async def _used(session: AsyncSession, attempt_id: uuid.UUID, eq_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(CodingSubmission)
            .where(
                CodingSubmission.attempt_id == attempt_id,
                CodingSubmission.exam_question_id == eq_id,
                CodingSubmission.is_auto.is_(False),
            )
        )
        or 0
    )


async def submit(
    session: AsyncSession,
    principal: Principal,
    attempt_id: uuid.UUID,
    exam_question_id: uuid.UUID,
    body: SubmitIn,
    storage: Storage,
) -> SubmissionView:
    now = datetime.now(UTC)
    attempt, questions = await open_attempt(session, principal, attempt_id, now)
    # From here on one request at a time per attempt: the counter and gap can't race.
    await session.execute(
        select(ExamAttempt.id).where(ExamAttempt.id == attempt.id).with_for_update()
    )
    question = questions.get(str(exam_question_id))
    if question is None:
        raise AppError("NOT_FOUND", "Not found.", status_code=404)
    if question["type"] != "CODING":
        raise _refuse("NOT_CODING", "Only coding questions take code submissions.")
    coding = question.get("coding") or {}
    if body.language_key not in {lang["key"] for lang in coding.get("languages", [])}:
        raise _refuse("LANGUAGE_NOT_ALLOWED", "This question doesn't allow that language.", 422)

    last = await session.scalar(
        select(func.max(CodingSubmission.created_at)).where(
            CodingSubmission.attempt_id == attempt.id, CodingSubmission.is_auto.is_(False)
        )
    )
    if last is not None and now - last < SUBMIT_GAP:
        wait = int((SUBMIT_GAP - (now - last)).total_seconds()) + 1
        raise _refuse(
            "SUBMIT_TOO_SOON", f"Wait {wait} s before submitting again.", 429, retry_after_s=wait
        )
    limit = int(coding.get("max_submissions", 10))
    if await _used(session, attempt.id, exam_question_id) >= limit:
        raise _refuse("SUBMISSION_LIMIT", f"You've used all {limit} submissions for this question.")

    submission, job = await create(
        session,
        attempt,
        question,
        language_key=body.language_key,
        source=body.source,
        storage=storage,
        now=now,
    )
    await session.commit()
    queue.send(job, queues.EXEC_SUBMIT)  # after the commit, so the result finds the job
    return await view(session, submission, uuid.UUID(question["version_id"]))


async def create(
    session: AsyncSession,
    attempt: ExamAttempt,
    question: dict[str, Any],
    *,
    language_key: str,
    source: str,
    storage: Storage,
    now: datetime,
    auto: bool = False,
) -> tuple[CodingSubmission, ExecJob]:
    """The next submission of this question, its first evaluation (QUEUED) and the job to send
    once the caller has committed. `auto`: the last draft, submitted when the attempt ended."""
    exam_question_id = uuid.UUID(question["exam_question_id"])
    version_id = uuid.UUID(question["version_id"])
    config = await session.scalar(
        select(CodingConfig).where(CodingConfig.version_id == version_id).with_for_update()
    )
    language = await session.scalar(select(Language).where(Language.key == language_key))
    if config is None or language is None:
        raise AppError("INTERNAL_ERROR", "Coding setup missing.", status_code=500)
    bundle_key = config.bundle_key or await bundles.ensure(session, storage, config)
    number = 1 + int(
        await session.scalar(
            select(func.coalesce(func.max(CodingSubmission.submission_no), 0)).where(
                CodingSubmission.attempt_id == attempt.id,
                CodingSubmission.exam_question_id == exam_question_id,
            )
        )
        or 0
    )
    submission = CodingSubmission(
        attempt_id=attempt.id,
        institution_id=attempt.institution_id,
        exam_question_id=exam_question_id,
        submission_no=number,
        language_key=language.key,
        source=source,
        created_at=now,
        is_auto=auto,
    )
    session.add(submission)
    await session.flush()
    evaluation = CodingEvaluation(
        submission_id=submission.id,
        institution_id=attempt.institution_id,
        max_score=Decimal(str(question["points"])),
    )
    session.add(evaluation)
    await session.flush()
    job = ExecJob(
        job_id=str(evaluation.id),
        kind="submit",
        language=LanguageSpec(
            key=language.key,
            image=language.image,
            source_filename=language.source_filename,
            compile_cmd=language.compile_cmd,
            run_cmd=language.run_cmd,
        ),
        time_limit_ms=effective_limit_ms(config.time_limit_ms, language.time_multiplier),
        memory_limit_mb=config.memory_limit_mb,
        source=source,
        bundle_url=storage.internal_url(bundles.BUNDLES, bundle_key, LINK_SECONDS),
        bundle_sha256=bundle_key.rsplit("/", 1)[1].removesuffix(".tar"),
        cases="all",
    )
    return submission, job


async def _readable_attempt(
    session: AsyncSession, principal: Principal, attempt_id: uuid.UUID
) -> ExamAttempt:
    """The student's own attempt, or one of an exam the teacher owns (anyone else: 404)."""
    attempt = await get_owned(session, ExamAttempt, attempt_id, principal, owned=lambda a: True)
    if attempt.student_id == principal.user_id:
        return attempt
    if principal.role == "TEACHER":
        exam = await session.get(Exam, attempt.exam_id)
        if exam is not None and exam.owner_id == principal.user_id:
            return attempt
    raise AppError("NOT_FOUND", "Not found.", status_code=404)


async def get_submission(
    session: AsyncSession, principal: Principal, submission_id: uuid.UUID
) -> SubmissionView:
    submission = await get_owned(
        session, CodingSubmission, submission_id, principal, owned=lambda s: True
    )
    attempt = await _readable_attempt(session, principal, submission.attempt_id)
    question = await _question(session, attempt, submission.exam_question_id)
    return await view(session, submission, uuid.UUID(question["version_id"]))


async def history(
    session: AsyncSession, principal: Principal, attempt_id: uuid.UUID, exam_question_id: uuid.UUID
) -> SubmissionHistory:
    attempt = await _readable_attempt(session, principal, attempt_id)
    question = await _question(session, attempt, exam_question_id)
    version_id = uuid.UUID(question["version_id"])
    rows = await session.scalars(
        select(CodingSubmission)
        .where(
            CodingSubmission.attempt_id == attempt.id,
            CodingSubmission.exam_question_id == exam_question_id,
        )
        .order_by(CodingSubmission.submission_no.desc())
    )
    limit = int((question.get("coding") or {}).get("max_submissions", 10))
    used = await _used(session, attempt.id, exam_question_id)
    return SubmissionHistory(
        submissions=[await view(session, s, version_id) for s in rows],
        submissions_left=max(0, limit - used),
        max_submissions=limit,
    )
