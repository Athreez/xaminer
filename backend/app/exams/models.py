import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin

EXAM_STATUSES = ("DRAFT", "PUBLISHED", "ARCHIVED")
NAVIGATION_MODES = ("FREE", "SEQUENTIAL")
RELEASE_POLICIES = ("MANUAL", "ON_SUBMIT")
COUNTED_SUBMISSIONS = ("BEST", "LAST")
PROCTORING_MODES = ("OFF", "VIDEO", "VIDEO_AUDIO")
DEFAULT_DETECTORS = '{"sensitivity": "STANDARD", "gaze": false, "books": false}'


class Exam(IdMixin, TenantMixin, TimestampMixin, Base):
    """An exam and all its settings (PRD § 6.3). Drafts may leave the window and duration empty;
    publishing requires them (publish check, TCK-0505)."""

    __tablename__ = "exam"
    __table_args__ = (
        CheckConstraint(f"status IN {EXAM_STATUSES}", name="status"),
        CheckConstraint(f"navigation_mode IN {NAVIGATION_MODES}", name="navigation_mode"),
        CheckConstraint(f"release_policy IN {RELEASE_POLICIES}", name="release_policy"),
        CheckConstraint(f"counted_submission IN {COUNTED_SUBMISSIONS}", name="counted_submission"),
        CheckConstraint(f"proctoring_mode IN {PROCTORING_MODES}", name="proctoring_mode"),
        CheckConstraint("close_at > open_at", name="window_order"),
        CheckConstraint("duration_min BETWEEN 1 AND 600", name="duration_range"),
        CheckConstraint("pass_percent BETWEEN 0 AND 100", name="pass_percent_range"),
        Index("ix_exam_institution_id_owner_id_status", "institution_id", "owner_id", "status"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str] = mapped_column(Text, server_default="")  # Markdown
    status: Mapped[str] = mapped_column(String(16), server_default="DRAFT")
    open_at: Mapped[datetime | None]
    close_at: Mapped[datetime | None]
    duration_min: Mapped[int | None] = mapped_column(SmallInteger)
    navigation_mode: Mapped[str] = mapped_column(String(16), server_default="FREE")
    shuffle_questions: Mapped[bool] = mapped_column(server_default=text("false"))
    shuffle_options: Mapped[bool] = mapped_column(server_default=text("false"))
    run_code_enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    # Fullscreen, leaving the page, pasting from outside, extra screens (recorded for review).
    browser_checks: Mapped[bool] = mapped_column(server_default=text("true"))
    release_policy: Mapped[str] = mapped_column(String(16), server_default="MANUAL")
    counted_submission: Mapped[str] = mapped_column(String(8), server_default="BEST")
    pass_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    proctoring_mode: Mapped[str] = mapped_column(String(16), server_default="OFF")
    # {"sensitivity": RELAXED|STANDARD|STRICT, "gaze": bool, "books": bool}; checked by the API.
    proctoring_detectors: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text(f"'{DEFAULT_DETECTORS}'::jsonb")
    )
    consent_text: Mapped[str | None] = mapped_column(Text)  # None: the institution's default
    # Circular with exam_version, so the foreign key is added after both tables exist.
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exam_version.id", ondelete="RESTRICT", use_alter=True)
    )


class ExamQuestion(IdMixin, TenantMixin, TimestampMixin, Base):
    """A question in an exam, in order. The version is pinned when the exam is published."""

    __tablename__ = "exam_question"
    __table_args__ = (
        UniqueConstraint("exam_id", "question_id"),
        # Checked at commit, so a reorder can swap two positions inside one transaction.
        UniqueConstraint("exam_id", "order_index", deferrable=True, initially="DEFERRED"),
        CheckConstraint("order_index >= 0", name="order_index_not_negative"),
        CheckConstraint("points IS NULL OR points > 0", name="points_positive"),
        CheckConstraint(
            "negative_marks IS NULL OR negative_marks >= 0", name="negative_marks_not_negative"
        ),
    )

    exam_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question.id", ondelete="RESTRICT"), index=True
    )
    pinned_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("question_version.id", ondelete="RESTRICT")
    )
    order_index: Mapped[int] = mapped_column(SmallInteger)
    # None: use the question version's own points / negative marks.
    points: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    negative_marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))


class ExamVersion(IdMixin, TenantMixin, Base):
    """The exam frozen at publish: settings, questions and pinned versions. A database trigger
    refuses any change or deletion, so a grade can always be traced to what students saw."""

    __tablename__ = "exam_version"
    __table_args__ = (UniqueConstraint("exam_id", "version_no"),)

    exam_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam.id", ondelete="CASCADE"), index=True
    )
    version_no: Mapped[int] = mapped_column(SmallInteger)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 of the snapshot
    published_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ExamAssignment(IdMixin, TenantMixin, Base):
    """A student allowed to take an exam. No assignment, no attempt (PRD EX-04)."""

    __tablename__ = "exam_assignment"
    __table_args__ = (UniqueConstraint("exam_id", "student_id"),)

    exam_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="RESTRICT"), index=True
    )
    assigned_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="RESTRICT"))
    # Set when added through a group; kept as a record even if the group is deleted later.
    via_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_group.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
