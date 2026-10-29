import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

QuestionType = Literal["MCQ", "MSQ", "TRUE_FALSE", "DESCRIPTIVE", "CODING"]
Visibility = Literal["PRIVATE", "INSTITUTION"]
MsqScoring = Literal["ALL_OR_NOTHING", "PARTIAL"]

Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]
Tag = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=50)
]
Points = Annotated[Decimal, Field(gt=0, le=1000, max_digits=6, decimal_places=2)]
NegativeMarks = Annotated[Decimal, Field(ge=0, le=1000, max_digits=6, decimal_places=2)]


class OptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Label
    is_correct: bool


class QuestionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: QuestionType
    visibility: Visibility = "PRIVATE"
    tags: list[Tag] = Field(default=[], max_length=20)
    body: Body = Field(description="Markdown")
    points: Points
    negative_marks: NegativeMarks = Decimal("0")
    msq_scoring: MsqScoring | None = None
    max_answer_length: int | None = Field(default=None, ge=1, le=20_000)
    rubric: Annotated[str, StringConstraints(max_length=10_000)] | None = None
    options: list[OptionIn] = Field(default=[], max_length=10, description="In display order")


class QuestionUpdate(BaseModel):
    """Only the fields sent change. `options`, when sent, replaces the whole list.

    The type can't change. If the current version is locked (used by a published exam), a content
    change creates a new version; published exams keep the old one (PRD QB-07).
    """

    model_config = ConfigDict(extra="forbid")

    visibility: Visibility | None = None
    tags: list[Tag] | None = Field(default=None, max_length=20)
    body: Body | None = None
    points: Points | None = None
    negative_marks: NegativeMarks | None = None
    msq_scoring: MsqScoring | None = None
    max_answer_length: int | None = Field(default=None, ge=1, le=20_000)
    rubric: Annotated[str, StringConstraints(max_length=10_000)] | None = None
    options: list[OptionIn] | None = Field(default=None, max_length=10)


class OptionView(BaseModel):
    id: uuid.UUID
    label: str
    is_correct: bool
    order_index: int


class VersionView(BaseModel):
    id: uuid.UUID
    version_no: int
    body: str
    points: Decimal
    negative_marks: Decimal
    msq_scoring: MsqScoring | None
    max_answer_length: int | None
    rubric: str | None
    is_locked: bool = Field(description="Used by a published exam: edits make a new version")
    created_at: datetime
    options: list[OptionView]


class Owner(BaseModel):
    id: uuid.UUID
    full_name: str


class QuestionView(BaseModel):
    """The teacher's full view, including answer keys and rubric. Never sent to students."""

    id: uuid.UUID
    type: QuestionType
    visibility: Visibility
    tags: list[str]
    owner: Owner
    is_mine: bool
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: VersionView = Field(description="The current version, text exactly as stored")
    image_urls: dict[str, str] = Field(
        description="Signed link (valid an hour) for each image reference in the text. Show the "
        "text with these swapped in; save it with the references unchanged."
    )


class QuestionSummary(BaseModel):
    id: uuid.UUID
    type: QuestionType
    visibility: Visibility
    tags: list[str]
    owner: Owner
    is_mine: bool
    title: str = Field(description="First line of the text, without Markdown, shortened")
    points: Decimal
    version_no: int
    is_locked: bool
    archived_at: datetime | None
    updated_at: datetime


class QuestionPage(BaseModel):
    data: list[QuestionSummary]
    next_cursor: str | None
