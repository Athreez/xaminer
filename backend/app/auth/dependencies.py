"""FastAPI dependencies: who is calling, and a database session scoped to their institution."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import InvalidTokenError, Principal, decode_access_token
from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import SessionFactory, tenant_session

_bearer = HTTPBearer(auto_error=False)


def settings_of(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def session_factory_of(request: Request) -> SessionFactory:
    factory: SessionFactory = request.app.state.session_factory
    return factory


def redis_of(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


def _unauthenticated() -> AppError:
    return AppError(
        "UNAUTHENTICATED",
        "Log in to continue.",
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_principal(
    settings: Annotated[Settings, Depends(settings_of)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """The verified caller. Role and institution come only from the signed token."""
    if credentials is None:
        raise _unauthenticated()
    try:
        return decode_access_token(credentials.credentials, settings.jwt_secret.get_secret_value())
    except InvalidTokenError as exc:
        raise _unauthenticated() from exc


async def tenant_db(
    factory: Annotated[SessionFactory, Depends(session_factory_of)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> AsyncIterator[AsyncSession]:
    """A database session that only sees the caller's institution (architecture § 5)."""
    async with tenant_session(factory, principal.institution_id) as session:
        yield session


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
TenantDB = Annotated[AsyncSession, Depends(tenant_db)]
