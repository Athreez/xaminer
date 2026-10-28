"""Reading the audit log (PRD AUD-03). Admin only; read-only by design (there is no write API).

Search by user, action, item and date, newest first, with cursor pages like the user list.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.core.errors import AppError
from app.core.pagination import MAX_PAGE, decode_cursor, encode_cursor
from app.users.models import User


class AuditActor(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str


class AuditEntry(BaseModel):
    id: uuid.UUID
    created_at: datetime
    actor_role: str | None = Field(description="Role at the time, or PLATFORM for the CLI")
    actor: AuditActor | None = Field(description="Null for the system or someone not logged in")
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    changes: dict[str, Any] | None
    ip: str | None
    user_agent: str | None
    request_id: str | None


class AuditPage(BaseModel):
    data: list[AuditEntry]
    next_cursor: str | None


async def list_entries(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str | None,
    target_type: str | None,
    target_id: uuid.UUID | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
    cursor: str | None,
) -> AuditPage:
    if since and until and since >= until:
        raise AppError("VALIDATION_FAILED", "`from` must be before `to`.", status_code=422)
    limit = max(1, min(limit, MAX_PAGE))
    query = (
        select(AuditLog, User)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .order_by(AuditLog.id.desc())
        .limit(limit + 1)
    )
    if actor_id:
        query = query.where(AuditLog.actor_id == actor_id)
    if action:
        # "user." matches every user action; anything else must match exactly.
        if action.endswith("."):
            query = query.where(AuditLog.action.startswith(action, autoescape=True))
        else:
            query = query.where(AuditLog.action == action)
    if target_type:
        query = query.where(AuditLog.target_type == target_type)
    if target_id:
        query = query.where(AuditLog.target_id == target_id)
    if since:
        query = query.where(AuditLog.created_at >= since)
    if until:
        query = query.where(AuditLog.created_at < until)
    if cursor:
        query = query.where(AuditLog.id < decode_cursor(cursor))
    rows = (await session.execute(query)).all()
    page, more = rows[:limit], len(rows) > limit
    return AuditPage(
        data=[
            AuditEntry(
                id=row.id,
                created_at=row.created_at,
                actor_role=row.actor_role,
                actor=AuditActor(id=user.id, full_name=user.full_name, email=user.email)
                if user
                else None,
                action=row.action,
                target_type=row.target_type,
                target_id=row.target_id,
                changes=row.changes,
                ip=row.ip,
                user_agent=row.user_agent,
                request_id=row.request_id,
            )
            for row, user in page
        ],
        next_cursor=encode_cursor(page[-1][0].id) if more and page else None,
    )


router = APIRouter(prefix="/audit-logs", tags=["audit"])

Admin = Annotated[Principal, Depends(require(P.AUDIT_LOG_READ))]


@router.get("")
async def search_audit_log(
    principal: Admin,
    db: TenantDB,
    actor_id: Annotated[uuid.UUID | None, Query(description="Who did it")] = None,
    action: Annotated[
        str | None,
        Query(max_length=64, description='Exact action, or a prefix ending in "." like "user."'),
    ] = None,
    target_type: Annotated[str | None, Query(max_length=32, description="e.g. user")] = None,
    target_id: Annotated[uuid.UUID | None, Query(description="The item acted on")] = None,
    since: Annotated[datetime | None, Query(alias="from", description="Inclusive")] = None,
    until: Annotated[datetime | None, Query(alias="to", description="Exclusive")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> AuditPage:
    """The institution's audit log, newest first."""
    return await list_entries(
        db,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        since=since,
        until=until,
        limit=limit,
        cursor=cursor,
    )


@router.get("/actions")
async def list_actions(principal: Admin, db: TenantDB) -> list[str]:
    """Every action name that appears in this institution's log, for the filter menu."""
    return list(await db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action)))
