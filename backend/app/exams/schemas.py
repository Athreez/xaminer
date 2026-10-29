import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

ExamStatus = Literal["DRAFT", "PUBLISHED", "ARCHIVED"]
NavigationMode = Literal["FREE", "SEQUENTIAL"]
ReleasePolicy = Literal["MANUAL", "ON_SUBMIT"]
CountedSubmission = Literal["BEST", "LAST"]
ProctoringMode = Literal["OFF", "VIDEO", "VIDEO_AUDIO"]
Sensitivity = Literal["RELAXED", "STANDARD", "STRICT"]

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(max_length=20_000)]
Duration = Annotated[int, Field(ge=1, le=600, description="Minutes")]
PassPercent = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]


class Detectors(BaseModel):
    """Proctoring detector settings (PRD § 6.5). Other detectors are always on when proctored."""

    model_config = ConfigDict(extra="forbid")

    sensitivity: Sensitivity = "STANDARD"
    gaze: bool = Field(default=False, description="Gaze detection")
    books: bool = Field(default=False, description="Book detection (closed-book exams)")


class ExamSettings(BaseModel):
    """Every setting with its PRD § 6.3 default. Window and duration may stay empty in a draft."""

    model_config = ConfigDict(extra="forbid")

    instructions: LongText = Field(default="", description="Markdown, shown before starting")
    open_at: AwareDatetime | None = None
    close_at: AwareDatetime | None = None
    duration_min: Duration | None = None
    navigation_mode: NavigationMode = "FREE"
    shuffle_questions: bool = False
    shuffle_options: bool = False
    run_code_enabled: bool = True
    release_policy: ReleasePolicy = "MANUAL"
    counted_submission: CountedSubmission = "BEST"
    pass_percent: PassPercent | None = None
    proctoring_mode: ProctoringMode = "OFF"
    proctoring_detectors: Detectors = Detectors()
    consent_text: LongText | None = Field(
        default=None, description="Null: use the institution's default consent text"
    )


class ExamCreate(ExamSettings):
    title: Title


class ExamUpdate(BaseModel):
    """Only the fields sent change. After publishing only `close_at` may change (PRD EX-06)."""

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    instructions: LongText | None = None
    open_at: AwareDatetime | None = None
    close_at: AwareDatetime | None = None
    duration_min: Duration | None = None
    navigation_mode: NavigationMode | None = None
    shuffle_questions: bool | None = None
    shuffle_options: bool | None = None
    run_code_enabled: bool | None = None
    release_policy: ReleasePolicy | None = None
    counted_submission: CountedSubmission | None = None
    pass_percent: PassPercent | None = None
    proctoring_mode: ProctoringMode | None = None
    proctoring_detectors: Detectors | None = None
    consent_text: LongText | None = None


class ExamView(BaseModel):
    id: uuid.UUID
    title: str
    status: ExamStatus
    instructions: str
    open_at: datetime | None
    close_at: datetime | None
    duration_min: int | None
    navigation_mode: NavigationMode
    shuffle_questions: bool
    shuffle_options: bool
    run_code_enabled: bool
    release_policy: ReleasePolicy
    counted_submission: CountedSubmission
    pass_percent: Decimal | None
    proctoring_mode: ProctoringMode
    proctoring_detectors: Detectors
    consent_text: str | None
    question_count: int
    total_points: Decimal
    assigned_count: int
    published_version_no: int | None
    created_at: datetime
    updated_at: datetime


class ExamSummary(BaseModel):
    id: uuid.UUID
    title: str
    status: ExamStatus
    open_at: datetime | None
    close_at: datetime | None
    duration_min: int | None
    question_count: int
    assigned_count: int
    proctoring_mode: ProctoringMode
    has_coding: bool
    updated_at: datetime


class ExamPage(BaseModel):
    data: list[ExamSummary]
    next_cursor: str | None


class AdminExamSummary(BaseModel):
    """What an admin may see of an exam: metadata only, never its questions (SECURITY § 3)."""

    id: uuid.UUID
    title: str
    owner_name: str
    status: ExamStatus
    open_at: datetime | None
    close_at: datetime | None
    duration_min: int | None
    assigned_count: int


class AdminExamPage(BaseModel):
    data: list[AdminExamSummary]
    next_cursor: str | None
