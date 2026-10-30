"""Proctoring events (PRD PRC-06, PRC-10; TCK-1101, browser-check events first).

One row per thing the exam screen noticed: leaving fullscreen, switching away, pasting from
outside the exam, more than one screen. Severity is set by the server's rules, never by the
browser (PRC-07). A teacher's decision (dismissed or flagged) always records who and when.
Students never see these rows (PRC-09).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin

KINDS = ("FULLSCREEN_EXIT", "TAB_SWITCH", "PASTE_BLOCKED", "MULTIPLE_SCREENS")
SEVERITIES = ("LOW", "MEDIUM", "HIGH")
DECISIONS = ("DISMISSED", "FLAGGED")


class ProctoringEvent(IdMixin, TenantMixin, Base):
    __tablename__ = "proctoring_event"
    __table_args__ = (
        UniqueConstraint("attempt_id", "client_id"),  # an upload repeated changes nothing
        CheckConstraint(f"kind IN {KINDS}", name="kind"),
        CheckConstraint(f"severity IN {SEVERITIES}", name="severity"),
        CheckConstraint(f"decision IS NULL OR decision IN {DECISIONS}", name="decision"),
        CheckConstraint(
            "(decision IS NULL) = (decided_by IS NULL AND decided_at IS NULL)",
            name="decision_has_reviewer",
        ),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_attempt.id", ondelete="CASCADE"), index=True
    )
    client_id: Mapped[uuid.UUID]  # made by the exam screen, for safe retries
    kind: Mapped[str] = mapped_column(String(24))
    occurred_at: Mapped[datetime]  # server time when it arrived, or the device's if earlier
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    severity: Mapped[str] = mapped_column(String(8))
    decision: Mapped[str | None] = mapped_column(String(12))
    note: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


CONSENT_DECISIONS = ("ACCEPTED", "DECLINED")


class ConsentRecord(IdMixin, TenantMixin, Base):
    """A student's answer to a proctored exam's consent text (PRD PRC-03; TCK-1001). A new row
    per decision, never changed. The hash says which wording was answered."""

    __tablename__ = "consent_record"
    __table_args__ = (
        CheckConstraint(f"decision IN {CONSENT_DECISIONS}", name="decision"),
        Index("ix_consent_record_exam_id_student_id", "exam_id", "student_id"),
    )

    exam_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exam.id", ondelete="CASCADE"))
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    consent_text_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 of the text, hex
    decision: Mapped[str] = mapped_column(String(8))
    decided_at: Mapped[datetime] = mapped_column(server_default=func.now())
