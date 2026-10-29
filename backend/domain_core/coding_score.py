"""Score and verdict of a coding submission (PRD § 6.2, GRD-02).

For a question worth `P` points, total test case weight `W` and passed weight `w`:

1. Compile error → 0.
2. Partial scoring off → `P` if every test case passes, else 0.
3. Partial scoring on → `P * w / W`, rounded to 2 decimals (half up).
4. A test case that fails for any reason adds nothing. No negative marks.
5. A platform failure is not scored here at all: the caller records INTERNAL_ERROR, never 0.

The verdict is for display: ACCEPTED, PARTIAL (some passed, partial scoring on), or the main reason
it failed, which is the outcome of the first failing test case (as judges usually report it).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum


class CaseOutcome(StrEnum):
    PASSED = "PASSED"
    WRONG_ANSWER = "WRONG_ANSWER"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    TIME_LIMIT_EXCEEDED = "TIME_LIMIT_EXCEEDED"
    MEMORY_LIMIT_EXCEEDED = "MEMORY_LIMIT_EXCEEDED"
    OUTPUT_LIMIT_EXCEEDED = "OUTPUT_LIMIT_EXCEEDED"


class Verdict(StrEnum):
    ACCEPTED = "ACCEPTED"
    PARTIAL = "PARTIAL"
    WRONG_ANSWER = "WRONG_ANSWER"
    COMPILE_ERROR = "COMPILE_ERROR"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    TIME_LIMIT_EXCEEDED = "TIME_LIMIT_EXCEEDED"
    MEMORY_LIMIT_EXCEEDED = "MEMORY_LIMIT_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"  # the platform failed: no score (set by the caller)


# A failing case's outcome as a verdict. Too much output isn't a verdict of its own in the PRD:
# it shows as a wrong answer (it's usually a print loop).
_VERDICT = {
    CaseOutcome.WRONG_ANSWER: Verdict.WRONG_ANSWER,
    CaseOutcome.OUTPUT_LIMIT_EXCEEDED: Verdict.WRONG_ANSWER,
    CaseOutcome.RUNTIME_ERROR: Verdict.RUNTIME_ERROR,
    CaseOutcome.TIME_LIMIT_EXCEEDED: Verdict.TIME_LIMIT_EXCEEDED,
    CaseOutcome.MEMORY_LIMIT_EXCEEDED: Verdict.MEMORY_LIMIT_EXCEEDED,
}

CENT = Decimal("0.01")


def case_outcome(
    *,
    timed_out: bool,
    memory_exceeded: bool,
    output_exceeded: bool,
    exit_code: int | None,
    output_matches: bool,
) -> CaseOutcome:
    """One test case's outcome. Limits first: a program killed for time may also look like it
    crashed, and its partial output means nothing."""
    if timed_out:
        return CaseOutcome.TIME_LIMIT_EXCEEDED
    if memory_exceeded:
        return CaseOutcome.MEMORY_LIMIT_EXCEEDED
    if output_exceeded:
        return CaseOutcome.OUTPUT_LIMIT_EXCEEDED
    if exit_code != 0:
        return CaseOutcome.RUNTIME_ERROR
    return CaseOutcome.PASSED if output_matches else CaseOutcome.WRONG_ANSWER


@dataclass(frozen=True)
class CodingScore:
    score: Decimal
    passed_weight: int
    total_weight: int
    verdict: Verdict


def score(
    points: Decimal,
    *,
    compiled: bool,
    partial_scoring: bool,
    cases: list[tuple[int, CaseOutcome]],
) -> CodingScore:
    """`cases`: (weight, outcome) of every graded test case, in order."""
    if not cases:
        raise ValueError("a coding question is scored on at least one test case")
    total = sum(weight for weight, _ in cases)
    if not compiled:
        return CodingScore(Decimal("0.00"), 0, total, Verdict.COMPILE_ERROR)

    passed = sum(weight for weight, outcome in cases if outcome == CaseOutcome.PASSED)
    first_failure = next((o for _, o in cases if o != CaseOutcome.PASSED), None)
    if first_failure is None:
        return CodingScore(points.quantize(CENT, ROUND_HALF_UP), passed, total, Verdict.ACCEPTED)
    if partial_scoring and passed:
        earned = (points * passed / total).quantize(CENT, ROUND_HALF_UP)
        return CodingScore(earned, passed, total, Verdict.PARTIAL)
    return CodingScore(Decimal("0.00"), passed, total, _VERDICT[first_failure])
