from decimal import Decimal

from sqlalchemy import ARRAY, CheckConstraint, Numeric, SmallInteger, String, Text
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


class Language(IdMixin, TimestampMixin, Base):
    """A programming language students can use. Global: not per institution (PRD CQ-02).

    `image` is the runner image built in TCK-0801; it is pinned to a digest there.
    """

    __tablename__ = "language"
    __table_args__ = (
        CheckConstraint("time_multiplier BETWEEN 1 AND 10", name="time_multiplier_range"),
    )

    key: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(64))
    image: Mapped[str] = mapped_column(String(255))
    source_filename: Mapped[str] = mapped_column(String(64))
    compile_cmd: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    run_cmd: Mapped[list[str]] = mapped_column(ARRAY(Text))
    # Slower languages get more time: effective limit = question limit x multiplier.
    time_multiplier: Mapped[Decimal] = mapped_column(Numeric(3, 1), server_default="1.0")
    enabled: Mapped[bool] = mapped_column(server_default="true")
