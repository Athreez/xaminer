import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
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
