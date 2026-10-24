"""One error format for every response (TECHNICAL_ARCHITECTURE.md § 8):

    {"error": {"code": "SNAKE_CASE_CODE", "message": "...", "details": [...], "request_id": "..."}}

Clients switch on `code`, never on `message`. Stack traces and SQL never reach the client.
"""

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_id import current_request_id

logger = logging.getLogger(__name__)

_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_FAILED",
    429: "RATE_LIMITED",
}


class AppError(Exception):
    """Raise from any module to return a documented error code."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        self.headers = headers


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    request_id = current_request_id()
    if request_id:
        body["request_id"] = request_id
    return JSONResponse({"error": jsonable_encoder(body)}, status_code=status_code, headers=headers)


async def _app_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        raise exc
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        raise exc
    code = _HTTP_CODES.get(exc.status_code, "ERROR")
    message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").capitalize()
    return error_response(exc.status_code, code, message, headers=exc.headers)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    details = [
        {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"], "type": err["type"]}
        for err in exc.errors()
    ]
    return error_response(422, "VALIDATION_FAILED", "The request is not valid.", details)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)


class UnhandledErrorMiddleware:
    """Turns any unexpected exception into a plain 500 in our error format.

    Done as middleware (inside the request-ID middleware) rather than an exception handler, because
    Starlette runs catch-all handlers outside all middleware, where the request ID is already gone.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def track(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, track)
        except Exception:
            logger.exception("unhandled error")
            if response_started:
                raise
            response = error_response(500, "INTERNAL_ERROR", "Something went wrong on our side.")
            await response(scope, receive, send)
