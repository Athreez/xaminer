"""Imports every module's models so `Base.metadata` is complete (used by Alembic)."""

from app.db.base import Base
from app.platform.models import Institution

__all__ = ["Base", "Institution"]
