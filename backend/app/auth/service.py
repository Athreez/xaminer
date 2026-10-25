"""Login and logout (PRD AUTH-01, AUTH-04). HTTP details live in router.py."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, Row, case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RefreshToken
from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.schemas import InstitutionChoice, UserView
from app.auth.tokens import Principal, hash_token, new_opaque_token
from app.core.errors import AppError
from app.core.ids import uuid7
from app.db.session import SessionFactory, system_session
from app.platform.models import Institution
from app.users.models import User

# Lockout (PRD AUTH-06): this many wrong passwords in a row lock the account for LOCK_TIME.
MAX_FAILED_LOGINS = 5
LOCK_TIME = timedelta(minutes=15)

# Checked when no account matches, so "no such email" takes as long as "wrong password".
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def invalid_credentials() -> AppError:
    # Same answer for unknown email, wrong password, invited or deactivated account (AUTH-01).
    return AppError("INVALID_CREDENTIALS", "Email or password is incorrect.", status_code=401)


@dataclass
class LoginResult:
    user: UserView
    principal: Principal
    refresh_token: str


async def login(
    factory: SessionFactory,
    *,
    email: str,
    password: str,
    institution_id: uuid.UUID | None,
    refresh_days: int,
    user_agent: str | None,
    ip: str | None,
    now: datetime | None = None,
) -> LoginResult:
    now = now or datetime.now(UTC)
    # Login happens before we know the institution, so it is one of the few system-session paths.
    async with system_session(factory) as session:
        query = (
            select(User, Institution)
            .join(Institution, Institution.id == User.institution_id)
            .where(User.email == email.strip())
        )
        if institution_id is not None:
            query = query.where(User.institution_id == institution_id)
        candidates = (await session.execute(query)).all()

        if not candidates:
            verify_password(_DUMMY_HASH, password)
            raise invalid_credentials()

        matches = [
            (user, institution)
            for user, institution in candidates
            if user.password_hash is not None
            and verify_password(user.password_hash, password)
            and user.status == "ACTIVE"
            and institution.status == "ACTIVE"
        ]
        if not matches:
            await _count_failure(session, candidates, now)
            raise invalid_credentials()
        if len(matches) > 1:
            # Shown only after a correct password, so it can't be used to find accounts.
            choices = [
                InstitutionChoice(id=inst.id, name=inst.name).model_dump(mode="json")
                for _, inst in matches
            ]
            raise AppError(
                "INSTITUTION_REQUIRED",
                "This account exists in more than one institution. Choose one.",
                status_code=409,
                details=choices,
            )

        user, institution = matches[0]
        # Only revealed after a correct password (SECURITY_AND_ACCESS.md § 2.1).
        if user.locked_until is not None and user.locked_until > now:
            raise AppError(
                "ACCOUNT_LOCKED",
                "Too many failed attempts. Try again later.",
                status_code=401,
                details=[{"locked_until": user.locked_until.isoformat()}],
            )

        user.last_login_at = now
        user.failed_logins = 0
        user.locked_until = None
        if user.password_hash is not None and needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        raw, hashed = new_opaque_token()
        session.add(
            RefreshToken(
                institution_id=user.institution_id,
                user_id=user.id,
                family_id=uuid7(),
                token_hash=hashed,
                expires_at=now + timedelta(days=refresh_days),
                user_agent=(user_agent or "")[:255] or None,
                ip=ip,
            )
        )
        await session.commit()

        return LoginResult(
            user=_view(user, institution),
            principal=Principal(user.id, user.institution_id, user.role),
            refresh_token=raw,
        )


async def _count_failure(
    session: AsyncSession, candidates: Sequence[Row[User, Institution]], now: datetime
) -> None:
    """Count a wrong password against active, unlocked accounts; lock at the limit.

    Done in one UPDATE so simultaneous wrong guesses can't slip past the limit. When an account
    locks, its count starts again, so after the lock ends the user gets the full number of tries.
    """
    ids = [
        user.id
        for user, _ in candidates
        if user.status == "ACTIVE" and (user.locked_until is None or user.locked_until <= now)
    ]
    if not ids:
        return
    reaches_limit = User.failed_logins + 1 >= MAX_FAILED_LOGINS
    await session.execute(
        update(User)
        .where(User.id.in_(ids))
        .values(
            failed_logins=case((reaches_limit, 0), else_=User.failed_logins + 1),
            locked_until=case((reaches_limit, now + LOCK_TIME), else_=User.locked_until),
        )
    )
    await session.commit()


async def logout(factory: SessionFactory, raw_refresh_token: str | None) -> None:
    """Revoke the session family of this browser's refresh token. Safe to call repeatedly."""
    if not raw_refresh_token:
        return
    async with system_session(factory) as session:
        token = await session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_refresh_token))
        )
        if token is not None:
            await _revoke(session, RefreshToken.family_id == token.family_id)
            await session.commit()


