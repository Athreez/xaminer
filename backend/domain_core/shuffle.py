"""Per-student shuffling that gives the same order every time (PRD ATT-05).

No random numbers: each item's place comes from SHA-256 of the attempt's seed and the item's key.
The same seed and keys always give the same order, so a reload shows exactly what the student saw,
and the order can be recomputed later to check it.
"""

import hashlib
from collections.abc import Callable, Sequence


def _rank(seed: int, key: str) -> bytes:
    return hashlib.sha256(f"{seed}:{key}".encode()).digest()


def shuffled[T](seed: int, items: Sequence[T], key: Callable[[T], str]) -> list[T]:
    """`items` in this seed's order. `key` must be unique per item (e.g. its id)."""
    return sorted(items, key=lambda item: _rank(seed, key(item)))


def permutation(seed: int, salt: str, size: int) -> list[int]:
    """A shuffled order of 0..size-1 for this seed (e.g. answer options of one question)."""
    return sorted(range(size), key=lambda i: _rank(seed, f"{salt}:{i}"))
