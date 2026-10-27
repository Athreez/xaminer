import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

RoleName = Literal["ADMIN", "TEACHER", "STUDENT"]
StatusName = Literal["INVITED", "ACTIVE", "DEACTIVATED"]
# Spaces are trimmed before the length check, so "   " is rejected rather than saved as "".
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
GroupName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class AdminUserView(BaseModel):
    """A user as the admin sees them. Built field by field; never includes password data."""

    id: uuid.UUID
    email: str
    full_name: str
    role: RoleName
    status: StatusName
    roll_no: str | None
    locked: bool = Field(description="Locked after too many failed logins (unlock to clear)")
    last_login_at: datetime | None
    created_at: datetime


class UserPage(BaseModel):
    data: list[AdminUserView]
    next_cursor: str | None = Field(
        description="Pass as `cursor` for the next page; null at the end"
    )


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=320)
    full_name: FullName
    role: RoleName
    roll_no: str | None = Field(default=None, max_length=64)


class UpdateUserRequest(BaseModel):
    """Only the fields sent are changed. Send `roll_no: null` to clear it."""

    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, max_length=320)
    full_name: FullName | None = None
    role: RoleName | None = None
    roll_no: str | None = Field(default=None, max_length=64)


# ----------------------------------------------------------------------------- groups


class GroupView(BaseModel):
    id: uuid.UUID
    name: str
    member_count: int
    created_at: datetime


class GroupMemberView(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    roll_no: str | None
    status: StatusName


class GroupDetail(GroupView):
    members: list[GroupMemberView] = Field(description="Sorted by roll number, then name")


class GroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: GroupName


class AddMembersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
