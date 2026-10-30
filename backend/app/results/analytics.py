"""Exam analytics for the teacher (PRD MON-03..05; TCK-1203).

Over the attempts that are fully graded (they have a result), never previews:

- The exam: how many, average, median, highest, lowest, pass rate (with a pass mark) and a
  histogram of percentages in tens.
- Each question: average score, how many got full marks, and for choice questions how often each
  option was picked.
- Each coding question: the verdict of every student's counted submission ("no submission" when
  there's none) and, per test case, how many of those submissions passed it. A hidden case most
  students fail is often a broken test (MON-05). Only positions and public/hidden are shown, never
  a hidden case's content.
"""

import statistics
import uuid
from collections import Counter
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attempts.models import Answer, ExamAttempt
from app.auth.tokens import Principal
from app.authz.ownership import get_owned
from app.exams.models import Exam, ExamVersion
from app.execution.models import CodingEvaluation, CodingSubmission, TestCaseResult
from app.questions.test_cases import positions, public_examples
from app.results.models import Result
from domain_core.objective_score import CENT

LOW_PASS_RATE = 0.3  # under this, a test case is flagged as possibly broken


class OptionPicks(BaseModel):
    label: str
    is_correct: bool
    picked: int


class TestCaseStat(BaseModel):
    number: int
    hidden: bool
    weight: int
    passed: int
    total: int
    pass_rate: float
    possibly_broken: bool = Field(description=f"Passed by under {LOW_PASS_RATE:.0%} of students")


class QuestionStat(BaseModel):
    exam_question_id: uuid.UUID
    position: int
    type: str
    title: str
    points: Decimal
    average: Decimal
    full_marks: int = Field(description="Attempts that got all the points")
    options: list[OptionPicks] = []
    verdicts: dict[str, int] = Field(
        default={}, description="Coding: counted submissions' verdicts"
    )
    test_cases: list[TestCaseStat] = []


class ExamAnalytics(BaseModel):
    graded: int = Field(description="Fully graded attempts the numbers are about")
    max_score: Decimal | None
    average: Decimal | None
    median: Decimal | None
    highest: Decimal | None
    lowest: Decimal | None
    pass_rate: float | None = Field(description="Share that passed, with a pass mark")
    histogram: list[int] = Field(description="Attempts per 10 % band: 0-9, 10-19, ..., 90-100")
    questions: list[QuestionStat]


