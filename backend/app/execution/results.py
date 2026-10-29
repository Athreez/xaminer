"""Turning raw execution results into grades (TECHNICAL_ARCHITECTURE.md § 9.2; TCK-0806).

app-worker receives what the exec-worker ran. Here, and only here, outputs are compared with the
expected ones and scored (domain_core), because the worker that ran untrusted code is never
trusted with a grade.

- Submissions: the evaluation (the job) must exist and be QUEUED, else the message is a repeat
  and is ignored. Each case is compared and given an outcome, the score and verdict computed,
  evaluation and per-case results saved with their weights, the counted submission updated
  (BEST or LAST), and the attempt's grading moved on once no code is waiting.
- Run Code: public cases compared, results kept for the student (never graded).
- A platform failure records INTERNAL_ERROR with no score (EXE-08), never 0.
"""

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.attempt import snapshot_of
from app.attempts.models import ExamAttempt
from app.db.session import SessionFactory, system_session
from app.execution.models import CodeRun, CodingEvaluation, CodingSubmission, TestCaseResult
from app.questions.models import CodingConfig
from app.questions.test_cases import all_test_cases, public_examples
from domain_core.coding_score import CaseOutcome, Verdict, case_outcome, score
from domain_core.compare import matches
from workers.exec_messages import ExecResult, StepResult

logger = logging.getLogger(__name__)

KEPT_OUTPUT = 4096  # characters of a case's stdout and stderr kept for the teacher


def _outcome(step: StepResult, expected: str | None, mode: str) -> CaseOutcome:
    return case_outcome(
        timed_out=step.timed_out,
        memory_exceeded=step.memory_exceeded,
        output_exceeded=step.output_exceeded,
        exit_code=step.exit_code,
        output_matches=expected is not None and matches(mode, expected, step.stdout),  # type: ignore[arg-type]
    )


def _compile_output(result: ExecResult) -> str | None:
    if result.compile is None:
        return None
    return (result.compile.stderr or result.compile.stdout)[-KEPT_OUTPUT:]


async def handle(factory: SessionFactory, result: ExecResult) -> str:
    """Apply one result. Returns what happened: "evaluated", "failed", "run", or "ignored"."""
    async with system_session(factory) as session:
        if result.kind == "submit":
            outcome = await _evaluation(session, result)
        elif result.kind == "run":
            outcome = await _code_run(session, result)
        else:
            outcome = "ignored"  # teacher validation: TCK-0705
        await session.commit()
    logger.info("execution result applied", extra={"job_id": result.job_id, "outcome": outcome})
    return outcome


# ----------------------------------------------------------------------------- submissions


async def _evaluation(session: AsyncSession, result: ExecResult) -> str:
    evaluation = await session.scalar(
        select(CodingEvaluation)
        .where(CodingEvaluation.id == uuid.UUID(result.job_id))
        .with_for_update()
    )
    if evaluation is None or evaluation.status != "QUEUED":
        return "ignored"  # unknown, or already applied: results may arrive twice
    submission = await session.get_one(CodingSubmission, evaluation.submission_id)
    attempt = await session.get_one(ExamAttempt, submission.attempt_id)
    question = next(
        q
        for q in (await snapshot_of(session, attempt))["questions"]
        if q["exam_question_id"] == str(submission.exam_question_id)
    )
    version_id = uuid.UUID(question["version_id"])
    config = await session.get(CodingConfig, version_id)
    cases = await all_test_cases(session, version_id)
    evaluation.image_digest = result.image_digest
    evaluation.compile_output = _compile_output(result)
    evaluation.evaluated_at = datetime.now(UTC)

    compiled = result.compiled
    by_name = {c.name: c for c in result.cases}
    expected_names = [f"{i:03d}" for i in range(1, len(cases) + 1)]
    broken = (
        result.status == "FAILED" or not cases or (compiled and sorted(by_name) != expected_names)
    )
    if config is None or broken:
        evaluation.status, evaluation.verdict, evaluation.score = (
            "FAILED",
            Verdict.INTERNAL_ERROR,
            None,
        )
        submission.status = "FAILED"
        await _after(session, submission, attempt, question)
        return "failed"

    outcomes: list[tuple[int, CaseOutcome]] = []
    for name, case in zip(expected_names, cases, strict=True):
        step = by_name.get(name)
        if step is None:  # didn't compile: nothing ran
            outcomes.append((case.weight, CaseOutcome.WRONG_ANSWER))
            continue
        outcome = _outcome(step, case.expected_output, config.comparison_mode)
        outcomes.append((case.weight, outcome))
        session.add(
            TestCaseResult(
                evaluation_id=evaluation.id,
                institution_id=evaluation.institution_id,
                test_case_id=case.id,
                weight=case.weight,
                outcome=outcome,
                time_ms=step.time_ms,
                memory_kb=step.memory_kb,
                stdout=step.stdout[:KEPT_OUTPUT],
                stderr=step.stderr[-KEPT_OUTPUT:],
            )
        )
    points = Decimal(str(question["points"]))
    graded = score(
        points, compiled=compiled, partial_scoring=config.partial_scoring, cases=outcomes
    )
    evaluation.status = "DONE"
    evaluation.verdict = graded.verdict
    evaluation.passed_weight, evaluation.total_weight = graded.passed_weight, graded.total_weight
    evaluation.score, evaluation.max_score = graded.score, points
    submission.status = "EVALUATED"
    await _after(session, submission, attempt, question)
    return "evaluated"


