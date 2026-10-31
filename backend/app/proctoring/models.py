"""Proctoring events (PRD PRC-06, PRC-10; TCK-1101, browser-check events first).

One row per thing the exam screen noticed: leaving fullscreen, switching away, pasting from
outside the exam, more than one screen; and with the camera: no face, a second face, looking
away, talking, screen sharing stopped. `SIGNAL_LOST` is made by the server (heartbeats arrive,
proctoring has stopped). Severity is set by the server's rules, never by the
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

KINDS = (
    "FULLSCREEN_EXIT",
    "TAB_SWITCH",
    "PASTE_BLOCKED",
    "MULTIPLE_SCREENS",
    "FACE_ABSENT",
    "MULTIPLE_FACES",
    "GAZE_AWAY",
    "VOICE_DETECTED",
    "SCREEN_SHARE_STOPPED",
    "SIGNAL_LOST",
    "PHONE_DETECTED",
    "BOOK_DETECTED",
)
# PROCESSING: waiting for the server's check of its pictures (never shown); REJECTED: the check
# found nothing (never shown); READY: for the teacher.
STATUSES = ("PROCESSING", "READY", "REJECTED")
SEVERITIES = ("LOW", "MEDIUM", "HIGH")
DECISIONS = ("DISMISSED", "FLAGGED")


class ProctoringEvent(IdMixin, TenantMixin, Base):
    __tablename__ = "proctoring_event"
    __table_args__ = (
        UniqueConstraint("attempt_id", "client_id"),  # an upload repeated changes nothing
        CheckConstraint(f"kind IN {KINDS}", name="kind"),
        CheckConstraint(f"severity IN {SEVERITIES}", name="severity"),
        CheckConstraint(f"status IN {STATUSES}", name="status"),
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
    status: Mapped[str] = mapped_column(String(12), server_default="READY")
    # The server's check (0..1): how sure it is; null when not checked (no pictures).
    confidence: Mapped[float | None]
    check_sent_at: Mapped[datetime | None]
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


CAPTURE_KINDS = ("CAMERA", "SCREEN")
CAPTURE_PURPOSES = ("EVENT", "SPOT_CHECK", "PERIODIC", "LEFT_PAGE")


class ProctoringCapture(IdMixin, TenantMixin, Base):
    """A picture from the exam screen (PRD PRC-05, PRC-17; TCK-1006, TCK-1102): up to 3 of the
    camera per event, random camera spot checks, and pictures of the shared screen (every
    20-40 s and when the student leaves the page). Stored re-encoded in the `evidence` bucket;
    `deleted_at` is set once the image is gone (spot checks soon, the rest after retention)."""

    __tablename__ = "proctoring_capture"
    __table_args__ = (
        UniqueConstraint("attempt_id", "client_id"),  # an upload repeated changes nothing
        CheckConstraint(f"kind IN {CAPTURE_KINDS}", name="kind"),
        CheckConstraint(f"purpose IN {CAPTURE_PURPOSES}", name="purpose"),
        CheckConstraint("(purpose = 'EVENT') = (event_client_id IS NOT NULL)", name="event_has_id"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_attempt.id", ondelete="CASCADE"), index=True
    )
    client_id: Mapped[uuid.UUID]
    kind: Mapped[str] = mapped_column(String(8))
    purpose: Mapped[str] = mapped_column(String(12))
    # The event's `client_id` (the event itself may arrive before or after its pictures).
    event_client_id: Mapped[uuid.UUID | None]
    taken_at: Mapped[datetime]
    storage_key: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer)
    check_sent_at: Mapped[datetime | None]  # spot checks: sent to the inference-worker
    checked_at: Mapped[datetime | None]  # spot checks: its answer applied
    deleted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
