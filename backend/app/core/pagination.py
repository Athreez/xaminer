"""Opaque cursors for "newest first" lists ordered by UUIDv7 id (ids sort by creation time)."""

import base64
import uuid

from app.core.errors import AppError

MAX_PAGE = 100


def encode_cursor(item_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(item_id.bytes).decode().rstrip("=")


def decode_cursor(cursor: str) -> uuid.UUID:
    try:
        return uuid.UUID(bytes=base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except ValueError as exc:
        raise AppError("VALIDATION_FAILED", "Invalid cursor.", status_code=422) from exc


def like_pattern(text: str) -> str:
    """`%text%` for ILIKE with `escape="\\"`, so `%` and `_` typed by the user match literally."""
    escaped = text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"
