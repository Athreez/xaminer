"""Per-student shuffling (domain_core.shuffle): same seed, same order; different seeds differ."""

from domain_core.shuffle import permutation, shuffled

IDS = [f"q{i}" for i in range(20)]


def test_same_seed_same_order() -> None:
    first = shuffled(42, IDS, key=str)
    assert shuffled(42, IDS, key=str) == first  # a reload sees the same order
    assert sorted(first) == sorted(IDS)  # nothing lost or repeated
    assert shuffled(42, list(reversed(IDS)), key=str) == first  # input order doesn't matter


def test_different_seeds_usually_differ() -> None:
    orders = {tuple(shuffled(seed, IDS, key=str)) for seed in range(50)}
    assert len(orders) == 50


def test_order_actually_moves() -> None:
    assert shuffled(7, IDS, key=str) != IDS


def test_permutation() -> None:
    order = permutation(9, "question-1", 4)
    assert sorted(order) == [0, 1, 2, 3]
    assert permutation(9, "question-1", 4) == order
    assert permutation(9, "question-2", 4) != order or permutation(9, "question-3", 4) != order
    assert permutation(9, "q", 0) == []
