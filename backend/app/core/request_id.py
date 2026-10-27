"""Request ID: taken from `X-Request-ID` if the caller sent a sane one, otherwise generated.

Stored in a context variable so log lines and error responses can include it. The caller's IP
address and browser are kept the same way, for the audit log.
"""

import re
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = "x-request-id"
_VALID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


@dataclass(frozen=True)
class Client:
    ip: str | None
    user_agent: str | None


client_var: ContextVar[Client | None] = ContextVar("client", default=None)


def current_request_id() -> str | None:
    return request_id_var.get()


def current_client() -> Client | None:
    """IP and browser of the current HTTP request (None outside a request, e.g. CLI or workers).

    The IP is the real one: uvicorn takes it from nginx, which overwrites X-Forwarded-For.
    """
    return client_var.get()


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        incoming = headers.get(HEADER.encode(), b"").decode("latin-1")
        request_id = incoming if _VALID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        client = scope.get("client")
        client_token = client_var.set(
            Client(
                ip=client[0] if client else None,
                user_agent=headers.get(b"user-agent", b"").decode("latin-1")[:255] or None,
            )
        )

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((HEADER.encode(), request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            request_id_var.reset(token)
            client_var.reset(client_token)
