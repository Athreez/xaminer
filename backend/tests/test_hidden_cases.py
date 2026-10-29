"""Hidden test cases have one door (PRD CQ-05, TCK-0703).

Only the modules listed here may touch the `TestCase` table or read every test case. Anything
that builds what a student receives must use `test_cases.public_examples`. A new reader (the test
bundle builder, validation) is added to these lists on purpose, in review.
"""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SOURCES = [*BACKEND.glob("app/**/*.py"), *BACKEND.glob("workers/**/*.py")]

# May use the TestCase model (define it, read it through the door, or write it for the teacher).
TABLE = {"app/questions/models.py", "app/questions/test_cases.py", "app/questions/coding.py"}
# May read hidden test cases.
READERS = {"app/questions/test_cases.py", "app/questions/coding.py"}
# Build what students receive: must never get near hidden cases.
STUDENT_FACING = {
    "app/questions/student_view.py",
    *(str(p.relative_to(BACKEND)).replace("\\", "/") for p in BACKEND.glob("app/attempts/*.py")),
}


def _name(path: Path) -> str:
    return str(path.relative_to(BACKEND)).replace("\\", "/")


def test_only_listed_modules_touch_the_test_case_table() -> None:
    touching = {_name(p) for p in SOURCES if re.search(r"\bTestCase\b", p.read_text("utf-8"))}
    assert touching <= TABLE, (
        f"read test cases through app/questions/test_cases.py: {touching - TABLE}"
    )


def test_only_listed_modules_read_hidden_test_cases() -> None:
    readers = {_name(p) for p in SOURCES if "all_test_cases" in p.read_text("utf-8")}
    assert readers <= READERS, f"hidden test cases are read by {readers - READERS}"


def test_student_facing_code_stays_away_from_hidden_cases() -> None:
    assert not STUDENT_FACING & (TABLE | READERS)
    for name in STUDENT_FACING:
        text = (BACKEND / name).read_text("utf-8")
        assert "all_test_cases" not in text and not re.search(r"\bTestCase\b", text), name
