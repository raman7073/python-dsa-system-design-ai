from datetime import UTC, datetime
from enum import StrEnum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, Index, String, text
from sqlalchemy.dialects import postgresql
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


class JobStage(StrEnum):
    """The last finished step of a censor job (AudioFile.stage).

    The worker runs the steps in this order, one Celery task each
    (app.worker.tasks); each needs the one before it to have finished.
    """

    TRANSCRIBED = "transcribed"  # transcript stored (with word timestamps)
    DETECTED = "detected"  # flagged words marked in the transcript
    RENDERED = "rendered"  # censored audio stored; the job is COMPLETED


class CensorMode(StrEnum):
    """What replaces each flagged word."""

    MUTE = "mute"  # silence
    BEEP = "beep"  # a 1 kHz tone
    SOUND_EFFECT = "sound_effect"  # AudioFile.sound_effect


class SoundEffect(SQLModel, table=True):
    """A sound that can replace flagged words (CensorMode.SOUND_EFFECT).

    Either a user's own (user_id set, only they can use it) or built in
    (user_id NULL, available to everyone).
    """

    __tablename__ = "sound_effects"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        # Names are unique per owner, ignoring case ("Airhorn" and "airhorn"
        # are one name), so different users can each have an "airhorn".
        # NULLS NOT DISTINCT (Postgres 15+) makes built-in effects unique among
        # themselves too, instead of treating every NULL owner as different.
        Index(
            "uq_sound_effects_user_id_lower_name",
            "user_id",
            text("lower(name)"),
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # NULL = built in. Deleting a user deletes their effects.
    user_id: UUID | None = Field(default=None, foreign_key="users.id", ondelete="CASCADE")
    name: str = Field(max_length=100)
    # Storage key (app.storage), e.g. "effects/<id>.mp3"; works on S3 too.
    file_path: str
    created_at: datetime = Field(default_factory=utc_now)

    user: Optional["User"] = Relationship(
        back_populates="sound_effects", sa_relationship_kwargs=_EXPLICIT_LOAD
    )


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
        # Deleting a sound effect sets this to NULL on every job using it;
        # without an index that would scan the whole table. Partial: most
        # jobs use no effect.
        Index(
            "ix_audio_sound_effect_id",
            "sound_effect_id",
            postgresql_where=text("sound_effect_id IS NOT NULL"),
        ),
    )
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # Display name, e.g. the uploaded file's name. Never used as a storage key.
    name: str | None = Field(default=None, max_length=255)
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
    # The last finished step (NULL: none yet). A step only runs when the job
    # is waiting for exactly that step, so duplicate or late deliveries skip.
    # To run steps again (e.g. detect with new custom words), set this back
    # to the step before them and queue from there (enqueue_censor(after=...)).
    stage: JobStage | None = Field(default=None, sa_type=String(20))
    # Why the job failed, safe to show the client. Set only when FAILED.
    error: str | None = None
    # Job options, kept on the row so a lost job can be queued again.
    padding_ms: int = 150
    # A plain string column, like status.
    censor_mode: CensorMode = Field(default=CensorMode.MUTE, sa_type=String(20))
    # The sound for CensorMode.SOUND_EFFECT. NULL if the effect was deleted
    # after the job was created: the worker then fails the job instead.
    sound_effect_id: UUID | None = Field(
        default=None, foreign_key="sound_effects.id", ondelete="SET NULL"
    )
    # Extra words to censor on top of the built-in list, copied onto the job
    # at upload so a retried or re-queued job uses the same words. Single
    # words, lower-cased. Never NULL: an empty list means "none".
    custom_words: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            postgresql.ARRAY(postgresql.TEXT), nullable=False, server_default="{}"
        ),
    )
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
    # Last change to the row. Set by the ORM on every update (the API and
    # worker both update through it), not by raw SQL.
    updated_at: datetime = Field(
        default_factory=utc_now, sa_column_kwargs={"onupdate": utc_now}
    )

    # ORM-only (no column): the owner, via user_id. Many audio -> one user.
    # Optional["User"] (a string) because User is defined below.
    user: Optional["User"] = Relationship(
        back_populates="audios", sa_relationship_kwargs=_EXPLICIT_LOAD
    )
    # ORM-only: the sound effect, via sound_effect_id. Many audio -> one effect.
    sound_effect: SoundEffect | None = Relationship(sa_relationship_kwargs=_EXPLICIT_LOAD)
    # ORM-only: the word-level transcript, in its own table (see AudioTranscript).
    transcript: Optional["AudioTranscript"] = Relationship(
        back_populates="audio", sa_relationship_kwargs=_EXPLICIT_LOAD
    )


class AudioTranscript(SQLModel, table=True):
    """A job's word-level transcript (one per audio row).

    In its own table rather than a column on `audio`: a long upload has
    thousands of words, and listing audio (GET /audio) loads whole rows, so a
    transcript column would be read for every record on every page.
    """

    __tablename__ = "audio_transcripts"  # pyright: ignore[reportAssignmentType]

    audio_id: UUID = Field(foreign_key="audio.id", primary_key=True, ondelete="CASCADE")
    # [{"word": ..., "start": ..., "end": ..., "score": ..., "flagged": ...}]
    # (app.audio_censor.Word). SQLAlchemy doesn't notice in-place changes to
    # a JSON list: assign a new list to update it.
    words: list[dict] = Field(sa_column=Column(postgresql.JSONB, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)

    audio: AudioFile = Relationship(
        back_populates="transcript", sa_relationship_kwargs=_EXPLICIT_LOAD
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
    # ORM-only: the user's own sound effects (not the built-in ones).
    sound_effects: list[SoundEffect] = Relationship(
        back_populates="user", sa_relationship_kwargs=_EXPLICIT_LOAD
    )
