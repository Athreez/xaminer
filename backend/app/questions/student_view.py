"""What a student sees of a question (PRD QB-08, NFR-02; SECURITY_AND_ACCESS.md § 3).

These types are separate from the teacher's view rather than a filtered copy of it, so there is no
field to forget to remove: correct answers, rubrics, owners, tags and versions don't exist here.
`build` is the only way to make one; the teacher preview and the exam screen both use it.
"""

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.core.storage import Storage
from app.images.service import sign_refs
from app.questions.models import Question, QuestionOption, QuestionVersion
from app.questions.schemas import MsqScoring, QuestionType


class StudentOption(BaseModel):
    id: uuid.UUID
    label: str


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


def build(
    question: Question,
    version: QuestionVersion,
    options: list[QuestionOption],
    storage: Storage,
    image_seconds: int,
) -> StudentQuestion:
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
    )
