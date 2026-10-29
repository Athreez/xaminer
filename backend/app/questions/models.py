import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin

QUESTION_TYPES = ("MCQ", "MSQ", "TRUE_FALSE", "DESCRIPTIVE", "CODING")
VISIBILITIES = ("PRIVATE", "INSTITUTION")
MSQ_SCORING = ("ALL_OR_NOTHING", "PARTIAL")


class Question(IdMixin, TenantMixin, TimestampMixin, Base):
    """Stable identity of a question. Its content lives in versions (PRD QB-07)."""

    __tablename__ = "question"
    __table_args__ = (
        CheckConstraint(f"type IN {QUESTION_TYPES}", name="type"),
        CheckConstraint(f"visibility IN {VISIBILITIES}", name="visibility"),
        Index("ix_question_tags", "tags", postgresql_using="gin"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="RESTRICT"), index=True
    )
    type: Mapped[str] = mapped_column(String(16))  # fixed for the life of the question
    visibility: Mapped[str] = mapped_column(String(16), server_default="PRIVATE")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), server_default="{}")
    # The version teachers see and edit. Circular with question_version, so added after both.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("question_version.id", ondelete="RESTRICT", use_alter=True)
    )
    archived_at: Mapped[datetime | None]


class QuestionVersion(IdMixin, TenantMixin, Base):
    """One edition of a question's content. Locked once a published exam uses it; a database
    trigger then refuses any change to the row or its options (PRD QB-07, architecture D-11)."""

    __tablename__ = "question_version"
    __table_args__ = (
        UniqueConstraint("question_id", "version_no"),
        CheckConstraint("version_no >= 1", name="version_no_positive"),
        CheckConstraint("points > 0", name="points_positive"),
        CheckConstraint("negative_marks >= 0", name="negative_marks_not_negative"),
        CheckConstraint(f"msq_scoring IS NULL OR msq_scoring IN {MSQ_SCORING}", name="msq_scoring"),
        CheckConstraint(
            "max_answer_length IS NULL OR max_answer_length BETWEEN 1 AND 20000",
            name="max_answer_length_range",
        ),
        # Full-text search of the question bank (PRD QB-01). "simple": no stemming, any language.
        Index(
            "ix_question_version_body_fts",
            text("to_tsvector('simple', body)"),
            postgresql_using="gin",
        ),
    )

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question.id", ondelete="CASCADE"), index=True
    )
    version_no: Mapped[int] = mapped_column(SmallInteger)
    body: Mapped[str] = mapped_column(Text)  # Markdown, sanitised when rendered
    points: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    negative_marks: Mapped[Decimal] = mapped_column(Numeric(6, 2), server_default="0")
    msq_scoring: Mapped[str | None] = mapped_column(String(16))  # MSQ only
    max_answer_length: Mapped[int | None] = mapped_column(Integer)  # DESCRIPTIVE only
    rubric: Mapped[str | None] = mapped_column(Text)  # DESCRIPTIVE only; graders only
    is_locked: Mapped[bool] = mapped_column(server_default=text("false"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class QuestionOption(IdMixin, TenantMixin, Base):
    """A choice of an MCQ, MSQ or True/False version. Frozen with its version."""

    __tablename__ = "question_option"
    __table_args__ = (UniqueConstraint("version_id", "order_index"),)

    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_version.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool]
    order_index: Mapped[int] = mapped_column(SmallInteger)


# ----------------------------------------------------------------------------- coding questions

COMPARISON_MODES = ("EXACT", "TRIM", "TOKEN", "NUMERIC")
VALIDATION_STATUSES = ("NEEDS_VALIDATION", "VALIDATING", "PASSED", "FAILED")
TEST_VISIBILITIES = ("PUBLIC", "HIDDEN")
MAX_CASE_BYTES = 1_048_576  # input and expected output, each (PRD CQ-04)
MAX_SOURCE_BYTES = 262_144


class CodingConfig(TenantMixin, Base):
    """The coding part of a CODING question version (PRD CQ-01..09). 1:1 with the version.

    The problem statement is the version's `body`; examples are its public test cases.
    """

    __tablename__ = "coding_config"
    __table_args__ = (
        CheckConstraint("time_limit_ms BETWEEN 100 AND 10000", name="time_limit_range"),
        CheckConstraint("memory_limit_mb BETWEEN 16 AND 512", name="memory_limit_range"),
        CheckConstraint("max_submissions BETWEEN 1 AND 100", name="max_submissions_range"),
        CheckConstraint(f"comparison_mode IN {COMPARISON_MODES}", name="comparison_mode"),
        CheckConstraint(f"validation_status IN {VALIDATION_STATUSES}", name="validation_status"),
        CheckConstraint("jsonb_typeof(allowed_languages) = 'array'", name="allowed_languages_list"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_version.id", ondelete="CASCADE"), primary_key=True
    )
    input_format: Mapped[str] = mapped_column(Text, server_default="")
    output_format: Mapped[str] = mapped_column(Text, server_default="")
    constraints: Mapped[str] = mapped_column(Text, server_default="")
    # [{"language_key": "python312", "starter_code": "..."}, ...] in the order students see them
    allowed_languages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    time_limit_ms: Mapped[int] = mapped_column(Integer, server_default="2000")
    memory_limit_mb: Mapped[int] = mapped_column(SmallInteger, server_default="256")
    comparison_mode: Mapped[str] = mapped_column(String(16), server_default="TRIM")
    partial_scoring: Mapped[bool] = mapped_column(server_default=text("true"))
    run_code_allowed: Mapped[bool] = mapped_column(server_default=text("true"))
    max_submissions: Mapped[int] = mapped_column(SmallInteger, server_default="10")
    bundle_key: Mapped[str | None] = mapped_column(String(255))  # test bundle in storage (0704)
    validation_status: Mapped[str] = mapped_column(String(16), server_default="NEEDS_VALIDATION")
    validation_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))


