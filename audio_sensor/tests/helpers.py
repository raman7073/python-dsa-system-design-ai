"""Test helpers. Imported by conftest.py after it has set up the test settings."""

import io
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.database.models import (
    AudioFile,
    AudioStatus,
    AudioTranscript,
    JobStage,
    SoundEffect,
)
from app.security import create_access_token
from app.storage import censored_key, get_storage, upload_key

# Helpers use their own engine without a connection pool, so they work from
# async tests and from sync tests (which use asyncio.run) alike.
helper_engine = create_async_engine(settings.DB_URL, poolclass=NullPool)
helper_sessions = async_sessionmaker(helper_engine, class_=AsyncSession, expire_on_commit=False)


@dataclass
class FakeQueue:
    """Stands in for app.worker.celery_app.enqueue_censor."""

    jobs: list[UUID] = field(default_factory=list)
    # The stage each queued job runs after (None: all steps).
    after: list[JobStage | None] = field(default_factory=list)
    available: bool = True  # False simulates Redis being unreachable

    def __call__(self, audio_id: UUID, after: JobStage | None = None) -> None:
        if not self.available:
            raise ConnectionError("Redis is unreachable (FakeQueue)")
        self.jobs.append(audio_id)
        self.after.append(after)


@dataclass
class AppUser:
    id: UUID
    email: str
    password: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(self.id)[0]}"}


MakeUser = Callable[..., Awaitable[AppUser]]


async def make_audio(
    owner_id: UUID,
    status: AudioStatus = AudioStatus.PENDING,
    *,
    original: bytes = b"original audio bytes",
    censored: bytes | None = None,
    created_at: datetime | None = None,
    **fields: Any,
) -> AudioFile:
    """Insert an audio row and write its original (and optionally censored) file."""
    audio_id = uuid4()
    src = upload_key(audio_id, ".mp3")
    out = censored_key(audio_id, ".mp3")
    storage = get_storage()
    storage.save(src, io.BytesIO(original), max_bytes=10**9)
    if censored is not None:
        storage.save(out, io.BytesIO(censored), max_bytes=10**9)
    record = AudioFile(
        id=audio_id,
        user_id=owner_id,
        file_path=src,
        censored_file_path=out,
        status=status,
        **fields,
    )
    if created_at is not None:
        record.created_at = created_at
    async with helper_sessions() as s:
        s.add(record)
        await s.commit()
    return record


def read_stored(key: str) -> bytes | None:
    """A stored file's content, or None if it doesn't exist."""
    storage = get_storage()
    if not storage.exists(key):
        return None
    with storage.local_copy(key) as path:
        return path.read_bytes()


def stored_keys(prefix: str) -> list[str]:
    """Keys under a prefix ("uploads" or "censored"). Tests use local storage."""
    folder = settings.storage_path / prefix
    return sorted(f"{prefix}/{p.name}" for p in folder.iterdir()) if folder.is_dir() else []


async def get_audio_row(audio_id: UUID) -> AudioFile | None:
    async with helper_sessions() as s:
        return await s.get(AudioFile, audio_id)


class InMemoryRateLimiter:
    """Stands in for the Redis rate limiter (same fixed-window behaviour)."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def hit(self, key: str, limit: int, window_seconds: int) -> int | None:
        self.counts[key] = self.counts.get(key, 0) + 1
        return window_seconds if self.counts[key] > limit else None


async def update_audio_row(audio_id: UUID, **fields: Any) -> None:
    """Change fields of an audio row directly (e.g. to set up a re-run)."""
    async with helper_sessions() as s:
        record = await s.get(AudioFile, audio_id)
        assert record is not None
        for name, value in fields.items():
            setattr(record, name, value)
        s.add(record)
        await s.commit()


async def get_transcript_words(audio_id: UUID) -> list[dict] | None:
    async with helper_sessions() as s:
        transcript = await s.get(AudioTranscript, audio_id)
        return transcript.words if transcript else None


async def make_transcript(audio_id: UUID, words: list[dict]) -> None:
    async with helper_sessions() as s:
        s.add(AudioTranscript(audio_id=audio_id, words=words))
        await s.commit()


async def make_sound_effect(
    owner_id: UUID | None, content: bytes = b"effect audio", name: str = "airhorn"
) -> SoundEffect:
    """Insert a sound effect row and store its file."""
    effect_id = uuid4()
    key = f"effects/{effect_id}.wav"
    get_storage().save(key, io.BytesIO(content), max_bytes=10**9)
    effect = SoundEffect(id=effect_id, user_id=owner_id, name=name, file_path=key)
    async with helper_sessions() as s:
        s.add(effect)
        await s.commit()
    return effect
