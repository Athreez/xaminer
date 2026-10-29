import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin

ATTEMPT_STATUSES = ("IN_PROGRESS", "SUBMITTED", "AUTO_SUBMITTED", "VOIDED")
GRADING_STATUSES = ("PENDING", "AWAITING_CODING", "AWAITING_MANUAL", "COMPLETE")
MAX_TEXT_ANSWER = 65_536  # characters (SECURITY_AND_ACCESS.md: answer text 64 KB)


class ExamAttempt(IdMixin, TenantMixin, TimestampMixin, Base):
    """One student's sitting of one exam (PRD ATT-01..11). Tied to the published version, so it is
    graded against exactly what the student saw. Never deleted; a teacher voids instead."""

    __tablename__ = "exam_attempt"
    __table_args__ = (
        CheckConstraint(f"status IN {ATTEMPT_STATUSES}", name="status"),
        CheckConstraint(f"grading_status IN {GRADING_STATUSES}", name="grading_status"),
        CheckConstraint("deadline_at > started_at", name="deadline_after_start"),
        CheckConstraint("extra_minutes BETWEEN 0 AND 600", name="extra_minutes_range"),
        CheckConstraint(
            "status NOT IN ('SUBMITTED', 'AUTO_SUBMITTED') OR submitted_at IS NOT NULL",
            name="submitted_has_time",
        ),
        CheckConstraint(
            "(exam_version_id IS NULL) <> (preview_snapshot IS NULL)"
            " AND (preview_snapshot IS NULL OR is_preview)",
            name="one_exam_copy",
        ),
        # ATT-02: one attempt per student per exam, unless voided. Two simultaneous "Start"
        # requests: the second insert fails here and the API returns the first attempt.
        Index(
            "uq_exam_attempt_one_active",
            "exam_id",
            "student_id",
            unique=True,
            postgresql_where=text("status <> 'VOIDED'"),
        ),
        Index("ix_exam_attempt_exam_id_status", "exam_id", "status"),
        # The sweeper looks for unfinished attempts past their deadline (ATT-11).
        Index(
            "ix_exam_attempt_open_deadline",
            "deadline_at",
            postgresql_where=text("status = 'IN_PROGRESS'"),
        ),
    )

    exam_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exam.id", ondelete="RESTRICT"))
    # A student's attempt uses the published version. A teacher's preview of a draft has no
    # published version, so it carries its own frozen copy instead (exactly one of the two).
    exam_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exam_version.id", ondelete="RESTRICT")
    )
    # none_as_null: Python None must be SQL NULL, not the JSON value null (the check counts it).
    preview_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), server_default="IN_PROGRESS")
    grading_status: Mapped[str] = mapped_column(String(16), server_default="PENDING")
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # Fixed at start (ATT-03): min(start + duration + extra, window close). Server time only.
    deadline_at: Mapped[datetime]
    submitted_at: Mapped[datetime | None]
    shuffle_seed: Mapped[int] = mapped_column(BigInteger)  # same order on every reload (ATT-05)
    last_heartbeat_at: Mapped[datetime | None]
    extra_minutes: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    is_preview: Mapped[bool] = mapped_column(server_default=text("false"))  # teacher's own test


class AttemptQuestion(IdMixin, TenantMixin, Base):
    """The order this student saw the questions and options in (ATT-05), and review marks."""

    __tablename__ = "attempt_question"
    __table_args__ = (
        UniqueConstraint("attempt_id", "position"),
        UniqueConstraint("attempt_id", "exam_question_id"),
        CheckConstraint("position >= 1", name="position_positive"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_attempt.id", ondelete="CASCADE"), index=True
    )
    exam_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_question.id", ondelete="RESTRICT")
    )
    position: Mapped[int] = mapped_column(SmallInteger)  # 1 = shown first
    # Indexes into the version's options in the order shown; None when not shuffled or no options.
    option_order: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    marked_for_review: Mapped[bool] = mapped_column(server_default=text("false"))


class Answer(TenantMixin, TimestampMixin, Base):
    """The student's answer to one question, and its marks once graded (PRD ATT-08, GRD-*).

    Saves are guarded by `client_revision`: an older revision arriving late never overwrites a
    newer one (offline queue, two tabs).
    """

    __tablename__ = "answer"
    __table_args__ = (
        CheckConstraint(
            f"text_answer IS NULL OR char_length(text_answer) <= {MAX_TEXT_ANSWER}",
            name="text_answer_length",
        ),
        CheckConstraint("client_revision >= 0", name="client_revision_not_negative"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_attempt.id", ondelete="CASCADE"), primary_key=True
    )
    exam_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_question.id", ondelete="RESTRICT"), primary_key=True
    )
    selected_option_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(Uuid))
    text_answer: Mapped[str | None] = mapped_column(Text)
    client_revision: Mapped[int] = mapped_column(Integer, server_default="0")
    auto_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # MCQ/MSQ/TF/coding
    manual_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # set by a grader
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # what counts
    feedback: Mapped[str | None] = mapped_column(Text)
    graded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="RESTRICT"))
    graded_at: Mapped[datetime | None]


class CodeDraft(TenantMixin, TimestampMixin, Base):
    """Unsubmitted editor content for a coding question, per language (PRD § 6.6)."""

    __tablename__ = "code_draft"
    __table_args__ = (
        CheckConstraint("char_length(source) <= 262144", name="source_length"),  # 256 KB
        CheckConstraint("client_revision >= 0", name="client_revision_not_negative"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_attempt.id", ondelete="CASCADE"), primary_key=True
    )
    exam_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_question.id", ondelete="RESTRICT"), primary_key=True
    )
    language_key: Mapped[str] = mapped_column(
        String(32), ForeignKey("language.key", ondelete="RESTRICT"), primary_key=True
    )
    source: Mapped[str] = mapped_column(Text)
    client_revision: Mapped[int] = mapped_column(Integer, server_default="0")
