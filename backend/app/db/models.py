"""Imports every module's models so `Base.metadata` is complete (used by Alembic)."""

from app.auth.models import AuthToken, RefreshToken
from app.db.base import Base
from app.platform.models import Institution, Language
from app.users.models import User

__all__ = ["AuthToken", "Base", "Institution", "Language", "RefreshToken", "User"]
