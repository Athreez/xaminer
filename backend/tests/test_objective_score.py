"""Objective scoring (PRD § 6.1, TCK-0901): one table of cases per rule."""

from decimal import Decimal

import pytest

from domain_core.objective_score import question_score, total

D = Decimal
A, B, C, E = "a", "b", "c", "e"

# (kind, msq_scoring, selected, correct, points, negative, expected)
CASES = [
    # MCQ and True/False
    ("MCQ", None, [A], [A], "2", "0", "2.00"),
    ("MCQ", None, [B], [A], "2", "0.5", "-0.50"),
    ("MCQ", None, [], [A], "2", "0.5", "0.00"),  # not answered: never negative
    ("MCQ", None, [A, B], [A], "2", "0.5", "-0.50"),  # two picked can't be right
    ("TRUE_FALSE", None, [A], [A], "1", "1", "1.00"),
    ("TRUE_FALSE", None, [B], [A], "1", "1", "-1.00"),
    # MSQ all or nothing
    ("MSQ", "ALL_OR_NOTHING", [A, B], [A, B], "4", "1", "4.00"),
    ("MSQ", "ALL_OR_NOTHING", [A], [A, B], "4", "1", "-1.00"),  # missed one: not exact
    ("MSQ", "ALL_OR_NOTHING", [A, B, C], [A, B], "4", "1", "-1.00"),
    ("MSQ", "ALL_OR_NOTHING", [], [A, B], "4", "1", "0.00"),
    # MSQ partial
    ("MSQ", "PARTIAL", [A, B, C], [A, B, C], "3", "1", "3.00"),
    ("MSQ", "PARTIAL", [A, B], [A, B, C], "3", "1", "2.00"),
    ("MSQ", "PARTIAL", [A], [A, B, C], "1", "0", "0.33"),  # 1/3 rounds down
    ("MSQ", "PARTIAL", [A, B], [A, B, C], "1", "0", "0.67"),  # 2/3 rounds up
    ("MSQ", "PARTIAL", [A, E], [A, B, C], "3", "1", "-1.00"),  # any wrong pick: negative
    ("MSQ", "PARTIAL", [E], [A, B, C], "3", "0", "0.00"),  # wrong, but no negative marks set
    ("MSQ", "PARTIAL", [A], [A, B, C, E, "f", "g", "h", "i"], "1", "0", "0.13"),  # 0.125 half up
]


@pytest.mark.parametrize(
    ("kind", "scoring", "selected", "correct", "points", "negative", "expected"), CASES
)
def test_question_scores(
    kind: str,
    scoring: str | None,
    selected: list[str],
    correct: list[str],
    points: str,
    negative: str,
    expected: str,
) -> None:
    got = question_score(
        kind,  # type: ignore[arg-type]
        selected=selected,
        correct=correct,
        points=D(points),
        negative_marks=D(negative),
        msq_scoring=scoring or "ALL_OR_NOTHING",  # type: ignore[arg-type]
    )
    assert got == D(expected)


def test_total_adds_rounded_scores_and_never_goes_below_zero() -> None:
    assert total([D("2"), D("-0.5"), D("0.33"), D("0.67")], D("10")) == total([D("2.50")], D("10"))
    result = total([D("2"), D("-0.5"), D("0.33"), D("0.67")], D("10"))
    assert (result.score, result.max_score, result.percentage) == (
        D("2.50"),
        D("10.00"),
        D("25.00"),
    )
    negative = total([D("-1"), D("-2"), D("1")], D("6"))
    assert (negative.score, negative.percentage) == (D("0.00"), D("0.00"))  # clamped at 0
    assert total([D("1")], D("3")).percentage == D("33.33")
    assert total([D("2")], D("3")).percentage == D("66.67")
    assert total([], D("0")).percentage == D("0.00")  # nothing to score
