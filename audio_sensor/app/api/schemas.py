"""Request/response models for the API (what clients see, not the DB tables)."""

import re
from datetime import datetime
from uuid import UUID

from fastapi import Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.censor_words import MAX_CUSTOM_WORDS
from app.database.models import (
    AudioFile,
    AudioStatus,
    CensorMode,
    JobStage,
    SoundEffect,
)
from app.service.audio_service import MAX_PADDING_MS, AudioVariant
from app.subtitles import SubtitleFormat

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
    stage: JobStage | None = Field(
        description="Last finished step: transcribed, detected, rendered; null before any."
    )
    # The settings the job runs with (change them with PATCH /audio/{id}).
    censor_mode: CensorMode
    sound_effect_id: UUID | None = Field(description="Set when censor_mode is sound_effect.")
    custom_words: list[str] = Field(description="Censored on top of the built-in list.")
    padding_ms: int
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
            stage=JobStage(record.stage) if record.stage else None,
            censor_mode=CensorMode(record.censor_mode),
            sound_effect_id=record.sound_effect_id,
            custom_words=list(record.custom_words),
            padding_ms=record.padding_ms,
            censored_url=(
                str(file_url.include_query_params(variant=AudioVariant.CENSORED))
                if completed
                else None
            ),
            original_url=str(file_url.include_query_params(variant=AudioVariant.ORIGINAL)),
        )


class SoundEffectRead(BaseModel):
    """A sound effect you can use with censor_mode sound_effect."""

    id: UUID
    name: str
    built_in: bool = Field(description="Provided for everyone; can't be deleted.")
    created_at: datetime
    file_url: str = Field(description="Download link, to preview it.")

    @classmethod
    def from_effect(cls, effect: SoundEffect, request: Request) -> "SoundEffectRead":
        return cls(
            id=effect.id,
            name=effect.name,
            built_in=effect.user_id is None,
            created_at=effect.created_at,
            file_url=str(request.url_for("read_sound_effect_file", effect_id=effect.id)),
        )


class TranscriptWord(BaseModel):
    word: str
    # Seconds. Null when the aligner couldn't place the word (numbers or
    # symbols); a flagged one is then censored over an estimated span.
    start: float | None = None
    end: float | None = None
    score: float | None = Field(default=None, description="Alignment confidence, 0-1.")
    flagged: bool | None = Field(
        default=None, description="Censored or not; null until detection has run."
    )


class TranscriptRead(BaseModel):
    """What was heard, word by word, and which words were censored."""

    audio_id: UUID
    stage: JobStage | None
    words: list[TranscriptWord]


MAX_VISIBLE_CHARS = 10


class SubtitleOptions(BaseModel):
    """Query parameters of GET /audio/{id}/subtitles."""

    format: SubtitleFormat = Field(
        default=SubtitleFormat.SRT, description="`srt` (default) or `vtt` (WebVTT)."
    )
    symbol: str = Field(
        default="*",
        min_length=1,
        max_length=1,
        description="The character that masks profane words (one character, not a "
        "letter, digit, space or `<`, `>`, `&`).",
    )
    visible_chars: int = Field(
        default=1,
        ge=0,
        le=MAX_VISIBLE_CHARS,
        description="How many leading characters of a profane word stay visible: "
        "1 gives `f***`, 0 masks it all. At least one character is always masked.",
    )

    @field_validator("symbol")
    @classmethod
    def check_symbol(cls, symbol: str) -> str:
        # A letter or digit wouldn't read as masking; <, > and & are markup
        # in subtitle players.
        if symbol.isalnum() or symbol.isspace() or symbol in "<>&":
            raise ValueError("must be a symbol, not a letter, digit, space or <, >, &")
        return symbol


class AudioSettingsUpdate(BaseModel):
    """PATCH /audio/{id} body: the settings to change; anything left out (or
    null) keeps its current value."""

    # Reject unknown fields, so a typo isn't silently ignored.
    model_config = ConfigDict(extra="forbid")

    custom_words: list[str] | None = Field(
        default=None,
        # Rough bound before the real validation (normalize_custom_words),
        # which also drops repeats and so may accept a longer list.
        max_length=MAX_CUSTOM_WORDS * 5,
        description="Extra words to censor, replacing the current list; [] removes them. "
        "Single words only (letters, digits, ' and -), at most "
        f"{MAX_CUSTOM_WORDS}. Whole words: 'banana' doesn't catch 'bananas'.",
        examples=[["banana", "heck"]],
    )
    censor_mode: CensorMode | None = Field(
        default=None, description="mute, beep, or sound_effect (needs sound_effect_id)."
    )
    sound_effect_id: UUID | None = Field(
        default=None, description="Your own sound effect or a built-in one."
    )
    padding_ms: int | None = Field(
        default=None,
        ge=0,
        le=MAX_PADDING_MS,
        description="Extra milliseconds censored on each side of a word.",
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
