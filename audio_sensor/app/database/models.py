from datetime import UTC, datetime
from enum import StrEnum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Index, String, text
from sqlmodel import Field, Relationship, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class AudioStatus(StrEnum):
    """Progress of a censor job (run by the Celery worker, app.worker.tasks)."""

    PENDING = "pending"  # uploaded and queued
    PROCESSING = "processing"  # a worker is censoring it
    COMPLETED = "completed"  # censored file is ready to download
    FAILED = "failed"  # see AudioFile.error


# Relationship loading: the app uses AsyncSession, where an unloaded
# relationship can't be fetched implicitly on attribute access. With
# "raise_on_sql", reading one that isn't loaded yet raises a clear error
# instead of the confusing MissingGreenlet; load it in the query instead:
#     select(AudioFile).options(selectinload(AudioFile.user))
#     select(User).options(selectinload(User.audios))
# It still resolves without a query when the related object is already in
# the session (e.g. the User loaded by get_current_user in the same request).
_EXPLICIT_LOAD = {"lazy": "raise_on_sql"}


class AudioFile(SQLModel, table=True):
    # SQLModel types __tablename__ as a declared_attr, so a plain string trips
    # type checkers even though it's the documented way to set the name.
    __tablename__ = "audio"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        # A user's records newest first (GET /audio). Also serves every
        # lookup by user_id alone, such as the foreign key.
        Index("ix_audio_user_id_created_at", "user_id", "created_at", "id"),
        # Only unfinished jobs, which are few: counting a user's active jobs
        # (the upload cap) and finding stuck ones (recover_stuck_jobs) stay
        # fast however many finished records pile up.
        Index(
            "ix_audio_active",
            "user_id",
            "status",
            postgresql_where=text("status IN ('pending', 'processing')"),
        ),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Owner. Only they can read this record (see AudioService). Nullable
    # because rows created before uploads required login have no owner;
    # those rows can't be read through the API.
    user_id: UUID | None = Field(default=None, foreign_key="users.id")
    # Relative to STORAGE_DIR, e.g. "uploads/<id>.mp3" (see app.storage).
    file_path: str
    # Where the worker writes the censored file. Set at upload; the file only
    # exists once status is COMPLETED.
    censored_file_path: str
    # A plain string column rather than a database ENUM type, so adding a
    # status later needs no type migration.
    status: AudioStatus = Field(default=AudioStatus.PENDING, sa_type=String(20))
    # Why the job failed, safe to show the client. Set only when FAILED.
    error: str | None = None
    # Job options, kept on the row so a lost job can be queued again.
    padding_ms: int = 150
    beep: bool = False
    # Set when the job completes.
    words_count: int | None = None
    flagged_count: int | None = None
    # How many times a worker has started this job. A job that keeps killing
    # its worker (e.g. out of memory) is failed after MAX_JOB_ATTEMPTS.
    attempts: int = 0
    # The Celery task currently running the job. A redelivery of the same
    # task (after a worker crash) may take it over; a different one may not.
    task_id: str | None = Field(default=None, max_length=64)
    # Timezone-aware (UTC): SQLModel rejects naive datetimes, and the column
    # is TIMESTAMP WITH TIME ZONE.
    created_at: datetime = Field(default_factory=utc_now)
    # When the job was last put on the queue (see recover_stuck_jobs).
    queued_at: datetime | None = None
    # When a worker last started the job.
    started_at: datetime | None = None
    # When the job finished, whether it completed or failed.
    finished_at: datetime | None = None

    # ORM-only (no column): the owner, via user_id. Many audio -> one user.
    # Optional["User"] (a string) because User is defined below.
    user: Optional["User"] = Relationship(
        back_populates="audios", sa_relationship_kwargs=_EXPLICIT_LOAD
    )


class User(SQLModel, table=True):
    # "user" is a reserved word in PostgreSQL, so the table is "users".
    __tablename__ = "users"  # pyright: ignore[reportAssignmentType]
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Stored lower-cased (see UserService), so uniqueness is case-insensitive.
    email: str = Field(max_length=254, unique=True, index=True)
    # Argon2 hash; the plain password is never stored.
    hashed_password: str
    is_active: bool = True
    created_at: datetime = Field(default_factory=utc_now)

    # ORM-only (no column): all audio rows whose user_id is this user.
    # One user -> many audio. Not loaded with the user (every authenticated
    # request loads the user); load it explicitly when needed.
    audios: list[AudioFile] = Relationship(
        back_populates="user", sa_relationship_kwargs=_EXPLICIT_LOAD
    )
