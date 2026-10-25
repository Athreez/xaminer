from sqlalchemy import CheckConstraint, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin

INSTITUTION_STATUSES = ("ACTIVE", "SUSPENDED")


class Institution(IdMixin, TimestampMixin, Base):
    """The tenant. Created with the platform-admin CLI, not through the API."""

    __tablename__ = "institution"
    __table_args__ = (
        CheckConstraint(f"status IN {INSTITUTION_STATUSES}", name="status"),
        CheckConstraint("evidence_retention_days BETWEEN 7 AND 90", name="retention_range"),
    )

    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), server_default="UTC")
    status: Mapped[str] = mapped_column(String(16), server_default="ACTIVE")
    evidence_retention_days: Mapped[int] = mapped_column(SmallInteger, server_default="30")
    default_consent_text: Mapped[str | None] = mapped_column(Text)
