import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin, TimestampMixin

TOKEN_PURPOSES = ("INVITE", "RESET")


class RefreshToken(IdMixin, TenantMixin, TimestampMixin, Base):
    """One refresh token. Rotated on every use; reusing an old one revokes its family (AUTH-03).

    Only a SHA-256 hash of the token is stored, so a database leak doesn't hand out sessions.
    """

    __tablename__ = "refresh_token"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(64))


class AuthToken(IdMixin, TenantMixin, TimestampMixin, Base):
    """Single-use token for an invitation (7 days) or a password reset (1 hour). Stored hashed."""

    __tablename__ = "auth_token"
    __table_args__ = (CheckConstraint(f"purpose IN {TOKEN_PURPOSES}", name="purpose"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
