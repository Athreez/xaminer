from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from redis.asyncio import Redis

from app.auth import accounts, service
from app.auth.dependencies import (
    CurrentPrincipal,
    TenantDB,
    redis_of,
    session_factory_of,
    settings_of,
)
from app.auth.schemas import (
    InvitationInfo,
    LoginRequest,
    LoginResponse,
    PasswordResetRequest,
    SetPasswordRequest,
    TokenRequest,
    UserView,
)
from app.auth.tokens import create_access_token
from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import SessionFactory

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "xaminer_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"  # sent only to auth endpoints, never to the rest of the API

Factory = Annotated[SessionFactory, Depends(session_factory_of)]
AppSettings = Annotated[Settings, Depends(settings_of)]
RedisClient = Annotated[Redis, Depends(redis_of)]


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    # HttpOnly: page scripts can't read it. SameSite=Strict: other sites can't make the browser
    # send it (SECURITY_AND_ACCESS.md § 2.2, § 5.1).
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_days * 24 * 3600,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _issue(result: service.LoginResult, response: Response, settings: Settings) -> LoginResponse:
    """Set the new refresh cookie and return a fresh access token."""
    _set_refresh_cookie(response, result.refresh_token, settings)
    return LoginResponse(
        access_token=create_access_token(
            result.principal,
            settings.jwt_secret.get_secret_value(),
            settings.access_token_minutes,
        ),
        expires_in=settings.access_token_minutes * 60,
        user=result.user,
    )


def _cleared_cookie_header(settings: Settings) -> str:
    """The Set-Cookie value that deletes the refresh cookie (for error responses)."""
    scratch = Response()
    _clear_refresh_cookie(scratch, settings)
    return scratch.headers["set-cookie"]


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    factory: Factory,
    settings: AppSettings,
) -> LoginResponse:
    """Log in with email and password. Returns an access token; sets the refresh cookie."""
    result = await service.login(
        factory,
        email=body.email,
        password=body.password,
        institution_id=body.institution_id,
        refresh_days=settings.refresh_token_days,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    return _issue(result, response, settings)


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    factory: Factory,
    settings: AppSettings,
    xaminer_refresh: Annotated[str | None, Cookie()] = None,
) -> LoginResponse:
    """Get a new access token using the refresh cookie. The cookie is replaced each time."""
    try:
        result = await service.refresh(
            factory,
            xaminer_refresh,
            refresh_days=settings.refresh_token_days,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
        )
    except AppError as exc:
        if exc.code != "TOKEN_ALREADY_ROTATED":  # that tab already holds the new cookie: keep it
            exc.headers = {**(exc.headers or {}), "set-cookie": _cleared_cookie_header(settings)}
        raise
    return _issue(result, response, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    factory: Factory,
    settings: AppSettings,
    xaminer_refresh: Annotated[str | None, Cookie()] = None,
) -> None:
    """End this browser's session. Works even if the access token has already expired."""
    await service.logout(factory, xaminer_refresh)
    _clear_refresh_cookie(response, settings)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    principal: CurrentPrincipal, db: TenantDB, response: Response, settings: AppSettings
) -> None:
    """End every session of the current user, on every device."""
    await service.logout_everywhere(db, principal.user_id)
    _clear_refresh_cookie(response, settings)


@router.get("/me")
async def me(principal: CurrentPrincipal, db: TenantDB) -> UserView:
    """The logged-in user."""
    return await service.current_user(db, principal)


@router.post("/invite/inspect")
async def inspect_invitation(body: TokenRequest, factory: Factory) -> InvitationInfo:
    """Who an invitation link is for (the activation page shows it). Doesn't use up the link."""
    return await accounts.inspect_invitation(factory, body.token)


@router.post("/invite/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_invitation(body: SetPasswordRequest, factory: Factory) -> None:
    """Set the first password from an invitation link. The account becomes active."""
    await accounts.accept_invitation(factory, body.token, body.password)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    body: PasswordResetRequest, factory: Factory, redis: RedisClient, settings: AppSettings
) -> dict[str, str]:
    """Email a reset link if the account exists. The answer is the same either way."""
    await accounts.request_password_reset(factory, redis, body.email, settings.public_base_url)
    return {"message": "If an account exists for that email, a reset link has been sent."}


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(body: SetPasswordRequest, factory: Factory) -> None:
    """Set a new password from a reset link. Every session of the account is logged out."""
    await accounts.confirm_password_reset(factory, body.token, body.password)
