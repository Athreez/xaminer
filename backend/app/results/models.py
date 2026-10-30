"""Results (TECHNICAL_ARCHITECTURE.md § 5; PRD GRD-05..08).

`result` is computed once an attempt's grading is complete, and computed again whenever a score
changes. Score and integrity outcome are separate columns, never combined. `released_at` is the
only thing that lets a student see it.

`result_revision` is written only when a released result's score changes: old, new, why and who.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin


class Result(TenantMixin, Base):
    __tablename__ = "result"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_attempt.id", ondelete="CASCADE"), primary_key=True
    )
    total_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    max_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    passed: Mapped[bool | None]  # null when the exam has no pass mark
    # [{exam_question_id, position, type, points, score}] in the teacher's order
    per_question: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    integrity_outcome: Mapped[str | None] = mapped_column(String(24))
    computed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    released_at: Mapped[datetime | None]


class ResultRevision(IdMixin, TenantMixin, Base):
    __tablename__ = "result_revision"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("result.attempt_id", ondelete="CASCADE"), index=True
    )
    old_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    new_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    reason: Mapped[str] = mapped_column(Text)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
