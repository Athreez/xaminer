"""In-app notifications (PRD NOT-02): one row per user and event, read or not."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin

KINDS = ("EXAM_ASSIGNED", "RESULT_RELEASED", "RESULT_CHANGED")


class Notification(IdMixin, TenantMixin, Base):
    __tablename__ = "notification"
    __table_args__ = (
        CheckConstraint(f"kind IN {KINDS}", name="kind"),
        Index("ix_notification_user_id_created_at", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, server_default="")
    link: Mapped[str] = mapped_column(String(300), server_default="")  # a path in the app
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    read_at: Mapped[datetime | None]
