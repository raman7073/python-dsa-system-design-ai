import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy import func, tuple_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import get_api_settings
from app.database.models import AudioFile, AudioStatus, User, utc_now
from app.storage import (
    Download,
    Storage,
    censored_key,
    get_storage,
    input_suffix,
    media_type_for,
    output_suffix,
    upload_key,
)

# Queues the censor job for a stored upload (its options are on the record).
# In the app this is app.worker.celery_app.enqueue_censor; tests can pass a fake.
EnqueueCensor = Callable[[UUID], None]


class AudioNotFoundError(LookupError):
    """No `audio` record with that ID, or its file is missing from storage."""


class AudioNotReadyError(RuntimeError):
    """The censored file isn't available: the job is still running, or failed."""

    def __init__(self, record: AudioFile):
        self.status = AudioStatus(record.status)
        if self.status is AudioStatus.FAILED:
            message = f"Censoring audio {record.id} failed: {record.error}"
        else:
            message = f"Audio {record.id} is still {self.status}; try again shortly"
        super().__init__(message)


class QueueUnavailableError(RuntimeError):
    """The censor job could not be queued (Redis is unreachable)."""


class TooManyActiveJobsError(RuntimeError):
    """The user already has the maximum number of jobs pending or processing."""

    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f"You already have {limit} audio files being censored")


ACTIVE_STATUSES = (AudioStatus.PENDING, AudioStatus.PROCESSING)


class AudioVariant(StrEnum):
    CENSORED = "censored"
    ORIGINAL = "original"


@dataclass
class StoredAudioFile:
    download: Download
    media_type: str
    download_filename: str


