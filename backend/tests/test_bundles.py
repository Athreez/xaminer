"""Test bundle packing (TCK-0704): same test cases, same bytes; anything different, new hash."""

import io
import json
import tarfile

from app.questions.bundles import key_for, pack
from app.questions.models import TestCase


def cases(*rows: tuple[str, str, int, str]) -> list[TestCase]:
    return [
        TestCase(input=i, expected_output=o, weight=w, visibility=v, order_index=n)
        for n, (i, o, w, v) in enumerate(rows)
    ]


def test_same_cases_same_bytes_and_hash() -> None:
    first = pack(cases(("1 2", "3", 1, "PUBLIC"), ("5 7", "12", 3, "HIDDEN")))
    again = pack(cases(("1 2", "3", 1, "PUBLIC"), ("5 7", "12", 3, "HIDDEN")))
    assert first == again
    assert len(first[1]) == 64


def test_any_change_changes_the_hash() -> None:
    base = pack(cases(("1 2", "3", 1, "PUBLIC"), ("5 7", "12", 3, "HIDDEN")))[1]
    variants = [
        cases(("1 2", "3", 1, "PUBLIC"), ("5 7", "13", 3, "HIDDEN")),  # output
        cases(("1 2", "3", 1, "PUBLIC"), ("5 7", "12", 4, "HIDDEN")),  # weight
        cases(("1 2", "3", 1, "HIDDEN"), ("5 7", "12", 3, "HIDDEN")),  # visibility
        cases(("5 7", "12", 3, "HIDDEN"), ("1 2", "3", 1, "PUBLIC")),  # order
    ]
    assert len({base, *(pack(v)[1] for v in variants)}) == 5


def test_tar_layout() -> None:
    data, digest = pack(cases(("1 2\n", "3\n", 1, "PUBLIC"), ("é", "", 2, "HIDDEN")))
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        assert tar.getnames() == ["001.in", "001.out", "002.in", "002.out", "manifest.json"]
        assert tar.extractfile("002.in").read() == "é".encode()  # type: ignore[union-attr]
        manifest = json.load(tar.extractfile("manifest.json"))  # type: ignore[arg-type]
        assert {m.mtime for m in tar.getmembers()} == {0}
    assert manifest == {
        "format": 1,
        "cases": [
            {"name": "001", "weight": 1, "hidden": False},
            {"name": "002", "weight": 2, "hidden": True},
        ],
    }
    assert key_for("inst", digest) == f"inst/{digest}.tar"  # type: ignore[arg-type]
