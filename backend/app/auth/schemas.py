import uuid

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)
    # Only needed when the same email + password belongs to accounts in several institutions.
    institution_id: uuid.UUID | None = None


class UserView(BaseModel):
    """What the client may know about the logged-in user. Built field by field from the row."""

    id: uuid.UUID
    email: str
    full_name: str
    role: str
    institution_id: uuid.UUID
    institution_name: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 (the OAuth token type name, not a secret)
    expires_in: int = Field(description="Seconds until the access token expires")
    user: UserView


class InstitutionChoice(BaseModel):
    id: uuid.UUID
    name: str


class InvitationInfo(BaseModel):
    email: str
    full_name: str
    institution_name: str


class TokenRequest(BaseModel):
    """One-time tokens travel in the body, never the URL, so they can't end up in access logs."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=10, max_length=200)


class SetPasswordRequest(TokenRequest):
    password: str = Field(max_length=1024)


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=320)