# Two tabs refreshing at the same moment both send the same cookie; the slower one would look like a
# stolen token. Inside this window it is told to retry (its tab already has the new cookie) instead.
REUSE_GRACE = timedelta(seconds=10)


def _session_ended() -> AppError:
    return AppError("UNAUTHENTICATED", "Your session has ended. Log in again.", status_code=401)


async def refresh(
    factory: SessionFactory,
    raw_refresh_token: str | None,
    *,
    refresh_days: int,
    user_agent: str | None,
    ip: str | None,
    now: datetime | None = None,
) -> LoginResult:
    """Swap a refresh token for a new access token and a new refresh token (PRD AUTH-03).

    Each refresh token works once. Presenting an already-used one (after the grace window) means
    it was copied, so the whole family, i.e. every device of that login, is logged out.
    """
    now = now or datetime.now(UTC)
    if not raw_refresh_token:
        raise _session_ended()

    async with system_session(factory) as session:
        token = await session.scalar(
            select(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(raw_refresh_token))
            .with_for_update()  # two requests with the same token are handled one after the other
        )
        if token is None or token.revoked_at is not None or token.expires_at <= now:
            raise _session_ended()

        if token.used_at is not None:
            if now - token.used_at <= REUSE_GRACE:
                raise AppError(
                    "TOKEN_ALREADY_ROTATED",
                    "This session was just refreshed in another tab. Retry.",
                    status_code=401,
                )
            await _revoke(session, RefreshToken.family_id == token.family_id)
            await session.commit()
            raise AppError(
                "TOKEN_REUSE_DETECTED",
                "This session was used from somewhere else and has been ended. Log in again.",
                status_code=401,
            )

        row = (
            await session.execute(
                select(User, Institution)
                .join(Institution, Institution.id == User.institution_id)
                .where(User.id == token.user_id)
            )
        ).one()
        user, institution = row
        if user.status != "ACTIVE" or institution.status != "ACTIVE":
            await _revoke(session, RefreshToken.family_id == token.family_id)
            await session.commit()
            raise _session_ended()

        token.used_at = now
        raw, hashed = new_opaque_token()
        session.add(
            RefreshToken(
                institution_id=token.institution_id,
                user_id=token.user_id,
                family_id=token.family_id,
                token_hash=hashed,
                expires_at=now + timedelta(days=refresh_days),
                user_agent=(user_agent or "")[:255] or None,
                ip=ip,
            )
        )
        await session.commit()
        return LoginResult(
            user=_view(user, institution),
            principal=Principal(user.id, user.institution_id, user.role),
            refresh_token=raw,
        )


async def logout_everywhere(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Revoke every session of the user (PRD AUTH-04). `session` is the user's tenant session."""
    await _revoke(session, RefreshToken.user_id == user_id)
    await session.commit()


async def current_user(session: AsyncSession, principal: Principal) -> UserView:
    row = (
        await session.execute(
            select(User, Institution)
            .join(Institution, Institution.id == User.institution_id)
            .where(User.id == principal.user_id)
        )
    ).first()
    # Deactivated after the token was issued: the token stops working straight away here.
    if row is None or row[0].status != "ACTIVE":
        raise AppError("UNAUTHENTICATED", "Log in to continue.", status_code=401)
    return _view(row[0], row[1])


async def _revoke(session: AsyncSession, condition: ColumnElement[bool]) -> None:
    await session.execute(
        update(RefreshToken)
        .where(condition, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def _view(user: User, institution: Institution) -> UserView:
    return UserView(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        institution_id=institution.id,
        institution_name=institution.name,
    )
