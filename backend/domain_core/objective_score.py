"""Scoring objective answers (PRD § 6.1, GRD-01).

- MCQ and True/False: the correct option earns the points; a wrong one loses the negative marks.
- MSQ, all or nothing: exactly the correct set earns the points; anything else loses the negative
  marks.
- MSQ, partial: points * (correct options picked / all correct options), as long as no wrong option
  is picked; any wrong option loses the negative marks.
- Not answered: 0, never negative.

Order: score each question, round to 2 decimals (half up), add up, the total can't go below 0,
then the percentage. A single question may be negative (that's what negative marks are); only the
total is clamped.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

Kind = Literal["MCQ", "TRUE_FALSE", "MSQ"]
MsqScoring = Literal["ALL_OR_NOTHING", "PARTIAL"]

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def _round(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


def question_score(
    kind: Kind,
    *,
    selected: Iterable[str],
    correct: Iterable[str],
    points: Decimal,
    negative_marks: Decimal = ZERO,
    msq_scoring: MsqScoring = "ALL_OR_NOTHING",
) -> Decimal:
    """One objective question's score, rounded to 2 decimals. `selected`/`correct`: option ids."""
    picked, right = set(selected), set(correct)
    if not picked:
        return ZERO  # not answered
    if kind in ("MCQ", "TRUE_FALSE"):
        # One option can be chosen; more than one is treated as wrong, never as right.
        return _round(points if picked == right and len(picked) == 1 else -negative_marks)
    if picked - right:
        return _round(-negative_marks)  # any wrong option picked
    if msq_scoring == "PARTIAL":
        return _round(points * len(picked) / len(right)) if right else ZERO
    return _round(points if picked == right else -negative_marks)


@dataclass(frozen=True)
class Total:
    score: Decimal  # never below 0
    max_score: Decimal
    percentage: Decimal  # 0 to 100, 2 decimals


def total(scores: Iterable[Decimal], max_score: Decimal) -> Total:
    """Add rounded question scores, clamp the total at 0, and turn it into a percentage."""
    summed = max(ZERO, sum((_round(s) for s in scores), ZERO))
    percentage = _round(summed * 100 / max_score) if max_score > 0 else ZERO
    return Total(summed, _round(max_score), percentage)
