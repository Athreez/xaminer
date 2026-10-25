"""Access tokens (signed JWT, short-lived) and refresh tokens (random, stored only as a hash)."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

ALGORITHM = "HS256"
ACCESS_TYPE = "access"


@dataclass(frozen=True)
class Principal:
    """Who is making the request. Built only from a verified token, never from request data."""

    user_id: uuid.UUID
    institution_id: uuid.UUID
    role: str


class InvalidTokenError(Exception):
    pass


def create_access_token(
    principal: Principal, secret: str, minutes: int, now: datetime | None = None
) -> str:
    issued = now or datetime.now(UTC)
    claims = {
        "sub": str(principal.user_id),
        "inst": str(principal.institution_id),
        "role": principal.role,
        "typ": ACCESS_TYPE,
        "iat": issued,
        "exp": issued + timedelta(minutes=minutes),
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, secret: str) -> Principal:
    try:
        # The algorithm is pinned: a token can't choose its own (e.g. "none").
        claims = jwt.decode(
            token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub", "inst"]}
        )
        if claims.get("typ") != ACCESS_TYPE:
            raise InvalidTokenError("not an access token")
        return Principal(
            user_id=uuid.UUID(claims["sub"]),
            institution_id=uuid.UUID(claims["inst"]),
            role=str(claims["role"]),
        )
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc


def hash_token(raw: str) -> str:
    """Refresh, invitation and reset tokens are stored as SHA-256, never in plain form."""
    return hashlib.sha256(raw.encode()).hexdigest()


def new_opaque_token() -> tuple[str, str]:
    """A random 256-bit token and its hash: (value to give the user, value to store)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)
