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
from app.database.models import AudioFile, AudioStatus
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
    available: bool = True  # False simulates Redis being unreachable

    def __call__(self, audio_id: UUID) -> None:
        if not self.available:
            raise ConnectionError("Redis is unreachable (FakeQueue)")
        self.jobs.append(audio_id)


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
