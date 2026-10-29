"""Does a program's output match the expected output? (PRD § 6.2, CQ-06)

Each mode is applied to both outputs the same way:

- `EXACT`: equal character for character.
- `TRIM` (the default): line endings made the same (CRLF and CR become LF), spaces and tabs at
  the end of each line removed, blank lines at the end removed.
- `TOKEN`: the same words and numbers in the same order; how they are spaced or split into lines
  doesn't matter.
- `NUMERIC`: like `TOKEN`, but two numbers match if they differ by at most 1e-6, absolutely or
  relative to the larger one. Anything that isn't a plain decimal number must match exactly.
"""

import math
import re
from typing import Literal

Mode = Literal["EXACT", "TRIM", "TOKEN", "NUMERIC"]

TOLERANCE = 1e-6
# Plain decimals only ("3", "-0.5", "1e-9", ".5"): not "nan", "inf", "0x1f" or "1_000", which
# float() would also accept but no test expects to be read as numbers.
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


def trimmed(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.rstrip(" \t") for line in lines]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _number(token: str) -> float | None:
    if not _NUMBER.fullmatch(token):
        return None
    value = float(token)
    return value if math.isfinite(value) else None


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE or abs(a - b) <= TOLERANCE * max(abs(a), abs(b))


def _tokens_match(expected: str, actual: str, numeric: bool) -> bool:
    want, got = expected.split(), actual.split()
    if len(want) != len(got):
        return False
    for w, g in zip(want, got, strict=True):
        if w == g:
            continue
        if not numeric:
            return False
        a, b = _number(w), _number(g)
        if a is None or b is None or not _close(a, b):
            return False
    return True


def matches(mode: Mode, expected: str, actual: str) -> bool:
    """True if `actual` counts as the expected output under `mode`."""
    if mode == "EXACT":
        return expected == actual
    if mode == "TRIM":
        return trimmed(expected) == trimmed(actual)
    if mode == "TOKEN":
        return _tokens_match(expected, actual, numeric=False)
    if mode == "NUMERIC":
        return _tokens_match(expected, actual, numeric=True)
    raise ValueError(f"unknown comparison mode: {mode}")