class TestCase(IdMixin, TenantMixin, Base):
    """One test of a coding question version. Hidden ones are never shown to students (CQ-05):
    only one function reads them (TCK-0703)."""

    __tablename__ = "test_case"
    __table_args__ = (
        # Deferred, so a reorder can swap positions inside one transaction.
        UniqueConstraint("version_id", "order_index", deferrable=True, initially="DEFERRED"),
        CheckConstraint(f"visibility IN {TEST_VISIBILITIES}", name="visibility"),
        CheckConstraint("weight BETWEEN 1 AND 1000", name="weight_range"),
        CheckConstraint(f"octet_length(input) <= {MAX_CASE_BYTES}", name="input_size"),
        CheckConstraint(
            f"octet_length(expected_output) <= {MAX_CASE_BYTES}", name="expected_output_size"
        ),
    )
    __test__ = False  # not a pytest test class, despite the name

    # Indexed by the unique (version_id, order_index).
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_version.id", ondelete="CASCADE")
    )
    visibility: Mapped[str] = mapped_column(String(8), server_default="HIDDEN")
    weight: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    input: Mapped[str] = mapped_column(Text)
    expected_output: Mapped[str] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(SmallInteger)


class ReferenceSolution(IdMixin, TenantMixin, Base):
    """The teacher's answer in one language, run against every test case to validate them (CQ-08).
    Never shown to students."""

    __tablename__ = "reference_solution"
    __table_args__ = (
        UniqueConstraint("version_id", "language_key"),
        CheckConstraint(f"octet_length(source) <= {MAX_SOURCE_BYTES}", name="source_size"),
    )

    # Indexed by the unique (version_id, language_key).
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_version.id", ondelete="CASCADE")
    )
    language_key: Mapped[str] = mapped_column(
        String(32), ForeignKey("language.key", ondelete="RESTRICT")
    )
    source: Mapped[str] = mapped_column(Text)