async def _after(
    session: AsyncSession,
    submission: CodingSubmission,
    attempt: ExamAttempt,
    question: dict[str, Any],
) -> None:
    await session.flush()
    await recount(session, attempt, submission.exam_question_id)
    await _move_grading_on(session, attempt)


async def recount(session: AsyncSession, attempt: ExamAttempt, exam_question_id: uuid.UUID) -> None:
    """Mark the submission that counts for this question (EXE-05): the best latest-evaluation
    score (the later one on a tie) or the last evaluated one, as the exam says. Submissions the
    platform failed to evaluate never count."""
    snapshot = await snapshot_of(session, attempt)
    rule = snapshot.get("settings", {}).get("counted_submission", "BEST")
    latest = (
        select(
            CodingEvaluation.submission_id,
            func.max(CodingEvaluation.evaluation_no).label("evaluation_no"),
        )
        .group_by(CodingEvaluation.submission_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(CodingSubmission, CodingEvaluation)
            .join(latest, latest.c.submission_id == CodingSubmission.id)
            .join(
                CodingEvaluation,
                (CodingEvaluation.submission_id == latest.c.submission_id)
                & (CodingEvaluation.evaluation_no == latest.c.evaluation_no),
            )
            .where(
                CodingSubmission.attempt_id == attempt.id,
                CodingSubmission.exam_question_id == exam_question_id,
            )
        )
    ).all()
    scored = [(s, e) for s, e in rows if e.status == "DONE" and e.score is not None]
    chosen = None
    if scored:
        key = (
            (lambda pair: pair[0].submission_no)
            if rule == "LAST"
            else (lambda pair: (pair[1].score, pair[0].submission_no))
        )
        chosen = max(scored, key=key)[0]
    for submission, _ in rows:
        submission.is_counted = submission is chosen


async def _move_grading_on(session: AsyncSession, attempt: ExamAttempt) -> None:
    """Once no submission of a finished attempt is waiting for its code to run, grading moves on
    to the teacher (descriptive answers) or is complete (§ 9.5)."""
    if attempt.grading_status != "AWAITING_CODING":
        return
    waiting = await session.scalar(
        select(func.count())
        .select_from(CodingEvaluation)
        .join(CodingSubmission, CodingSubmission.id == CodingEvaluation.submission_id)
        .where(CodingSubmission.attempt_id == attempt.id, CodingEvaluation.status == "QUEUED")
    )
    if waiting:
        return
    questions = (await snapshot_of(session, attempt))["questions"]
    descriptive = any(q["type"] == "DESCRIPTIVE" for q in questions)
    attempt.grading_status = "AWAITING_MANUAL" if descriptive else "COMPLETE"


# ----------------------------------------------------------------------------- Run Code


async def _code_run(session: AsyncSession, result: ExecResult) -> str:
    run = await session.scalar(
        select(CodeRun).where(CodeRun.id == uuid.UUID(result.job_id)).with_for_update()
    )
    if run is None or run.status != "QUEUED":
        return "ignored"
    run.finished_at = datetime.now(UTC)
    run.compile_output = _compile_output(result)
    if result.status == "FAILED":
        run.status = "FAILED"
        return "failed"
    attempt = await session.get_one(ExamAttempt, run.attempt_id)
    question = next(
        q
        for q in (await snapshot_of(session, attempt))["questions"]
        if q["exam_question_id"] == str(run.exam_question_id)
    )
    version_id = uuid.UUID(question["version_id"])
    config = await session.get(CodingConfig, version_id)
    mode = config.comparison_mode if config else "TRIM"
    # Public cases only, named by their position in the bundle: what the student may see.
    expected = {f"{c.order_index + 1:03d}": c for c in await public_examples(session, version_id)}
    shown = []
    for step in result.cases:
        case = expected.get(step.name)
        if step.name != "custom" and case is None:
            continue  # never report anything about a case that isn't public
        outcome = _outcome(step, case.expected_output if case else None, mode)
        shown.append(
            {
                "name": step.name,
                "input": case.input if case else run.custom_input,
                "expected_output": case.expected_output if case else None,
                "stdout": step.stdout[:KEPT_OUTPUT],
                "stderr": step.stderr[-KEPT_OUTPUT:],
                "outcome": outcome if case else None,  # custom input: nothing to compare
                "passed": outcome == CaseOutcome.PASSED if case else None,
                "time_ms": step.time_ms,
                "timed_out": step.timed_out,
            }
        )
    run.results = shown
    run.status = "COMPLETED"
    return "run"
