"""Admin user management API (PRD USR-01, USR-04). Admin only: the role table gives only ADMIN
`user:write`. Every `{user_id}` route answers 404 for users of another institution."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.auth.dependencies import TenantDB, settings_of
from app.auth.tokens import Principal
from app.authz.guards import require
from app.authz.permissions import P
from app.core.config import Settings
from app.users import csv_import, groups, service
from app.users.csv_import import ImportRequest, ImportResult
from app.users.schemas import (
    AddMembersRequest,
    AdminUserView,
    CreateUserRequest,
    GroupDetail,
    GroupRequest,
    GroupView,
    RoleName,
    StatusName,
    UpdateUserRequest,
    UserPage,
)

router = APIRouter(prefix="/users", tags=["users"])

Admin = Annotated[Principal, Depends(require(P.USER_WRITE))]
AppSettings = Annotated[Settings, Depends(settings_of)]


@router.get("")
async def list_users(
    principal: Admin,
    db: TenantDB,
    role: RoleName | None = None,
    status: StatusName | None = None,
    q: Annotated[
        str | None, Query(max_length=100, description="Search name, email, roll no.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> UserPage:
    """Users of the institution, newest first."""
    return await service.list_users(db, role=role, status=status, q=q, limit=limit, cursor=cursor)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest, principal: Admin, db: TenantDB, settings: AppSettings
) -> AdminUserView:
    """Create a user and email them an invitation to set their password."""
    return service.view(await service.create_user(db, principal, body, settings.public_base_url))


@router.post("/import")
async def import_users(
    body: ImportRequest, principal: Admin, db: TenantDB, settings: AppSettings
) -> ImportResult:
    """Check (`dry_run: true`) or import a CSV of users: email, full name, role, roll no.

    Rows with errors are reported and not imported; existing emails are skipped. Each imported
    user gets an invitation email. At most 1 MB and 2,000 users per file.
    """
    return await csv_import.import_users(db, principal, body, settings.public_base_url)


@router.get("/{user_id}")
async def get_user(user_id: uuid.UUID, principal: Admin, db: TenantDB) -> AdminUserView:
    return service.view(await service.get_user(db, principal, user_id))


@router.patch("/{user_id}")
async def update_user(
    user_id: uuid.UUID, body: UpdateUserRequest, principal: Admin, db: TenantDB
) -> AdminUserView:
    """Change name, email, role or roll number. A new email or role logs the user out everywhere."""
    return service.view(await service.update_user(db, principal, user_id, body))


@router.post("/{user_id}/deactivate")
async def deactivate_user(user_id: uuid.UUID, principal: Admin, db: TenantDB) -> AdminUserView:
    """Block login and end all sessions. Their past work is kept."""
    return service.view(await service.deactivate_user(db, principal, user_id))


@router.post("/{user_id}/reactivate")
async def reactivate_user(user_id: uuid.UUID, principal: Admin, db: TenantDB) -> AdminUserView:
    return service.view(await service.reactivate_user(db, principal, user_id))


@router.post("/{user_id}/resend-invite")
async def resend_invite(
    user_id: uuid.UUID, principal: Admin, db: TenantDB, settings: AppSettings
) -> AdminUserView:
    """Email a new invitation link (the old one stops working)."""
    return service.view(
        await service.resend_invitation(db, principal, user_id, settings.public_base_url)
    )


@router.post("/{user_id}/password-reset")
async def send_password_reset(
    user_id: uuid.UUID, principal: Admin, db: TenantDB, settings: AppSettings
) -> AdminUserView:
    """Email the user a password reset link. The admin never sees or sets the password."""
    return service.view(
        await service.send_password_reset(db, principal, user_id, settings.public_base_url)
    )


@router.post("/{user_id}/unlock")
async def unlock_user(user_id: uuid.UUID, principal: Admin, db: TenantDB) -> AdminUserView:
    """Clear a lockout caused by too many failed logins."""
    return service.view(await service.unlock_user(db, principal, user_id))


# ----------------------------------------------------------------------------- groups (USR-02)

groups_router = APIRouter(prefix="/groups", tags=["groups"])

GroupReader = Annotated[Principal, Depends(require(P.GROUP_READ))]
GroupWriter = Annotated[Principal, Depends(require(P.GROUP_WRITE))]


@groups_router.get("")
async def list_groups(
    principal: GroupReader,
    db: TenantDB,
    q: Annotated[str | None, Query(max_length=100, description="Search by name")] = None,
) -> list[GroupView]:
    """All groups of the institution, by name. Admins and teachers."""
    return await groups.list_groups(db, q)


@groups_router.post("", status_code=status.HTTP_201_CREATED)
async def create_group(body: GroupRequest, principal: GroupWriter, db: TenantDB) -> GroupDetail:
    return await groups.detail(db, await groups.create_group(db, principal, body.name))


@groups_router.get("/{group_id}")
async def get_group(group_id: uuid.UUID, principal: GroupReader, db: TenantDB) -> GroupDetail:
    """The group with its members. Admins and teachers."""
    return await groups.detail(db, await groups.get_group(db, principal, group_id))


@groups_router.patch("/{group_id}")
async def rename_group(
    group_id: uuid.UUID, body: GroupRequest, principal: GroupWriter, db: TenantDB
) -> GroupDetail:
    return await groups.detail(db, await groups.rename_group(db, principal, group_id, body.name))


@groups_router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: uuid.UUID, principal: GroupWriter, db: TenantDB) -> None:
    """Delete the group. The students in it are not affected."""
    await groups.delete_group(db, principal, group_id)


@groups_router.post("/{group_id}/members")
async def add_members(
    group_id: uuid.UUID, body: AddMembersRequest, principal: GroupWriter, db: TenantDB
) -> GroupDetail:
    """Add students (ones already in the group are skipped). Nothing is added if any id is not an
    active or invited student of the institution."""
    return await groups.detail(db, await groups.add_members(db, principal, group_id, body.user_ids))


@groups_router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    group_id: uuid.UUID, user_id: uuid.UUID, principal: GroupWriter, db: TenantDB
) -> None:
    await groups.remove_member(db, principal, group_id, user_id)
