"""Request/response models for the API (what clients see, not the DB tables)."""

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class AudioRead(BaseModel):
    id: UUID
    created_at: datetime
    # Download links (GET /audio/{id}/file). Storage paths stay internal.
    censored_url: str
    original_url: str


class UserCreate(BaseModel):
    """Signup request body."""

    # Reject unknown fields, e.g. a client trying to send "is_active".
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(examples=["jane@example.com"])
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        description=(
            f"{PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} characters, with at "
            "least one letter and one digit, and no leading/trailing spaces."
        ),
        examples=["correct-horse-42"],
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, email: str) -> str:
        # Emails are compared case-insensitively, so store them lower-cased.
        return email.lower()

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, password: str) -> str:
        if password != password.strip():
            raise ValueError("must not start or end with whitespace")
        if not re.search(r"[A-Za-z]", password):
            raise ValueError("must contain at least one letter")
        if not re.search(r"\d", password):
            raise ValueError("must contain at least one digit")
        return password


class TokenData(BaseModel):
    """Login response (OAuth2 bearer token)."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until the token expires.")


class UserRead(BaseModel):
    """A user as returned by the API (never includes the password hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    is_active: bool
    created_at: datetime
