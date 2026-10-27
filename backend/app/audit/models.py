import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TenantMixin


class AuditLog(IdMixin, TenantMixin, Base):
    """One recorded action. Append-only: the `app` DB user can't update or delete rows.

    No foreign keys: the log must outlive whatever it describes, and must never block (or be
    removed by) the deletion of a user or institution. Still filtered by institution like any
    tenant table.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_institution_id_created_at", "institution_id", "created_at"),
        Index("ix_audit_log_institution_id_actor_id", "institution_id", "actor_id"),
        Index("ix_audit_log_institution_id_target", "institution_id", "target_type", "target_id"),
    )

    # Overrides TenantMixin's column to drop its foreign key (see above).
    institution_id: Mapped[uuid.UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    actor_id: Mapped[uuid.UUID | None]  # None: the system, or someone not logged in
    actor_role: Mapped[str | None] = mapped_column(String(16))  # role, or PLATFORM for the CLI
    action: Mapped[str] = mapped_column(String(64))  # e.g. "auth.login_failed"
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[uuid.UUID | None]
    # Changed fields only, as {"field": {"old": ..., "new": ...}}. Never passwords or tokens.
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    request_id: Mapped[str | None] = mapped_column(String(64))
