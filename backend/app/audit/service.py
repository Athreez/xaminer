"""Writing audit entries (SECURITY_AND_ACCESS.md § 10).

`record()` only adds the entry to the session: it is saved by the same commit as the change it
describes, so a change can't happen without its record, and a failed change leaves no record.

Never put answers, code, passwords, tokens or evidence in `changes`: ids and field names only.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.core.request_id import current_client, current_request_id

# Never stored in `changes`, whatever a caller passes.
_SECRET_FIELDS = {"password", "password_hash", "token", "token_hash", "refresh_token"}


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Changed fields only: {"role": {"old": "STUDENT", "new": "TEACHER"}}."""
    return {
        key: {"old": old.get(key), "new": new.get(key)}
        for key in sorted(set(old) | set(new))
        if old.get(key) != new.get(key) and key not in _SECRET_FIELDS
    }


def record(
    session: AsyncSession,
    action: str,
    *,
    institution_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    changes: dict[str, Any] | None = None,
) -> None:
    client = current_client()
    safe_changes = (
        {k: v for k, v in changes.items() if k not in _SECRET_FIELDS} if changes else None
    )
    session.add(
        AuditLog(
            institution_id=institution_id,
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            changes=safe_changes or None,
            ip=client.ip if client else None,
            user_agent=client.user_agent if client else None,
            request_id=current_request_id(),
        )
    )
