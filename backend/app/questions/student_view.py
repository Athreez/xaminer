"""What a student sees of a question (PRD QB-08, NFR-02; SECURITY_AND_ACCESS.md § 3).

These types are separate from the teacher's view rather than a filtered copy of it, so there is no
field to forget to remove: correct answers, rubrics, owners, tags and versions don't exist here.
`build` is the only way to make one; the teacher preview and the exam screen both use it.

Coding questions add their problem setup and the public test cases as examples. Hidden test cases
are never read here: `coding_part` uses `test_cases.public_examples` only (PRD CQ-05).
"""

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import Storage
from app.images.service import sign_refs
from app.platform.models import Language
from app.questions.models import CodingConfig, Question, QuestionOption, QuestionVersion
from app.questions.schemas import MsqScoring, QuestionType
from app.questions.test_cases import public_examples


class StudentOption(BaseModel):
    id: uuid.UUID
    label: str


class StudentLanguage(BaseModel):
    key: str
    display_name: str
    starter_code: str


class StudentExample(BaseModel):
    """A public test case, shown in full (hidden ones never appear anywhere a student can see)."""

    input: str
    expected_output: str


class StudentCoding(BaseModel):
    input_format: str = Field(description="Markdown")
    output_format: str = Field(description="Markdown")
    constraints: str = Field(description="Markdown")
    languages: list[StudentLanguage] = Field(description="Allowed languages, with starter code")
    time_limit_ms: int = Field(description="Before each language's multiplier")
    memory_limit_mb: int
    run_code_allowed: bool
    max_submissions: int
    partial_scoring: bool = Field(description="Marks for each test passed, not all or nothing")
    examples: list[StudentExample]


class StudentQuestion(BaseModel):
    """A question as shown in an exam. Never includes answer keys or the rubric."""

    id: uuid.UUID = Field(description="The question version shown")
    type: QuestionType
    body: str = Field(description="Markdown; image links are signed")
    points: Decimal
    negative_marks: Decimal
    multiple_answers: bool = Field(description="True for multiple-select: tick all that apply")
    msq_scoring: MsqScoring | None = Field(description="How a multiple-select answer is marked")
    max_answer_length: int | None = Field(description="Descriptive answers: character limit")
    options: list[StudentOption] = Field(description="In the order to show them")
    coding: StudentCoding | None = Field(default=None, description="Coding questions only")


def build(
    question: Question,
    version: QuestionVersion,
    options: list[QuestionOption],
    storage: Storage,
    image_seconds: int,
    coding: dict[str, Any] | None = None,
) -> StudentQuestion:
    """`coding`: from `coding_part`, for coding questions."""

    def signed(text: str) -> str:
        return sign_refs(text, question.institution_id, storage, image_seconds)

    return StudentQuestion(
        id=version.id,
        type=question.type,  # type: ignore[arg-type]
        body=signed(version.body),
        points=version.points,
        negative_marks=version.negative_marks,
        multiple_answers=question.type == "MSQ",
        msq_scoring=version.msq_scoring,  # type: ignore[arg-type]
        max_answer_length=version.max_answer_length,
        options=[StudentOption(id=o.id, label=signed(o.label)) for o in options],
        coding=_coding(coding, signed),
    )


def from_snapshot(
    question: dict[str, Any],
    option_order: list[int] | None,
    institution_id: uuid.UUID,
    storage: Storage,
    image_seconds: int,
) -> StudentQuestion:
    """The same student view, built from a published exam's frozen copy of the question.

    `option_order` lists indexes into the stored options in the order this student sees them
    (shuffled answers); None keeps the teacher's order. Correct answers and the rubric are in the
    snapshot but never copied here.
    """

    def signed(text: str) -> str:
        return sign_refs(text, institution_id, storage, image_seconds)

    stored = question.get("options", [])
    order = option_order if option_order is not None else list(range(len(stored)))
    return StudentQuestion(
        id=uuid.UUID(question["version_id"]),
        type=question["type"],
        body=signed(question["body"]),
        points=Decimal(question["points"]),
        negative_marks=Decimal(question["negative_marks"]),
        multiple_answers=question["type"] == "MSQ",
        msq_scoring=question.get("msq_scoring"),
        max_answer_length=question.get("max_answer_length"),
        options=[
            StudentOption(id=uuid.UUID(stored[i]["id"]), label=signed(stored[i]["label"]))
            for i in order
        ],
        coding=_coding(question.get("coding"), signed),
    )


def _coding(part: dict[str, Any] | None, signed: Any) -> StudentCoding | None:
    if part is None:
        return None
    return StudentCoding(
        **part
        | {field: signed(part[field]) for field in ("input_format", "output_format", "constraints")}
    )


async def coding_part(session: AsyncSession, version_id: uuid.UUID) -> dict[str, Any]:
    """What a student may see of a coding version, as plain data: kept in published exams'
    snapshots and turned into `StudentCoding` by `build` and `from_snapshot`. Public examples
    only; the hidden test cases stay in their table, for grading."""
    config = await session.get(CodingConfig, version_id)
    if config is None:
        config = CodingConfig(version_id=version_id)  # not set up yet: the defaults
    choices = config.allowed_languages or []
    names = dict(
        (
            await session.execute(
                select(Language.key, Language.display_name).where(
                    Language.key.in_([c["language_key"] for c in choices])
                )
            )
        ).all()
    )
    return {
        "input_format": config.input_format or "",
        "output_format": config.output_format or "",
        "constraints": config.constraints or "",
        "languages": [
            {
                "key": c["language_key"],
                "display_name": names.get(c["language_key"], c["language_key"]),
                "starter_code": c.get("starter_code", ""),
            }
            for c in choices
        ],
        "time_limit_ms": config.time_limit_ms or 2000,
        "memory_limit_mb": config.memory_limit_mb or 256,
        "run_code_allowed": config.run_code_allowed is not False,
        "max_submissions": config.max_submissions or 10,
        "partial_scoring": config.partial_scoring is not False,
        "examples": [
            {"input": c.input, "expected_output": c.expected_output}
            for c in await public_examples(session, version_id)
        ],
    }
