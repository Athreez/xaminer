"""platform-admin commands as plain functions (easy to test). __main__.py wires up the CLI."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select

from app.db.session import SessionFactory, system_session
from app.platform.models import Institution, Language

DEFAULT_TIMEZONE = "Asia/Kolkata"


class CommandError(Exception):
    """A user-facing error: printed without a stack trace."""


async def create_institution(
    factory: SessionFactory, name: str, timezone: str = DEFAULT_TIMEZONE
) -> Institution:
    name = name.strip()
    if not name or len(name) > 200:
        raise CommandError("Name must be 1-200 characters.")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CommandError(f"Unknown timezone {timezone!r}. Example: Asia/Kolkata") from exc

    async with system_session(factory) as session:
        existing = await session.scalar(
            select(Institution.id).where(func.lower(Institution.name) == name.lower())
        )
        if existing:
            raise CommandError(f"An institution named {name!r} already exists ({existing}).")
        institution = Institution(name=name, timezone=timezone)
        session.add(institution)
        await session.commit()
        await session.refresh(institution)
        return institution


async def list_institutions(factory: SessionFactory) -> list[Institution]:
    async with system_session(factory) as session:
        return list(await session.scalars(select(Institution).order_by(Institution.created_at)))


async def list_languages(factory: SessionFactory) -> list[Language]:
    async with system_session(factory) as session:
        return list(await session.scalars(select(Language).order_by(Language.key)))
