import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RoleName = Literal["ADMIN", "TEACHER", "STUDENT"]
StatusName = Literal["INVITED", "ACTIVE", "DEACTIVATED"]


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
    full_name: str = Field(min_length=1, max_length=200)
    role: RoleName
    roll_no: str | None = Field(default=None, max_length=64)


class UpdateUserRequest(BaseModel):
    """Only the fields sent are changed. Send `roll_no: null` to clear it."""

    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, max_length=320)
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: RoleName | None = None
    roll_no: str | None = Field(default=None, max_length=64)
