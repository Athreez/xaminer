"""In-app notifications and their emails (PRD NOT-02, NOT-03; TCK-1301, TCK-1303).

`notify` adds one notification per user in the caller's transaction; emails, when the event has
one, go out only after it commits (never for a change that rolled back), and only to ACTIVE
accounts (an invited student can't log in yet; they see the notification once they do).

Events: an exam assigned to students (when it's published, or later to a published exam), a
result released, and a released result changed. Users read and mark only their own.
"""

import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import Principal
from app.authz.ownership import get_owned
from app.db.session import after_commit
from app.notifications.emails import Email, queue_email
from app.notifications.models import Notification
from app.users.models import User

LIST_LIMIT = 30


async def notify(
    session: AsyncSession,
    *,
    institution_id: uuid.UUID,
    user_ids: Iterable[uuid.UUID],
    kind: str,
    title: str,
    body: str = "",
    link: str = "",
    email: Callable[[User], Email] | None = None,
) -> int:
    """Notify these users (in-app, and by email if `email` builds one). Returns how many."""
    ids = list(dict.fromkeys(user_ids))
    for user_id in ids:
        session.add(
            Notification(
                institution_id=institution_id,
                user_id=user_id,
                kind=kind,
                title=title[:200],
                body=body,
                link=link,
            )
        )
    if email is not None and ids:
        users = await session.scalars(select(User).where(User.id.in_(ids), User.status == "ACTIVE"))
        messages = [email(u) for u in users]

        def send() -> None:
            for message in messages:
                queue_email(message)

        after_commit(session, send)
    return len(ids)


class NotificationView(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    link: str
    created_at: datetime
    read: bool


class NotificationList(BaseModel):
    items: list[NotificationView]
    unread: int


async def mine(session: AsyncSession, principal: Principal) -> NotificationList:
    rows = await session.scalars(
        select(Notification)
        .where(Notification.user_id == principal.user_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(LIST_LIMIT)
    )
    unread = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == principal.user_id, Notification.read_at.is_(None))
    )
    return NotificationList(
        items=[
            NotificationView(
                id=n.id,
                kind=n.kind,
                title=n.title,
                body=n.body,
                link=n.link,
                created_at=n.created_at,
                read=n.read_at is not None,
            )
            for n in rows
        ],
        unread=unread or 0,
    )


async def mark_read(
    session: AsyncSession, principal: Principal, notification_id: uuid.UUID
) -> None:
    n = await get_owned(
        session,
        Notification,
        notification_id,
        principal,
        owned=lambda n: n.user_id == principal.user_id,
    )
    if n.read_at is None:
        n.read_at = datetime.now(UTC)
        await session.commit()


async def mark_all_read(session: AsyncSession, principal: Principal) -> None:
    await session.execute(
        update(Notification)
        .where(Notification.user_id == principal.user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await session.commit()
