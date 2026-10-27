"""platform-admin commands as plain functions (easy to test). __main__.py wires up the CLI."""

import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.audit.service import record
from app.auth.accounts import create_invitation
from app.auth.passwords import WeakPasswordError, check_policy, hash_password
from app.db.session import SessionFactory, system_session, tenant_session
from app.notifications.emails import queue_email
from app.platform.models import Institution, Language
from app.users.models import ROLES, User

DEFAULT_TIMEZONE = "Asia/Kolkata"
# Audit actor for platform-admin commands: an operator at a terminal, not an in-app user.
PLATFORM = "PLATFORM"


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
        await session.flush()
        record(
            session,
            "institution.created",
            institution_id=institution.id,
            actor_role=PLATFORM,
            target_type="institution",
            target_id=institution.id,
            changes={
                "name": {"old": None, "new": name},
                "timezone": {"old": None, "new": timezone},
            },
        )
        await session.commit()
        await session.refresh(institution)
        return institution


async def list_institutions(factory: SessionFactory) -> list[Institution]:
    async with system_session(factory) as session:
        return list(await session.scalars(select(Institution).order_by(Institution.created_at)))


async def list_languages(factory: SessionFactory) -> list[Language]:
    async with system_session(factory) as session:
        return list(await session.scalars(select(Language).order_by(Language.key)))


async def find_institution(factory: SessionFactory, id_or_name: str) -> Institution:
    """Look up an institution by its id, or by its exact name (case-insensitive)."""
    async with system_session(factory) as session:
        try:
            found = await session.get(Institution, uuid.UUID(id_or_name))
        except ValueError:
            found = await session.scalar(
                select(Institution).where(
                    func.lower(Institution.name) == id_or_name.strip().lower()
                )
            )
    if found is None:
        raise CommandError(f"No institution {id_or_name!r}. See: list-institutions")
    return found


async def create_admin(
    factory: SessionFactory, institution: str, email: str, full_name: str, password: str
) -> User:
    """Create an ACTIVE admin with a password: the first account of a new institution."""
    target = await find_institution(factory, institution)
    if target.status != "ACTIVE":
        raise CommandError(f"Institution {target.name!r} is {target.status}.")

    full_name = full_name.strip()
    if not full_name or len(full_name) > 200:
        raise CommandError("Name must be 1-200 characters.")
    try:
        email = validate_email(email.strip(), check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise CommandError(f"Invalid email: {exc}") from exc
    try:
        check_policy(password, email=email, full_name=full_name)
    except WeakPasswordError as exc:
        raise CommandError(str(exc)) from exc

    async with tenant_session(factory, target.id) as session:
        if await session.scalar(select(User.id).where(User.email == email)):
            raise CommandError(f"{email} already has an account in {target.name!r}.")
        admin = User(
            email=email,
            full_name=full_name,
            role="ADMIN",
            status="ACTIVE",
            password_hash=hash_password(password),
        )
        session.add(admin)
        await session.flush()
        record(
            session,
            "user.created",
            institution_id=target.id,
            actor_role=PLATFORM,
            target_type="user",
            target_id=admin.id,
            changes={
                "role": {"old": None, "new": "ADMIN"},
                "status": {"old": None, "new": "ACTIVE"},
            },
        )
        try:
            await session.commit()
        except IntegrityError as exc:  # another command created the same email at the same time
            raise CommandError(f"{email} already has an account in {target.name!r}.") from exc
        return admin


async def invite_user(
    factory: SessionFactory,
    institution: str,
    email: str,
    full_name: str,
    role: str,
    base_url: str,
    roll_no: str | None = None,
) -> tuple[User, bool]:
    """Create an INVITED user and email them an activation link.

    Running it again for someone still INVITED re-sends: a new link that cancels the old one.
    Returns (user, created).
    """
    target = await find_institution(factory, institution)
    role = role.upper()
    if role not in ROLES:
        raise CommandError(f"Role must be one of {', '.join(ROLES)}.")
    full_name = full_name.strip()
    if not full_name or len(full_name) > 200:
        raise CommandError("Name must be 1-200 characters.")
    try:
        email = validate_email(email.strip(), check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise CommandError(f"Invalid email: {exc}") from exc

    async with tenant_session(factory, target.id) as session:
        user = await session.scalar(select(User).where(User.email == email))
        created = user is None
        if user is None:
            user = User(
                email=email,
                full_name=full_name,
                role=role,
                status="INVITED",
                roll_no=(roll_no or "").strip() or None,
            )
            session.add(user)
            await session.flush()
        elif user.status != "INVITED":
            raise CommandError(f"{email} is already {user.status} in {target.name!r}.")
        message = await create_invitation(session, user, target.name, base_url)
        record(
            session,
            "user.invited" if created else "user.invitation_resent",
            institution_id=target.id,
            actor_role=PLATFORM,
            target_type="user",
            target_id=user.id,
            changes={"role": {"old": None, "new": role}} if created else None,
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            raise CommandError("That roll number is already used in this institution.") from exc
    queue_email(message)  # only after the commit, so nobody gets a link that doesn't work
    return user, created
