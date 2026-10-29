"""Output comparison test vectors (PRD § 6.2, TCK-0804): line endings, trailing newlines, empty
output, spacing and floats, for every mode."""

import pytest

from domain_core.compare import Mode, matches, trimmed

# (expected, actual) -> outcome in EXACT, TRIM, TOKEN, NUMERIC
VECTORS: list[tuple[str, str, str, tuple[bool, bool, bool, bool]]] = [
    ("identical", "3\n", "3\n", (True, True, True, True)),
    ("missing final newline", "3\n", "3", (False, True, True, True)),
    ("extra blank lines at the end", "3\n", "3\n\n\n", (False, True, True, True)),
    ("Windows line endings", "1\n2\n", "1\r\n2\r\n", (False, True, True, True)),
    ("old Mac line endings", "1\n2", "1\r2", (False, True, True, True)),
    ("trailing spaces and tabs", "a b\nc\n", "a b  \nc\t\n", (False, True, True, True)),
    ("leading spaces matter to TRIM", "x\n", "  x\n", (False, False, True, True)),
    ("spacing inside a line", "1 2 3\n", "1  2   3\n", (False, False, True, True)),
    ("split over lines", "1 2 3\n", "1\n2\n3\n", (False, False, True, True)),
    ("blank line in the middle", "a\n\nb\n", "a\nb\n", (False, False, True, True)),
    ("both empty", "", "", (True, True, True, True)),
    ("empty vs only whitespace", "", "\n \n\t\n", (False, True, True, True)),
    ("empty vs something", "", "0\n", (False, False, False, False)),
    ("nothing printed", "42\n", "", (False, False, False, False)),
    ("wrong answer", "42\n", "41\n", (False, False, False, False)),
    ("extra token", "1 2\n", "1 2 3\n", (False, False, False, False)),
    ("case matters", "YES\n", "yes\n", (False, False, False, False)),
    ("float within 1e-6", "0.333333\n", "0.3333333333\n", (False, False, False, True)),
    ("float off by more", "0.3333\n", "0.3334\n", (False, False, False, False)),
    ("integer written as float", "2\n", "2.0\n", (False, False, False, True)),
    ("scientific notation", "0.000001\n", "1e-6\n", (False, False, False, True)),
    ("large numbers, relative", "1000000000\n", "1000000000.5\n", (False, False, False, True)),
    ("large numbers, too far", "1000000\n", "1000002\n", (False, False, False, False)),
    ("1e-6 relative: 1 in a million", "1000000\n", "1000001\n", (False, False, False, True)),
    ("signs", "-0.5 +3\n", "-.5 3\n", (False, False, False, True)),
    (
        "words still exact in NUMERIC",
        "Case #1: 1.5\n",
        "case #1: 1.5\n",
        (False, False, False, False),
    ),
    (
        "words with numbers nearby",
        "Case #1: 1.5\n",
        "Case #1: 1.5000001\n",
        (False, False, False, True),
    ),
    ("nan is not a number here", "nan\n", "NaN\n", (False, False, False, False)),
    ("inf is not a number here", "inf\n", "1e400\n", (False, False, False, False)),
    ("hex is not a number here", "0x10\n", "16\n", (False, False, False, False)),
    ("unicode", "héllo wörld\n", "héllo wörld\r\n", (False, True, True, True)),
]
MODES: tuple[Mode, ...] = ("EXACT", "TRIM", "TOKEN", "NUMERIC")


@pytest.mark.parametrize(
    ("name", "expected", "actual", "outcomes"), VECTORS, ids=[v[0] for v in VECTORS]
)
def test_vectors(name: str, expected: str, actual: str, outcomes: tuple[bool, ...]) -> None:
    got = tuple(matches(mode, expected, actual) for mode in MODES)
    assert got == outcomes, dict(zip(MODES, got, strict=True))


@pytest.mark.parametrize("mode", MODES)
def test_symmetric(mode: Mode) -> None:
    for _, expected, actual, _outcomes in VECTORS:
        assert matches(mode, expected, actual) == matches(mode, actual, expected)


def test_trimmed() -> None:
    assert trimmed("a  \r\nb\t\r\n\r\n\n") == "a\nb"
    assert trimmed("\n\n") == ""


def test_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unknown comparison mode"):
        matches("FUZZY", "a", "a")  # type: ignore[arg-type]
