"""Exam timing rules (domain_core.timer): window cut-off, extensions, grace, starting."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from domain_core.timer import (
    GRACE,
    StartBlock,
    accepts_saves,
    deadline,
    is_overdue,
    remaining,
    seconds_left,
    start_block,
)

T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
CLOSE = T0 + timedelta(hours=3)


# ----------------------------------------------------------------------------- deadline (ATT-03)


def test_deadline_is_start_plus_duration() -> None:
    assert deadline(T0, 60, CLOSE) == T0 + timedelta(minutes=60)


def test_window_close_cuts_a_late_start_short() -> None:
    late_start = CLOSE - timedelta(minutes=20)
    assert deadline(late_start, 60, CLOSE) == CLOSE


def test_extension_adds_time_but_never_past_the_window() -> None:
    assert deadline(T0, 60, CLOSE, extra_minutes=15) == T0 + timedelta(minutes=75)
    assert deadline(CLOSE - timedelta(minutes=50), 60, CLOSE, extra_minutes=30) == CLOSE


def test_moving_the_window_end_lets_an_extension_count() -> None:
    start = CLOSE - timedelta(minutes=40)
    assert deadline(start, 60, CLOSE) == CLOSE
    later_close = CLOSE + timedelta(hours=1)  # the teacher extends the window's end
    assert deadline(start, 60, later_close) == start + timedelta(minutes=60)


def test_time_zones_are_respected() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    start_ist = T0.astimezone(ist)
    assert deadline(start_ist, 30, CLOSE) == T0 + timedelta(minutes=30)


@pytest.mark.parametrize(
    "call",
    [
        lambda: deadline(datetime(2026, 11, 1, 9), 60, CLOSE),  # no time zone
        lambda: deadline(T0, 0, CLOSE),
        lambda: deadline(T0, 60, CLOSE, extra_minutes=-5),
        lambda: remaining(T0, datetime(2026, 11, 1, 9)),
    ],
    ids=["naive-time", "zero-duration", "negative-extension", "naive-now"],
)
def test_bad_input_is_refused(call) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        call()


# ----------------------------------------------------------------------------- remaining (ATT-04)


def test_remaining_counts_down_and_stops_at_zero() -> None:
    end = T0 + timedelta(minutes=60)
    assert remaining(end, T0) == timedelta(minutes=60)
    assert seconds_left(end, end - timedelta(seconds=1.9)) == 1  # rounded down
    assert remaining(end, end + timedelta(minutes=5)) == timedelta(0)
    assert seconds_left(end, end + timedelta(minutes=5)) == 0


# ----------------------------------------------------------------------------- grace (ATT-11)


def test_saves_count_until_the_grace_runs_out() -> None:
    end = T0 + timedelta(minutes=60)
    assert accepts_saves(end, end)
    assert accepts_saves(end, end + GRACE)  # exactly 60 s late: still counts
    assert not accepts_saves(end, end + GRACE + timedelta(milliseconds=1))
    assert GRACE == timedelta(seconds=60)


def test_overdue_only_after_the_grace() -> None:
    end = T0 + timedelta(minutes=60)
    assert not is_overdue(end, end + timedelta(seconds=30))  # a last save may still arrive
    assert is_overdue(end, end + timedelta(seconds=61))


# ----------------------------------------------------------------------------- starting (ATT-01)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (T0 - timedelta(seconds=1), StartBlock.NOT_OPEN),
        (T0, None),
        (CLOSE - timedelta(minutes=5), None),  # exactly 5 minutes left: allowed
        (CLOSE - timedelta(minutes=4, seconds=59), StartBlock.TOO_LATE),
        (CLOSE, StartBlock.CLOSED),
        (CLOSE + timedelta(days=1), StartBlock.CLOSED),
    ],
    ids=["before-open", "at-open", "five-min-left", "under-five-min", "at-close", "after-close"],
)
def test_when_a_student_may_start(now: datetime, expected: StartBlock | None) -> None:
    assert start_block(T0, CLOSE, now) == expected
