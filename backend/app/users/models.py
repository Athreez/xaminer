import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin

ROLES = ("ADMIN", "TEACHER", "STUDENT")
USER_STATUSES = ("INVITED", "ACTIVE", "DEACTIVATED")


class User(IdMixin, TenantMixin, TimestampMixin, Base):
    """A person in one institution. Never hard-deleted once they have graded work (PRD USR-01)."""

    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint("institution_id", "email"),
        CheckConstraint(f"role IN {ROLES}", name="role"),
        CheckConstraint(f"status IN {USER_STATUSES}", name="status"),
        # An active account must be able to log in; an invited one sets its password later.
        CheckConstraint(
            "status <> 'ACTIVE' OR password_hash IS NOT NULL", name="active_has_password"
        ),
        Index(
            "uq_user_institution_id_roll_no",
            "institution_id",
            "roll_no",
            unique=True,
            postgresql_where=text("roll_no IS NOT NULL"),
        ),
        Index("ix_user_institution_id_role_status", "institution_id", "role", "status"),
    )

    email: Mapped[str] = mapped_column(CITEXT)  # case-insensitive: Ana@X.edu == ana@x.edu
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="INVITED")
    roll_no: Mapped[str | None] = mapped_column(String(64))
    # Kept on the user row for simplicity; never part of any API response (users get a view type).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    failed_logins: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    deactivated_at: Mapped[datetime | None]


class UserGroup(IdMixin, TenantMixin, TimestampMixin, Base):
    """A named set of students, e.g. "CSE-A 2026", so an exam can be assigned to all of them."""

    __tablename__ = "user_group"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)

    name: Mapped[str] = mapped_column(CITEXT)  # case-insensitive, like emails


class UserGroupMember(TenantMixin, Base):
    __tablename__ = "user_group_member"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_group.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())
