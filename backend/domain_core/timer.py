"""Exam timing (PRD ATT-01, ATT-03, ATT-04, ATT-11; § 6.3 "fixed for everyone").

Pure functions over the server's clock: the caller passes `now`, nothing here reads it. All times
must carry a time zone, so a naive local time can never shift a deadline silently.
"""

from datetime import datetime, timedelta
from enum import StrEnum

GRACE = timedelta(seconds=60)
"""Saves arriving up to this long after the deadline still count (slow networks)."""

MIN_TIME_TO_START = timedelta(minutes=5)
"""A student can't start once less than this is left of the window (ATT-01)."""


class StartBlock(StrEnum):
    """Why a student can't start yet (or any more), from the clock's point of view."""

    NOT_OPEN = "NOT_OPEN"
    CLOSED = "CLOSED"
    TOO_LATE = "TOO_LATE"  # open, but less than MIN_TIME_TO_START left


def _aware(*values: datetime) -> None:
    for value in values:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"time zone missing: {value!r}")


def deadline(
    started_at: datetime, duration_min: int, close_at: datetime, extra_minutes: int = 0
) -> datetime:
    """When the attempt ends: start + duration + extra, but never after the window closes (ATT-03).

    Recomputed with the same rule when a teacher grants extra minutes or moves the window's end.
    """
    _aware(started_at, close_at)
    if duration_min < 1:
        raise ValueError("duration must be at least 1 minute")
    if extra_minutes < 0:
        raise ValueError("extra minutes can't be negative")
    own = started_at + timedelta(minutes=duration_min + extra_minutes)
    return min(own, close_at)


def remaining(deadline_at: datetime, now: datetime) -> timedelta:
    """Time left, never negative. The exam screen counts down from this and the server's clock."""
    _aware(deadline_at, now)
    return max(deadline_at - now, timedelta(0))


def seconds_left(deadline_at: datetime, now: datetime) -> int:
    """Whole seconds left, rounded down (the screen shows 0:00 only when time is really up)."""
    return int(remaining(deadline_at, now).total_seconds())


def accepts_saves(deadline_at: datetime, now: datetime) -> bool:
    """Whether an answer arriving now still counts: up to the deadline plus the grace (ATT-11)."""
    _aware(deadline_at, now)
    return now <= deadline_at + GRACE


def is_overdue(deadline_at: datetime, now: datetime) -> bool:
    """Whether the attempt should be submitted automatically: the grace has run out too.

    Waiting for the grace means saves sent in the last seconds still land before submitting.
    """
    return not accepts_saves(deadline_at, now)


def start_block(open_at: datetime, close_at: datetime, now: datetime) -> StartBlock | None:
    """None if the clock allows starting now; otherwise the reason it doesn't (ATT-01)."""
    _aware(open_at, close_at, now)
    if now < open_at:
        return StartBlock.NOT_OPEN
    if now >= close_at:
        return StartBlock.CLOSED
    if close_at - now < MIN_TIME_TO_START:
        return StartBlock.TOO_LATE
    return None
