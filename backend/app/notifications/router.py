"""Notifications API (PRD NOT-02): your own, newest first, with the unread count."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.auth.dependencies import TenantDB
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.notifications import inbox
from app.notifications.inbox import NotificationList

router = APIRouter(prefix="/notifications", tags=["notifications"])

Reader = Annotated[Principal, Depends(require(P.NOTIFICATION_READ))]


@router.get("")
async def my_notifications(principal: Reader, db: TenantDB) -> NotificationList:
    """The latest 30 and how many are unread."""
    return await inbox.mine(db, principal)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def read_notification(notification_id: uuid.UUID, principal: Reader, db: TenantDB) -> None:
    await inbox.mark_read(db, principal, notification_id)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def read_all_notifications(principal: Reader, db: TenantDB) -> None:
    await inbox.mark_all_read(db, principal)
