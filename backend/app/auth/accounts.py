"""Invitations and password reset (PRD AUTH-02, AUTH-05; SECURITY_AND_ACCESS.md § 2.1)."""

import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.auth.models import AuthToken, RefreshToken
from app.auth.passwords import WeakPasswordError, check_policy, hash_password
from app.auth.schemas import InvitationInfo
from app.auth.tokens import hash_token, new_opaque_token
from app.core.errors import AppError
from app.core.rate_limit import hit
from app.db.session import SessionFactory, system_session
from app.notifications.emails import (
    INVITE_DAYS,
    RESET_HOURS,
    Email,
    invitation_email,
    password_reset_email,
    queue_email,
)
from app.platform.models import Institution
from app.users.models import User

RESET_REQUESTS_PER_HOUR = 3


def invalid_link() -> AppError:
    # One answer for unknown, used, expired or wrong-kind tokens.
    return AppError("INVALID_TOKEN", "This link is invalid or has expired.", status_code=400)


def _weak(exc: WeakPasswordError) -> AppError:
    return AppError(
        "VALIDATION_FAILED",
        str(exc),
        status_code=422,
        details=[{"field": "password", "message": str(exc), "type": "weak_password"}],
    )


async def _cancel_open_tokens(
    session: AsyncSession, user_id: uuid.UUID, purpose: str, now: datetime
) -> None:
    """Re-sending a link makes the older ones stop working."""
    await session.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user_id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
        )
        .values(used_at=now)
    )


async def create_password_reset(
    session: AsyncSession, user: User, institution_name: str, base_url: str
) -> Email:
    """Add a fresh reset token (cancelling older ones). Caller commits, then queues the email."""
    now = datetime.now(UTC)
    await _cancel_open_tokens(session, user.id, "RESET", now)
    raw, hashed = new_opaque_token()
    session.add(
        AuthToken(
            institution_id=user.institution_id,
            user_id=user.id,
            purpose="RESET",
            token_hash=hashed,
            expires_at=now + timedelta(hours=RESET_HOURS),
        )
    )
    return password_reset_email(
        to=user.email,
        full_name=user.full_name,
        institution_name=institution_name,
        token=raw,
        base_url=base_url,
    )


async def cancel_all_links(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Make every open invitation and reset link of the user stop working (e.g. on deactivation)."""
    now = datetime.now(UTC)
    for purpose in ("INVITE", "RESET"):
        await _cancel_open_tokens(session, user_id, purpose, now)


async def create_invitation(
    session: AsyncSession, user: User, institution_name: str, base_url: str
) -> Email:
    """Add a fresh invitation token for an INVITED user. Caller commits, then queues the email."""
    now = datetime.now(UTC)
    await _cancel_open_tokens(session, user.id, "INVITE", now)
    raw, hashed = new_opaque_token()
    session.add(
        AuthToken(
            institution_id=user.institution_id,
            user_id=user.id,
            purpose="INVITE",
            token_hash=hashed,
            expires_at=now + timedelta(days=INVITE_DAYS),
        )
    )
    return invitation_email(
        to=user.email,
        full_name=user.full_name,
        institution_name=institution_name,
        token=raw,
        base_url=base_url,
    )


async def _use_token(
    session: AsyncSession, raw: str, purpose: str, now: datetime
) -> tuple[AuthToken, User, Institution]:
    found = (
        await session.execute(
            select(AuthToken, User, Institution)
            .join(User, User.id == AuthToken.user_id)
            .join(Institution, Institution.id == User.institution_id)
            .where(AuthToken.token_hash == hash_token(raw))
            .with_for_update(of=AuthToken)  # a link can't be used twice at the same moment
        )
    ).first()
    if found is None:
        raise invalid_link()
    token, user, institution = found
    if (
        token.purpose != purpose
        or token.used_at is not None
        or token.expires_at <= now
        or institution.status != "ACTIVE"
    ):
        raise invalid_link()
    return token, user, institution


async def inspect_invitation(factory: SessionFactory, raw: str) -> InvitationInfo:
    """Who the invitation is for, so the activation page can greet them. Doesn't use the token."""
    async with system_session(factory) as session:
        _, user, institution = await _use_token(session, raw, "INVITE", datetime.now(UTC))
        if user.status != "INVITED":
            raise invalid_link()
        return InvitationInfo(
            email=user.email, full_name=user.full_name, institution_name=institution.name
        )


async def accept_invitation(factory: SessionFactory, raw: str, password: str) -> None:
    """Set the first password and activate the account (PRD AUTH-02)."""
    now = datetime.now(UTC)
    async with system_session(factory) as session:
        token, user, _ = await _use_token(session, raw, "INVITE", now)
        if user.status != "INVITED":
            raise invalid_link()
        try:
            check_policy(password, email=user.email, full_name=user.full_name)
        except WeakPasswordError as exc:
            raise _weak(exc) from exc  # the link stays valid so they can try another password
        user.password_hash = hash_password(password)
        user.status = "ACTIVE"
        token.used_at = now
        record(
            session,
            "auth.invitation_accepted",
            institution_id=user.institution_id,
            actor_id=user.id,
            actor_role=user.role,
            target_type="user",
            target_id=user.id,
            changes={"status": {"old": "INVITED", "new": "ACTIVE"}},
        )
        await session.commit()


async def request_password_reset(
    factory: SessionFactory, redis: Redis, email: str, base_url: str
) -> None:
    """Email a reset link if an active account exists. The caller always answers the same way."""
    email = email.strip()
    if not (await hit(redis, f"reset:{email.lower()}", RESET_REQUESTS_PER_HOUR, 3600)).allowed:
        return  # over the limit: silently do nothing, so the answer still reveals nothing

    emails: list[Email] = []
    async with system_session(factory) as session:
        rows = (
            await session.execute(
                select(User, Institution)
                .join(Institution, Institution.id == User.institution_id)
                .where(
                    User.email == email,
                    User.status == "ACTIVE",
                    Institution.status == "ACTIVE",
                )
            )
        ).all()
        # The same person can have an account in more than one institution: one link each.
        for user, institution in rows:
            emails.append(await create_password_reset(session, user, institution.name, base_url))
        await session.commit()
    for message in emails:
        queue_email(message)


async def confirm_password_reset(factory: SessionFactory, raw: str, password: str) -> None:
    """Set a new password and log out every session of that account (PRD AUTH-05)."""
    now = datetime.now(UTC)
    async with system_session(factory) as session:
        token, user, _ = await _use_token(session, raw, "RESET", now)
        if user.status != "ACTIVE":
            raise invalid_link()
        try:
            check_policy(password, email=user.email, full_name=user.full_name)
        except WeakPasswordError as exc:
            raise _weak(exc) from exc
        user.password_hash = hash_password(password)
        user.failed_logins = 0
        user.locked_until = None
        token.used_at = now
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        record(
            session,
            "auth.password_reset",
            institution_id=user.institution_id,
            actor_id=user.id,
            actor_role=user.role,
            target_type="user",
            target_id=user.id,
        )
        await session.commit()