def _two(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def _title(body: str) -> str:
    line = next((x.strip("# ").strip() for x in body.splitlines() if x.strip()), "")
    return line[:80]


async def analytics(
    session: AsyncSession, principal: Principal, exam_id: uuid.UUID
) -> ExamAnalytics:
    exam = await get_owned(
        session, Exam, exam_id, principal, owned=lambda e: e.owner_id == principal.user_id
    )
    version = (
        await session.get(ExamVersion, exam.published_version_id)
        if exam.published_version_id
        else None
    )
    rows = (
        await session.execute(
            select(
                ExamAttempt.id,
                Result.total_score,
                Result.max_score,
                Result.percentage,
                Result.passed,
            )
            .join(Result, Result.attempt_id == ExamAttempt.id)
            .where(ExamAttempt.exam_id == exam.id, ExamAttempt.is_preview.is_(False))
        )
    ).all()
    ids = [r[0] for r in rows]
    scores = [r[1] for r in rows]
    histogram = [0] * 10
    for r in rows:
        histogram[min(9, int(r[3] // 10))] += 1
    with_pass = [r[4] for r in rows if r[4] is not None]

    questions: list[QuestionStat] = []
    if version is not None and ids:
        answers: dict[uuid.UUID, list[Answer]] = {}
        for a in await session.scalars(select(Answer).where(Answer.attempt_id.in_(ids))):
            answers.setdefault(a.exam_question_id, []).append(a)
        coding = await _coding(session, ids)
        for position, q in enumerate(version.snapshot["questions"], start=1):
            eq_id = uuid.UUID(q["exam_question_id"])
            points = Decimal(str(q["points"]))
            given = answers.get(eq_id, [])
            total = sum((a.score or Decimal(0) for a in given), Decimal(0))
            stat = QuestionStat(
                exam_question_id=eq_id,
                position=position,
                type=q["type"],
                title=_title(q["body"]),
                points=points,
                average=_two(total / len(ids)),
                full_marks=sum(1 for a in given if a.score is not None and a.score >= points),
            )
            if q["type"] in ("MCQ", "MSQ", "TRUE_FALSE"):
                picks = Counter(str(o) for a in given for o in (a.selected_option_ids or []))
                stat.options = [
                    OptionPicks(
                        label=o["label"], is_correct=o["is_correct"], picked=picks[str(o["id"])]
                    )
                    for o in q["options"]
                ]
            if q["type"] == "CODING":
                verdicts, cases, versions = coding.get(eq_id, (Counter(), [], set()))
                verdicts["NO_SUBMISSION"] = len(ids) - sum(verdicts.values())
                stat.verdicts = {k: v for k, v in verdicts.items() if v}
                versions.add(uuid.UUID(q["version_id"]))
                stat.test_cases = await _case_stats(session, cases, versions)
            questions.append(stat)

    return ExamAnalytics(
        graded=len(rows),
        max_score=rows[0][2] if rows else None,
        average=_two(sum(scores, Decimal(0)) / len(scores)) if scores else None,
        median=_two(Decimal(statistics.median(scores))) if scores else None,
        highest=max(scores) if scores else None,
        lowest=min(scores) if scores else None,
        pass_rate=round(sum(with_pass) / len(with_pass), 4) if with_pass else None,
        histogram=histogram,
        questions=questions,
    )


async def _coding(
    session: AsyncSession, attempt_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[Counter[str], list[TestCaseResult], set[uuid.UUID]]]:
    """Per coding question: verdicts of the counted submissions, their test case results, and the
    versions a re-evaluation graded them with (none: the exam's own)."""
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
            select(CodingSubmission.exam_question_id, CodingEvaluation)
            .join(latest, latest.c.submission_id == CodingSubmission.id)
            .join(
                CodingEvaluation,
                (CodingEvaluation.submission_id == latest.c.submission_id)
                & (CodingEvaluation.evaluation_no == latest.c.evaluation_no),
            )
            .where(CodingSubmission.attempt_id.in_(attempt_ids), CodingSubmission.is_counted)
        )
    ).all()
    out: dict[uuid.UUID, tuple[Counter[str], list[TestCaseResult], set[uuid.UUID]]] = {}
    evaluation_question = {}
    for eq_id, evaluation in rows:
        verdicts, _, versions = out.setdefault(eq_id, (Counter(), [], set()))
        verdicts[evaluation.verdict or "PENDING"] += 1
        if evaluation.version_id:
            versions.add(evaluation.version_id)
        evaluation_question[evaluation.id] = eq_id
    if evaluation_question:
        for r in await session.scalars(
            select(TestCaseResult).where(
                TestCaseResult.evaluation_id.in_(list(evaluation_question))
            )
        ):
            out[evaluation_question[r.evaluation_id]][1].append(r)
    return out


async def _case_stats(
    session: AsyncSession, results: list[TestCaseResult], versions: set[uuid.UUID]
) -> list[TestCaseStat]:
    if not results:
        return []
    place = await positions(session, list({r.test_case_id for r in results}))
    public = {c.id for v in versions for c in await public_examples(session, v)}
    by_case: dict[uuid.UUID, list[TestCaseResult]] = {}
    for r in results:
        by_case.setdefault(r.test_case_id, []).append(r)
    stats = []
    for case_id, rs in by_case.items():
        passed = sum(r.outcome == "PASSED" for r in rs)
        rate = passed / len(rs)
        stats.append(
            TestCaseStat(
                number=place.get(case_id, 0),
                hidden=case_id not in public,
                weight=rs[0].weight,
                passed=passed,
                total=len(rs),
                pass_rate=round(rate, 4),
                possibly_broken=rate < LOW_PASS_RATE,
            )
        )
    return sorted(stats, key=lambda s: s.number)
