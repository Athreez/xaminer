"""Coding score and verdict (PRD § 6.2, TCK-0805), with the PRD's worked example."""

from decimal import Decimal

import pytest

from domain_core.coding_score import CaseOutcome, Verdict, case_outcome, score

P, W = CaseOutcome.PASSED, CaseOutcome.WRONG_ANSWER
TLE, MLE = CaseOutcome.TIME_LIMIT_EXCEEDED, CaseOutcome.MEMORY_LIMIT_EXCEEDED
RTE, OLE = CaseOutcome.RUNTIME_ERROR, CaseOutcome.OUTPUT_LIMIT_EXCEEDED


def test_prd_worked_example() -> None:
    # P = 10, weights 1,1,2,2,2,2,3,3 (W = 16); all pass but the two weight-3 cases -> 6.25 PARTIAL
    weights = [1, 1, 2, 2, 2, 2, 3, 3]
    outcomes = [P, P, P, P, P, P, W, TLE]
    result = score(
        Decimal("10"),
        compiled=True,
        partial_scoring=True,
        cases=list(zip(weights, outcomes, strict=True)),
    )
    assert (result.score, result.passed_weight, result.total_weight, result.verdict) == (
        Decimal("6.25"),
        10,
        16,
        Verdict.PARTIAL,
    )


def test_everything_passes() -> None:
    result = score(Decimal("8"), compiled=True, partial_scoring=False, cases=[(1, P), (3, P)])
    assert (result.score, result.verdict) == (Decimal("8.00"), Verdict.ACCEPTED)


def test_compile_error_scores_zero() -> None:
    result = score(Decimal("10"), compiled=False, partial_scoring=True, cases=[(1, W), (2, W)])
    assert (result.score, result.passed_weight, result.total_weight, result.verdict) == (
        Decimal("0.00"),
        0,
        3,
        Verdict.COMPILE_ERROR,
    )


def test_partial_off_is_all_or_nothing() -> None:
    result = score(
        Decimal("10"), compiled=True, partial_scoring=False, cases=[(1, P), (1, P), (5, MLE)]
    )
    assert (result.score, result.passed_weight, result.verdict) == (
        Decimal("0.00"),
        2,
        Verdict.MEMORY_LIMIT_EXCEEDED,
    )


def test_nothing_passed_shows_the_first_failure() -> None:
    result = score(Decimal("10"), compiled=True, partial_scoring=True, cases=[(1, RTE), (1, TLE)])
    assert (result.score, result.verdict) == (Decimal("0.00"), Verdict.RUNTIME_ERROR)


def test_too_much_output_shows_as_wrong_answer() -> None:
    result = score(Decimal("5"), compiled=True, partial_scoring=True, cases=[(1, OLE)])
    assert result.verdict == Verdict.WRONG_ANSWER


@pytest.mark.parametrize(
    ("points", "passed", "total", "expected"),
    [
        ("10", 1, 3, "3.33"),
        ("10", 2, 3, "6.67"),
        ("1", 1, 8, "0.13"),  # 0.125 rounds half up
        ("2.5", 1, 2, "1.25"),
        ("7", 1, 7, "1.00"),
    ],
)
def test_rounding_half_up(points: str, passed: int, total: int, expected: str) -> None:
    cases = [(passed, P), (total - passed, W)]
    result = score(Decimal(points), compiled=True, partial_scoring=True, cases=cases)
    assert result.score == Decimal(expected)


def test_never_negative_and_needs_cases() -> None:
    result = score(Decimal("10"), compiled=True, partial_scoring=True, cases=[(9, W)])
    assert result.score == Decimal("0.00") >= 0
    with pytest.raises(ValueError):
        score(Decimal("10"), compiled=True, partial_scoring=True, cases=[])


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({"timed_out": True, "memory_exceeded": True, "exit_code": None}, TLE),
        ({"memory_exceeded": True, "exit_code": 137}, MLE),
        ({"output_exceeded": True, "exit_code": 0}, OLE),
        ({"exit_code": 1, "output_matches": True}, RTE),  # right output but it crashed
        ({"exit_code": None}, RTE),
        ({"exit_code": 0, "output_matches": False}, W),
        ({"exit_code": 0, "output_matches": True}, P),
    ],
)
def test_case_outcome_priority(flags: dict[str, object], expected: CaseOutcome) -> None:
    values: dict[str, object] = {
        "timed_out": False,
        "memory_exceeded": False,
        "output_exceeded": False,
        "exit_code": 0,
        "output_matches": False,
    } | flags
    assert case_outcome(**values) == expected  # type: ignore[arg-type]