class AudioService:
    """Stores uploads, queues their censor jobs, and reads back the results.

    Knows nothing about HTTP, so it can be reused from scripts or tests. The
    censoring itself runs in a Celery worker (app.worker.tasks). Files go to
    the configured Storage (local disk or S3); storage calls block, so they
    run in a thread.
    """

    def __init__(
        self,
        session: AsyncSession,
        enqueue_censor: EnqueueCensor,
        storage: Storage | None = None,
        max_upload_bytes: int | None = None,
        max_active_jobs: int | None = None,
    ):
        self.session = session
        self.enqueue_censor = enqueue_censor
        self.storage = storage or get_storage()
        self.max_upload_bytes = max_upload_bytes or get_api_settings().max_upload_bytes
        self.max_active_jobs = max_active_jobs or get_api_settings().MAX_ACTIVE_JOBS_PER_USER

    async def submit_upload(
        self,
        owner_id: UUID,
        filename: str | None,
        data: BinaryIO,
        padding_ms: int = 150,
        beep: bool = False,
    ) -> AudioFile:
        """Save the upload as a PENDING record of `owner_id` and queue its job.

        Returns straight away; the worker censors the file and moves the
        record to COMPLETED or FAILED. Nothing is kept unless the file, the
        row and the queued job all succeed. Raises TooManyActiveJobsError if
        the user already has the maximum number of jobs in progress,
        UploadTooLargeError if the upload exceeds the size limit, and
        QueueUnavailableError if the job can't be queued.
        """
        in_suffix = input_suffix(filename)
        out_suffix = output_suffix(in_suffix)

        # Files are named by the record's ID, so names never collide and the
        # client's filename is never used as a key.
        audio_id = uuid4()
        src = upload_key(audio_id, in_suffix)
        out = censored_key(audio_id, out_suffix)

        # Storing the file can take seconds (a 50 MB upload to S3), so no
        # database connection or lock is held meanwhile; holding one per
        # upload would let a few slow uploads use up the connection pool.
        # A quick unlocked check first, so users at the cap don't upload for
        # nothing; then end that transaction (and the one the login check
        # opened). commit() rather than rollback(): rollback would expire the
        # already-loaded user.
        await self._check_active_jobs(owner_id, lock=False)
        await self.session.commit()
        await asyncio.to_thread(self.storage.save, src, data, self.max_upload_bytes)

        try:
            # The authoritative check, in one short transaction with the
            # insert: another upload may have taken the last slot meanwhile.
            await self._check_active_jobs(owner_id, lock=True)
            record = AudioFile(
                id=audio_id,
                user_id=owner_id,
                file_path=src,
                censored_file_path=out,
                padding_ms=padding_ms,
                beep=beep,
                queued_at=utc_now(),
            )
            self.session.add(record)
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            await asyncio.to_thread(self.storage.delete, src)
            raise

        # Queued only after the commit, so the worker always finds the row.
        # Publishing to Redis is blocking I/O, so it runs in a thread.
        try:
            await asyncio.to_thread(self.enqueue_censor, audio_id)
        except Exception as exc:
            # No worker will ever pick this record up; remove it rather than
            # leave it pending forever.
            await self.session.delete(record)
            await self.session.commit()
            await asyncio.to_thread(self.storage.delete, src)
            raise QueueUnavailableError("Could not queue the censor job") from exc

        return record

    async def _check_active_jobs(self, owner_id: UUID, lock: bool) -> None:
        """Raise TooManyActiveJobsError if the user is at the limit.

        With `lock`, the user's row stays locked until the transaction ends
        (the new record is committed), so two uploads at the same moment
        can't both pass the check.
        """
        if lock:
            await self.session.exec(select(User).where(User.id == owner_id).with_for_update())
        active = await self.session.scalar(
            select(func.count())
            .select_from(AudioFile)
            .where(AudioFile.user_id == owner_id, col(AudioFile.status).in_(ACTIVE_STATUSES))
        )
        if (active or 0) >= self.max_active_jobs:
            raise TooManyActiveJobsError(self.max_active_jobs)

    async def get_audio(self, audio_id: UUID, owner_id: UUID) -> AudioFile:
        """`owner_id`'s audio record with this ID. Raises AudioNotFoundError.

        Someone else's record is reported as not found, the same as an ID
        that doesn't exist, so callers can't probe which IDs exist.
        """
        record = await self.session.scalar(
            select(AudioFile).where(AudioFile.id == audio_id, AudioFile.user_id == owner_id)
        )
        if record is None:
            raise AudioNotFoundError(f"No audio with id {audio_id}")
        return record

    async def list_audios(
        self,
        owner_id: UUID,
        limit: int = 50,
        offset: int = 0,
        before: tuple[datetime, UUID] | None = None,
    ) -> list[AudioFile]:
        """`owner_id`'s audio records, newest first, one page at a time.

        Page with `before` (the (created_at, id) of the previous page's last
        record): served straight from the (user_id, created_at, id) index, so
        every page costs the same. `offset` still works, but deep offsets
        make the database read and skip every earlier row.
        """
        query = select(AudioFile).where(AudioFile.user_id == owner_id)
        if before is not None:
            query = query.where(
                tuple_(col(AudioFile.created_at), col(AudioFile.id)) < tuple_(*before)
            )
        result = await self.session.exec(
            # id breaks ties between rows with the same created_at, so pages
            # never overlap or skip a record.
            query.order_by(col(AudioFile.created_at).desc(), col(AudioFile.id).desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

    async def get_audio_file(
        self,
        audio_id: UUID,
        owner_id: UUID,
        variant: AudioVariant = AudioVariant.CENSORED,
    ) -> StoredAudioFile:
        """The censored or original file of `owner_id`'s record.

        Raises AudioNotReadyError if the censored file is requested before the
        job has completed, and AudioNotFoundError if the record doesn't exist,
        belongs to someone else, or its file has been removed from storage.
        """
        record = await self.get_audio(audio_id, owner_id)
        if variant is AudioVariant.CENSORED and record.status != AudioStatus.COMPLETED:
            raise AudioNotReadyError(record)

        key = (
            record.censored_file_path
            if variant is AudioVariant.CENSORED
            else record.file_path
        )
        try:
            download = await asyncio.to_thread(self.storage.download, key)
        except FileNotFoundError as exc:
            raise AudioNotFoundError(
                f"The {variant} file for audio {audio_id} is missing"
            ) from exc

        # The client's original filename isn't stored, so name downloads by ID.
        suffix = "_censored" if variant is AudioVariant.CENSORED else ""
        return StoredAudioFile(
            download=download,
            media_type=media_type_for(key),
            download_filename=f"{audio_id}{suffix}{PurePosixPath(key).suffix}",
        )
