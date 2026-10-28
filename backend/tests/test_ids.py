import time

from app.core.ids import uuid7


def test_version_and_variant() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_time_ordered() -> None:
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert first < second


def test_unique() -> None:
    assert len({uuid7() for _ in range(10_000)}) == 10_000


def test_strictly_increasing_within_a_millisecond() -> None:
    """Lists sort "newest first" by id, so ids made back to back must never go backwards."""
    ids = [uuid7() for _ in range(10_000)]  # many land in the same millisecond
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    assert all(i.version == 7 and i.variant == "specified in RFC 4122" for i in ids)


def test_embeds_the_current_time() -> None:
    before = time.time_ns() // 1_000_000
    stamp = uuid7().int >> 80
    assert before <= stamp <= time.time_ns() // 1_000_000 + 1
