"""Student groups (PRD USR-02): admins manage them, teachers read them to assign exams.

Only students can be members; deactivated students can't be added. Every change is audit-logged
in the same transaction.
"""

import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record
from app.auth.tokens import Principal
from app.authz.ownership import get_owned, not_found
from app.core.errors import AppError
from app.core.pagination import like_pattern
from app.users.models import User, UserGroup, UserGroupMember
from app.users.schemas import GroupDetail, GroupMemberView, GroupView


def _audit(
    session: AsyncSession,
    principal: Principal,
    action: str,
    group: UserGroup,
    changes: dict[str, Any] | None = None,
) -> None:
    record(
        session,
        action,
        institution_id=principal.institution_id,
        actor_id=principal.user_id,
        actor_role=principal.role,
        target_type="group",
        target_id=group.id,
        changes=changes,
    )


def _name_taken(name: str) -> AppError:
    return AppError("GROUP_NAME_TAKEN", f'A group called "{name}" already exists.', status_code=409)


async def _check_name_free(session: AsyncSession, name: str, keep: uuid.UUID | None = None) -> None:
    query = select(UserGroup.id).where(UserGroup.name == name)
    if keep:
        query = query.where(UserGroup.id != keep)
    if await session.scalar(query):
        raise _name_taken(name)


async def _save(session: AsyncSession, name: str) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:  # raced with another admin using the same name
        await session.rollback()
        raise _name_taken(name) from exc


# ----------------------------------------------------------------------------- reading


async def list_groups(session: AsyncSession, q: str | None) -> list[GroupView]:
    """All groups of the institution by name, with member counts. Institutions have few groups."""
    counts = (
        select(UserGroupMember.group_id, func.count().label("n"))
        .group_by(UserGroupMember.group_id)
        .subquery()
    )
    query = (
        select(UserGroup, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.group_id == UserGroup.id)
        .order_by(UserGroup.name)
    )
    if q and q.strip():
        query = query.where(UserGroup.name.ilike(like_pattern(q.strip()), escape="\\"))
    rows = (await session.execute(query)).all()
    return [
        GroupView(id=g.id, name=g.name, member_count=n, created_at=g.created_at) for g, n in rows
    ]


async def get_group(session: AsyncSession, principal: Principal, group_id: uuid.UUID) -> UserGroup:
    return await get_owned(session, UserGroup, group_id, principal)


async def detail(session: AsyncSession, group: UserGroup) -> GroupDetail:
    members = await session.scalars(
        select(User)
        .join(UserGroupMember, UserGroupMember.user_id == User.id)
        .where(UserGroupMember.group_id == group.id)
        .order_by(User.roll_no.asc().nulls_last(), User.full_name)
    )
    views = [
        GroupMemberView(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            roll_no=u.roll_no,
            status=u.status,  # type: ignore[arg-type]
        )
        for u in members
    ]
    return GroupDetail(
        id=group.id,
        name=group.name,
        member_count=len(views),
        created_at=group.created_at,
        members=views,
    )


# ----------------------------------------------------------------------------- changing


async def create_group(session: AsyncSession, principal: Principal, name: str) -> UserGroup:
    name = name.strip()
    await _check_name_free(session, name)
    group = UserGroup(name=name)
    session.add(group)
    await session.flush()
    _audit(session, principal, "group.created", group, {"name": {"old": None, "new": name}})
    await _save(session, name)
    return group


async def rename_group(
    session: AsyncSession, principal: Principal, group_id: uuid.UUID, name: str
) -> UserGroup:
    group = await get_group(session, principal, group_id)
    name = name.strip()
    if name == group.name:
        return group
    await _check_name_free(session, name, keep=group.id)
    _audit(session, principal, "group.renamed", group, {"name": {"old": group.name, "new": name}})
    group.name = name
    await _save(session, name)
    return group


async def delete_group(session: AsyncSession, principal: Principal, group_id: uuid.UUID) -> None:
    """Members are removed with it; the students themselves are untouched."""
    group = await get_group(session, principal, group_id)
    count = await session.scalar(
        select(func.count())
        .select_from(UserGroupMember)
        .where(UserGroupMember.group_id == group.id)
    )
    _audit(session, principal, "group.deleted", group, {"name": group.name, "members": count})
    await session.delete(group)
    await session.commit()


async def add_members(
    session: AsyncSession, principal: Principal, group_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> UserGroup:
    """Add students; ones already in the group are skipped. Any invalid id: nothing is added."""
    group = await get_group(session, principal, group_id)
    wanted = list(dict.fromkeys(user_ids))  # drop repeats, keep order
    eligible = set(
        await session.scalars(
            select(User.id).where(
                User.id.in_(wanted), User.role == "STUDENT", User.status != "DEACTIVATED"
            )
        )
    )
    invalid = [uid for uid in wanted if uid not in eligible]
    if invalid:
        raise AppError(
            "INVALID_MEMBERS",
            "Only active or invited students of this institution can be added.",
            status_code=422,
            details=[
                {"field": "user_ids", "message": f"{uid} is not an eligible student", "type": "id"}
                for uid in invalid
            ],
        )
    existing = set(
        await session.scalars(
            select(UserGroupMember.user_id).where(
                UserGroupMember.group_id == group.id, UserGroupMember.user_id.in_(wanted)
            )
        )
    )
    new = [uid for uid in wanted if uid not in existing]
    if new:
        session.add_all(UserGroupMember(group_id=group.id, user_id=uid) for uid in new)
        _audit(
            session, principal, "group.members_added", group, {"user_ids": [str(u) for u in new]}
        )
        await session.commit()
    return group


async def remove_member(
    session: AsyncSession, principal: Principal, group_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    group = await get_group(session, principal, group_id)
    removed = await session.execute(
        delete(UserGroupMember).where(
            UserGroupMember.group_id == group.id, UserGroupMember.user_id == user_id
        )
    )
    if not removed.rowcount:  # type: ignore[attr-defined]
        raise not_found()
    _audit(session, principal, "group.member_removed", group, {"user_id": str(user_id)})
    await session.commit()
