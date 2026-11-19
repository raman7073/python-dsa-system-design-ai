"""AudioService.submit_upload holds no database connection or lock while the
file is being stored (slow on S3), and still enforces the active-jobs cap."""

import asyncio
import io
from typing import BinaryIO

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.config import get_api_settings
from app.database.models import AudioStatus, User
from app.database.session import async_session_maker
from app.service.audio_service import AudioService, TooManyActiveJobsError
from app.storage import get_storage
from tests.helpers import FakeQueue, MakeUser, helper_engine, make_audio, stored_keys


class ObservingStorage:
    """Local storage that runs `during_save` while a file is being saved."""

    def __init__(self, during_save):
        self.inner = get_storage()
        self.during_save = during_save

    def save(self, key: str, source: BinaryIO, max_bytes: int) -> None:
        self.during_save()
        self.inner.save(key, source, max_bytes)

    def __getattr__(self, name):
        return getattr(self.inner, name)


async def user_row_is_free(user_id) -> bool:
    """Can another connection lock the user's row right now?"""
    async with helper_engine.connect() as conn:
        try:
            await conn.execute(
                text("SELECT 1 FROM users WHERE id = :id FOR UPDATE NOWAIT"), {"id": user_id}
            )
        except DBAPIError:
            return False
        finally:
            await conn.rollback()
    return True


async def test_no_transaction_or_lock_while_storing(make_user: MakeUser) -> None:
    owner = await make_user()
    seen: dict[str, bool] = {}

    async with async_session_maker() as session:
        # What the login check does: load the user (opens a transaction).
        user = await session.get(User, owner.id)
        assert user is not None and session.in_transaction()

        def during_save() -> None:
            seen["in_transaction"] = session.in_transaction()

        service = AudioService(session, FakeQueue(), storage=ObservingStorage(during_save))  # type: ignore[arg-type]
        record = await service.submit_upload(owner.id, "a.mp3", io.BytesIO(b"audio"))

    assert seen["in_transaction"] is False  # connection back in the pool
    assert record.status == AudioStatus.PENDING
    assert user.email == owner.email  # still usable (not expired)


async def test_user_row_not_locked_while_storing(make_user: MakeUser) -> None:
    owner = await make_user()
    checks: list[bool] = []

    async with async_session_maker() as session:
        await session.get(User, owner.id)

        loop = asyncio.get_running_loop()

        def during_save() -> None:
            # Runs in the save thread: ask the event loop to probe the lock.
            checks.append(
                asyncio.run_coroutine_threadsafe(user_row_is_free(owner.id), loop).result(10)
            )

        service = AudioService(session, FakeQueue(), storage=ObservingStorage(during_save))  # type: ignore[arg-type]
        await service.submit_upload(owner.id, "a.mp3", io.BytesIO(b"audio"))

    assert checks == [True]


async def test_slot_taken_while_storing_is_refused_and_file_removed(
    make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await make_user()
    monkeypatch.setattr(get_api_settings(), "MAX_ACTIVE_JOBS_PER_USER", 1)

    loop = asyncio.get_running_loop()

    def another_upload_finishes_first() -> None:
        asyncio.run_coroutine_threadsafe(make_audio(owner.id), loop).result(10)

    queue = FakeQueue()
    async with async_session_maker() as session:
        await session.get(User, owner.id)
        service = AudioService(
            session, queue, storage=ObservingStorage(another_upload_finishes_first)  # type: ignore[arg-type]
        )
        with pytest.raises(TooManyActiveJobsError):
            await service.submit_upload(owner.id, "a.mp3", io.BytesIO(b"audio"))

    assert queue.jobs == []
    # Only the other upload's file is left; this one's was deleted.
    assert len(stored_keys("uploads")) == 1


async def test_user_at_cap_is_refused_before_uploading(
    make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await make_user()
    monkeypatch.setattr(get_api_settings(), "MAX_ACTIVE_JOBS_PER_USER", 1)
    await make_audio(owner.id)
    saves: list[str] = []

    async with async_session_maker() as session:
        await session.get(User, owner.id)
        service = AudioService(
            session, FakeQueue(), storage=ObservingStorage(lambda: saves.append("save"))  # type: ignore[arg-type]
        )
        with pytest.raises(TooManyActiveJobsError):
            await service.submit_upload(owner.id, "a.mp3", io.BytesIO(b"audio"))

    assert saves == []  # rejected by the quick check, nothing uploaded
