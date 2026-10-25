"""Base model and column mixins. Conventions: TECHNICAL_ARCHITECTURE.md § 7.1."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.ids import uuid7

# Predictable constraint names, so migrations can refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # SQLAlchemy reads this as a plain class attribute, so the mutable-default rule doesn't apply.
    type_annotation_map = {datetime: DateTime(timezone=True), uuid.UUID: Uuid}  # noqa: RUF012


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class TenantMixin:
    """Every domain table except `institution` and `language` has this.

    Queries on these tables are filtered by institution automatically (see app.db.tenancy).
    """

    institution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("institution.id", ondelete="RESTRICT"), index=True
    )
