"""Request/response models for the API (what clients see, not the DB tables)."""

import re
from datetime import datetime
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.database.models import AudioFile, AudioStatus
from app.service.audio_service import AudioVariant

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class AudioRead(BaseModel):
    """A censor job. Poll GET /audio/{id} until `status` is completed or failed."""

    id: UUID
    status: AudioStatus
    created_at: datetime
    finished_at: datetime | None = Field(
        description="When the job completed or failed; null while it is running."
    )
    words_count: int | None = Field(description="Words transcribed; set once completed.")
    flagged_count: int | None = Field(description="Words censored; set once completed.")
    error: str | None = Field(description="Why the job failed; set only when failed.")
    # Download links (GET /audio/{id}/file). Storage paths stay internal.
    censored_url: str | None = Field(
        description="Download link for the censored file; null until completed."
    )
    original_url: str

    @classmethod
    def from_record(cls, record: AudioFile, request: Request) -> "AudioRead":
        """API view of a record, with download links instead of storage paths."""
        file_url = request.url_for("read_audio_file", audio_id=record.id)
        completed = record.status == AudioStatus.COMPLETED
        return cls(
            id=record.id,
            status=AudioStatus(record.status),
            created_at=record.created_at,
            finished_at=record.finished_at,
            words_count=record.words_count,
            flagged_count=record.flagged_count,
            error=record.error,
            censored_url=(
                str(file_url.include_query_params(variant=AudioVariant.CENSORED))
                if completed
                else None
            ),
            original_url=str(file_url.include_query_params(variant=AudioVariant.ORIGINAL)),
        )


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
