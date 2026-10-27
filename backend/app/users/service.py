"""User management by an admin (PRD USR-01, USR-04; SECURITY_AND_ACCESS.md § 2.2).

Every change is audit-logged in the same transaction. Changing someone's email or role, or
deactivating them, ends all their sessions. Emails (invitations, reset links) are queued only
after the commit.
"""

import base64
import uuid
from datetime import UTC, datetime
from typing import Any

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import diff, record
from app.auth.accounts import cancel_all_links, create_invitation, create_password_reset
from app.auth.models import RefreshToken
from app.auth.tokens import Principal
from app.authz.ownership import get_owned
from app.core.errors import AppError
from app.notifications.emails import queue_email
from app.platform.models import Institution
from app.users.models import User
from app.users.schemas import AdminUserView, CreateUserRequest, UpdateUserRequest, UserPage

MAX_PAGE = 100


def view(user: User, now: datetime | None = None) -> AdminUserView:
    now = now or datetime.now(UTC)
    return AdminUserView(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,  # type: ignore[arg-type]
        status=user.status,  # type: ignore[arg-type]
        roll_no=user.roll_no,
        locked=user.locked_until is not None and user.locked_until > now,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def _conflict(code: str, message: str) -> AppError:
    return AppError(code, message, status_code=409)


def _clean_email(email: str) -> str:
    try:
        return validate_email(email.strip(), check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise AppError(
            "VALIDATION_FAILED",
            "Enter a valid email address.",
            status_code=422,
            details=[{"field": "email", "message": str(exc), "type": "email"}],
        ) from exc


def _clean_roll_no(roll_no: str | None) -> str | None:
    return (roll_no or "").strip() or None


def _encode_cursor(user_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(user_id.bytes).decode().rstrip("=")


def _decode_cursor(cursor: str) -> uuid.UUID:
    try:
        return uuid.UUID(bytes=base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except ValueError as exc:
        raise AppError("VALIDATION_FAILED", "Invalid cursor.", status_code=422) from exc


async def _check_roll_no_free(session: AsyncSession, roll_no: str | None) -> None:
    if roll_no and await session.scalar(select(User.id).where(User.roll_no == roll_no)):
        raise _conflict("ROLL_NO_TAKEN", f"Roll number {roll_no} is already used here.")


async def _institution_name(session: AsyncSession, institution_id: uuid.UUID) -> str:
    name = await session.scalar(select(Institution.name).where(Institution.id == institution_id))
    return name or ""


async def _end_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def _guard_last_admin(session: AsyncSession, user: User) -> None:
    """Refuse to remove the last active admin: nobody could manage the institution after that.

    Through the API the actor is itself another active admin, so this only bites when two admins
    remove each other at the same moment. Locking the admin rows makes the second one wait and
    then see the first one's change.
    """
    if user.role != "ADMIN" or user.status != "ACTIVE":
        return
    others = await session.scalars(
        select(User.id)
        .where(User.role == "ADMIN", User.status == "ACTIVE", User.id != user.id)
        .with_for_update()
    )
    if not others.first():
        raise _conflict("LAST_ADMIN", "This is the only active admin. Add another admin first.")


def _audit(
    session: AsyncSession,
    principal: Principal,
    action: str,
    user: User,
    changes: dict[str, Any] | None = None,
) -> None:
    record(
        session,
        action,
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="user",
        target_id=user.id,
        changes=changes,
    )


# ----------------------------------------------------------------------------- reading


async def list_users(
    session: AsyncSession,
    *,
    role: str | None,
    status: str | None,
    q: str | None,
    limit: int,
    cursor: str | None,
) -> UserPage:
    """Newest first, `limit` per page (max 100), filtered by role, status and a text search."""
    limit = max(1, min(limit, MAX_PAGE))
    query = select(User).order_by(User.id.desc()).limit(limit + 1)
    if role:
        query = query.where(User.role == role)
    if status:
        query = query.where(User.status == status)
    if q and q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(
            or_(
                User.full_name.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
                User.roll_no.ilike(pattern, escape="\\"),
            )
        )
    if cursor:
        query = query.where(User.id < _decode_cursor(cursor))  # ids are time-ordered (UUIDv7)
    rows = list(await session.scalars(query))
    page, more = rows[:limit], len(rows) > limit
    now = datetime.now(UTC)
    return UserPage(
        data=[view(user, now) for user in page],
        next_cursor=_encode_cursor(page[-1].id) if more and page else None,
    )


async def get_user(session: AsyncSession, principal: Principal, user_id: uuid.UUID) -> User:
    return await get_owned(session, User, user_id, principal)


# ----------------------------------------------------------------------------- changing


async def create_user(
    session: AsyncSession, principal: Principal, body: CreateUserRequest, base_url: str
) -> User:
    """Create an INVITED user and email them an activation link (PRD USR-01)."""
    email = _clean_email(body.email)
    if await session.scalar(select(User.id).where(User.email == email)):
        raise _conflict("EMAIL_TAKEN", f"{email} already has an account here.")
    roll_no = _clean_roll_no(body.roll_no)
    await _check_roll_no_free(session, roll_no)
    user = User(
        email=email,
        full_name=body.full_name.strip(),
        role=body.role,
        status="INVITED",
        roll_no=roll_no,
    )
    session.add(user)
    await _save(session, commit=False)
    message = await create_invitation(
        session, user, await _institution_name(session, principal.institution_id), base_url
    )
    _audit(
        session,
        principal,
        "user.invited",
        user,
        diff({}, {"email": email, "role": body.role, "full_name": user.full_name}),
    )
    await _save(session)
    queue_email(message)
    return user


async def update_user(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID, body: UpdateUserRequest
) -> User:
    user = await get_user(session, principal, user_id)
    sent = body.model_fields_set
    before = {"email": user.email, "full_name": user.full_name, "role": user.role,
              "roll_no": user.roll_no}  # fmt: skip

    if "role" in sent and body.role is not None and body.role != user.role:
        if user.id == principal.user_id:
            raise _conflict("CANNOT_CHANGE_OWN_ROLE", "You can't change your own role.")
        await _guard_last_admin(session, user)
        user.role = body.role
    if "email" in sent and body.email is not None:
        email = _clean_email(body.email)
        if email.lower() != user.email.lower():
            if await session.scalar(select(User.id).where(User.email == email)):
                raise _conflict("EMAIL_TAKEN", f"{email} already has an account here.")
            user.email = email
    if "full_name" in sent and body.full_name is not None:
        user.full_name = body.full_name.strip()
    if "roll_no" in sent:
        roll_no = _clean_roll_no(body.roll_no)
        if roll_no != user.roll_no:
            await _check_roll_no_free(session, roll_no)
            user.roll_no = roll_no

    after = {"email": user.email, "full_name": user.full_name, "role": user.role,
             "roll_no": user.roll_no}  # fmt: skip
    changes = diff(before, after)
    if not changes:
        return user
    # A new email or role means existing logins carry stale identity: end them (SECURITY § 2.2).
    if "email" in changes or "role" in changes:
        await _end_sessions(session, user.id)
        await cancel_all_links(session, user.id)  # links mailed to the old address stop working
    _audit(session, principal, "user.updated", user, changes)
    await _save(session)
    return user


async def deactivate_user(session: AsyncSession, principal: Principal, user_id: uuid.UUID) -> User:
    """Block login and end all sessions. Past work is kept (PRD USR-01)."""
    user = await get_user(session, principal, user_id)
    if user.id == principal.user_id:
        raise _conflict("CANNOT_DEACTIVATE_SELF", "You can't deactivate your own account.")
    if user.status == "DEACTIVATED":
        return user
    await _guard_last_admin(session, user)
    old = user.status
    user.status = "DEACTIVATED"
    user.deactivated_at = datetime.now(UTC)
    await _end_sessions(session, user.id)
    await cancel_all_links(session, user.id)
    _audit(
        session, principal, "user.deactivated", user, diff({"status": old}, {"status": user.status})
    )
    await _save(session)
    return user


async def reactivate_user(session: AsyncSession, principal: Principal, user_id: uuid.UUID) -> User:
    """Back to ACTIVE, or to INVITED if they never set a password."""
    user = await get_user(session, principal, user_id)
    if user.status != "DEACTIVATED":
        return user
    user.status = "ACTIVE" if user.password_hash else "INVITED"
    user.deactivated_at = None
    _audit(
        session,
        principal,
        "user.reactivated",
        user,
        diff({"status": "DEACTIVATED"}, {"status": user.status}),
    )
    await _save(session)
    return user


async def resend_invitation(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID, base_url: str
) -> User:
    user = await get_user(session, principal, user_id)
    if user.status != "INVITED":
        raise _conflict("NOT_INVITED", "Only users who haven't activated yet can be re-invited.")
    message = await create_invitation(
        session, user, await _institution_name(session, principal.institution_id), base_url
    )
    _audit(session, principal, "user.invitation_resent", user)
    await _save(session)
    queue_email(message)
    return user


async def send_password_reset(
    session: AsyncSession, principal: Principal, user_id: uuid.UUID, base_url: str
) -> User:
    """Email the user a reset link (PRD USR-04). The admin never sees or sets the password."""
    user = await get_user(session, principal, user_id)
    if user.status != "ACTIVE":
        raise _conflict("NOT_ACTIVE", "Only active users can be sent a password reset link.")
    message = await create_password_reset(
        session, user, await _institution_name(session, principal.institution_id), base_url
    )
    _audit(session, principal, "user.password_reset_sent", user)
    await _save(session)
    queue_email(message)
    return user


async def unlock_user(session: AsyncSession, principal: Principal, user_id: uuid.UUID) -> User:
    """Clear a lockout from too many failed logins (SECURITY § 2.1 trade-off)."""
    user = await get_user(session, principal, user_id)
    if user.locked_until is None and user.failed_logins == 0:
        return user
    user.locked_until = None
    user.failed_logins = 0
    _audit(session, principal, "user.unlocked", user)
    await _save(session)
    return user


async def _save(session: AsyncSession, *, commit: bool = True) -> None:
    try:
        await (session.commit() if commit else session.flush())
    except IntegrityError as exc:  # raced with another change (same email or roll number)
        await session.rollback()
        raise _conflict("CONFLICT", "That email or roll number is already used here.") from exc
