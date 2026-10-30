import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.questions.models import MAX_CASE_BYTES, MAX_SOURCE_BYTES

QuestionType = Literal["MCQ", "MSQ", "TRUE_FALSE", "DESCRIPTIVE", "CODING"]
Visibility = Literal["PRIVATE", "INSTITUTION"]
MsqScoring = Literal["ALL_OR_NOTHING", "PARTIAL"]
ComparisonMode = Literal["EXACT", "TRIM", "TOKEN", "NUMERIC"]
CaseVisibility = Literal["PUBLIC", "HIDDEN"]
ValidationStatus = Literal["NEEDS_VALIDATION", "VALIDATING", "PASSED", "FAILED"]

Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20_000)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)]
Tag = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=50)
]
Points = Annotated[Decimal, Field(gt=0, le=1000, max_digits=6, decimal_places=2)]
NegativeMarks = Annotated[Decimal, Field(ge=0, le=1000, max_digits=6, decimal_places=2)]

MAX_TEST_CASES = 50  # PRD CQ-04
MAX_STARTER_BYTES = 65_536
Text5k = Annotated[str, StringConstraints(max_length=5_000)]
CaseText = Annotated[str, StringConstraints(max_length=MAX_CASE_BYTES)]


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


# ----------------------------------------------------------------------------- coding


class LanguageChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language_key: str = Field(max_length=32)
    starter_code: str = Field(default="", max_length=MAX_STARTER_BYTES)


class CodingIn(BaseModel):
    """The whole coding setup; PUT replaces it. Limits per PRD CQ-03, CQ-06, CQ-07."""

    model_config = ConfigDict(extra="forbid")

    input_format: Text5k = Field(default="", description="Markdown")
    output_format: Text5k = Field(default="", description="Markdown")
    constraints: Text5k = Field(default="", description="Markdown")
    allowed_languages: list[LanguageChoice] = Field(
        max_length=4,
        description="In the order students see them. May be empty while drafting; validation "
        "needs at least one",
    )
    time_limit_ms: int = Field(default=2000, ge=100, le=10_000)
    memory_limit_mb: int = Field(default=256, ge=16, le=512)
    comparison_mode: ComparisonMode = "TRIM"
    partial_scoring: bool = True
    run_code_allowed: bool = True
    max_submissions: int = Field(default=10, ge=1, le=100)


class TestCaseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: CaseVisibility = "HIDDEN"
    weight: int = Field(default=1, ge=1, le=1000)
    input: CaseText = ""
    expected_output: CaseText


class TestCasePatch(BaseModel):
    """Only the fields sent change."""

    model_config = ConfigDict(extra="forbid")

    visibility: CaseVisibility | None = None
    weight: int | None = Field(default=None, ge=1, le=1000)
    input: CaseText | None = None
    expected_output: CaseText | None = None


class TestCaseOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] = Field(max_length=MAX_TEST_CASES, description="Every test case, in order")


class ReferenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=MAX_SOURCE_BYTES)


class TestCaseView(BaseModel):
    """Teacher-only: includes hidden test cases in full."""

    id: uuid.UUID
    visibility: CaseVisibility
    weight: int
    input: str
    expected_output: str
    order_index: int


class ReferenceView(BaseModel):
    language_key: str
    source: str


class CodingView(BaseModel):
    """The coding setup of the current version, for the teacher's editor."""

    input_format: str
    output_format: str
    constraints: str
    allowed_languages: list[LanguageChoice]
    time_limit_ms: int
    memory_limit_mb: int
    comparison_mode: ComparisonMode
    partial_scoring: bool
    run_code_allowed: bool
    max_submissions: int
    validation_status: ValidationStatus
    validation_report: dict[str, Any] | None
    test_case_count: int
    hidden_test_case_count: int
    reference_solutions: list[ReferenceView]
    blocks: list[str] = Field(
        description="What has to be fixed before the question can be validated"
    )


class LanguageView(BaseModel):
    key: str
    display_name: str
    time_multiplier: float = Field(description="Time limit multiplier for this language")


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
    coding: CodingView | None = Field(
        description="Coding questions only: setup, references, what blocks validation. Test cases "
        "are listed by GET /questions/{id}/test-cases"
    )
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
