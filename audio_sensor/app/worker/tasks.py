"""Celery tasks, run only by the worker (see docker-compose.yml)."""

import asyncio
from datetime import timedelta
from typing import Any
from uuid import UUID

from botocore.exceptions import BotoCoreError
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger
from sqlalchemy import func, or_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.audio_censor import AudioCensor, AudioDecodeError
from app.config import get_worker_settings, settings
from app.database.models import AudioFile, AudioStatus, utc_now
from app.storage import get_storage
from app.worker.celery_app import CENSOR_TASK, RECOVER_TASK, celery_app, enqueue_censor

logger = get_task_logger(__name__)

# Messages stored on the record, so the client sees why a job failed. They
# must not include internal details such as paths or tracebacks.
DECODE_ERROR = "Could not decode the upload as audio."
UNEXPECTED_ERROR = "Censoring failed unexpectedly. Try uploading the file again."
TIMEOUT_ERROR = "Censoring took too long. Try a shorter file."
GAVE_UP_ERROR = "Censoring failed repeatedly. Try uploading the file again."
MISSING_UPLOAD_ERROR = "The uploaded file is missing. Try uploading it again."


class _CensorFailed(Exception):
    """The censoring itself failed: record `message` on the job."""

    def __init__(self, message: str, reraise: bool = False):
        self.message = message
        self.reraise = reraise  # unexpected: also fail the task, so it's logged
        super().__init__(message)


# Each task runs its database work with asyncio.run(), i.e. on a new event
# loop every time. Pooled asyncpg connections belong to the loop that opened
# them, so the worker doesn't pool: NullPool opens a connection per use.
# (A connection per database step is nothing next to a minutes-long job.)
_engine = create_async_engine(
    settings.DB_URL, echo=settings.DB_ECHO, poolclass=NullPool
)
_session_maker = async_sessionmaker(
    _engine, class_=AsyncSession, expire_on_commit=False
)

_censor: AudioCensor | None = None


def get_censor() -> AudioCensor:
    """This worker process's AudioCensor.

    Its models load when a job first needs them, not at worker start-up (a
    load takes minutes): the Whisper model on the first job, the alignment
    model on the first job with something to censor. They are then kept for
    later jobs. A plain global is enough: each worker process runs one job at
    a time, in one thread.
    """
    global _censor
    if _censor is None:
        worker_settings = get_worker_settings()
        _censor = AudioCensor(
            censor_words=worker_settings.CENSOR_WORDS,
            model_name=worker_settings.WHISPER_MODEL,
            threads=worker_settings.WHISPER_THREADS or None,
        )
    return _censor


@celery_app.task(
    name=CENSOR_TASK,
    bind=True,
    # Brief database, storage or network outages: retry the whole job with
    # backoff (it is safe to run again, see _claim_job).
    autoretry_for=(DBAPIError, BotoCoreError, ConnectionError),
    retry_backoff=True,
    retry_backoff_max=5 * 60,
    retry_jitter=True,
    max_retries=5,
    # Linux worker only (the soft limit raises SoftTimeLimitExceeded in the
    # task; the hard one kills it shortly after if it doesn't stop).
    soft_time_limit=settings.job_time_limit_seconds,
    time_limit=settings.job_time_limit_seconds + 60,
)
def censor_audio(self: Task, audio_id: UUID) -> None:
    """Censor a stored upload and record the outcome on its `audio` row.

    `audio_id` arrives as a real UUID: Celery's JSON serializer (kombu) tags
    UUIDs in the message and turns them back into UUID objects.
    """
    record = asyncio.run(_claim_job(audio_id, self.request.id))
    if record is None:
        return

    storage = get_storage()
    # Only the censoring step's own failures fail the job. Storage errors
    # (downloading the upload, storing the result) propagate instead, so a
    # brief outage is retried (autoretry_for) rather than failing for good.
    try:
        with (
            storage.local_copy(record.file_path) as src,
            storage.local_output(record.censored_file_path) as out,
        ):
            try:
                written, words = get_censor().censor_audio(
                    str(src),
                    output_path=str(out),
                    padding_ms=record.padding_ms,
                    beep=record.beep,
                    # Nothing to censor and the same format: don't store a
                    # second, identical file (an upload, on S3).
                    copy_unchanged=False,
                )
            except AudioDecodeError as exc:
                raise _CensorFailed(DECODE_ERROR) from exc
            except SoftTimeLimitExceeded as exc:
                logger.warning(
                    "Audio %s exceeded the %s s time limit",
                    audio_id,
                    settings.job_time_limit_seconds,
                )
                raise _CensorFailed(TIMEOUT_ERROR) from exc
            except Exception as exc:
                raise _CensorFailed(UNEXPECTED_ERROR, reraise=True) from exc
            # Leaving the block stores the result, if one was written (a
            # no-op for local storage).
    except FileNotFoundError:
        # From local_copy: the upload is gone. (The censoring step's own
        # errors are all _CensorFailed by now.)
        asyncio.run(
            _finish_job(audio_id, status=AudioStatus.FAILED, error=MISSING_UPLOAD_ERROR)
        )
        return
    except _CensorFailed as failed:
        # Raised inside the block, so the partial output was discarded.
        asyncio.run(
            _finish_job(audio_id, status=AudioStatus.FAILED, error=failed.message)
        )
        if failed.reraise and failed.__cause__ is not None:
            raise failed.__cause__  # Celery logs the original traceback
        return

    unchanged = written is None
    asyncio.run(
        _finish_job(
            audio_id,
            status=AudioStatus.COMPLETED,
            words_count=len(words),
            flagged_count=sum(1 for w in words if w.get("flagged")),
            # Nothing was censored: the "censored" file is the upload itself.
            # (A future delete must not remove a shared key twice over.)
            **({"censored_file_path": record.file_path} if unchanged else {}),
        )
    )


async def _claim_job(audio_id: UUID, task_id: str | None) -> AudioFile | None:
    """Mark the record PROCESSING for this task and return it, or return None
    if this task shouldn't run it.

    The row is locked while deciding, so two deliveries of the same job can't
    both claim it. A job may be claimed when it is PENDING, when it is
    PROCESSING under this same task (Celery redelivered it after the worker
    died, or is retrying it), or when it has been PROCESSING for so long that
    its worker must be gone. After MAX_JOB_ATTEMPTS starts it is failed.
    """
    async with _session_maker() as session:
        result = await session.exec(
            select(AudioFile).where(AudioFile.id == audio_id).with_for_update()
        )
        record = result.first()
        if record is None:
            logger.warning("Audio %s no longer exists; skipping", audio_id)
            return None
        if record.status in (AudioStatus.COMPLETED, AudioStatus.FAILED):
            logger.info("Audio %s is already %s; skipping", audio_id, record.status)
            return None
        if record.status == AudioStatus.PROCESSING and record.task_id != task_id:
            stale_before = utc_now() - timedelta(
                seconds=settings.stale_processing_seconds
            )
            if record.started_at is not None and record.started_at > stale_before:
                logger.info(
                    "Audio %s is being processed by another task; skipping", audio_id
                )
                return None

        now = utc_now()
        if record.attempts >= get_worker_settings().MAX_JOB_ATTEMPTS:
            logger.error(
                "Audio %s failed after %s attempts; giving up",
                audio_id,
                record.attempts,
            )
            record.status = AudioStatus.FAILED
            record.error = GAVE_UP_ERROR
            record.finished_at = now
            session.add(record)
            await session.commit()
            return None

        record.status = AudioStatus.PROCESSING
        record.attempts += 1
        record.task_id = task_id
        record.started_at = now
        session.add(record)
        await session.commit()
        return record


async def _finish_job(audio_id: UUID, **fields: Any) -> None:
    async with _session_maker() as session:
        record = await session.get(AudioFile, audio_id)
        if record is None:
            logger.warning("Audio %s was deleted while it was being censored", audio_id)
            return
        for name, value in fields.items():
            setattr(record, name, value)
        record.finished_at = utc_now()
        session.add(record)
        await session.commit()


@celery_app.task(name=RECOVER_TASK)
def recover_stuck_jobs() -> int:
    """Queue again the jobs that no worker will otherwise finish.

    Run every few minutes by the beat service. Covers a job whose message
    never reached Redis (the API stopped between saving the row and queuing
    it) or was lost, and a job whose worker died without Celery delivering it
    again. Returns how many jobs were queued.
    """
    audio_ids = asyncio.run(_find_stuck_jobs())
    for audio_id in audio_ids:
        enqueue_censor(audio_id)
    if audio_ids:
        logger.warning("Queued %d stuck job(s) again: %s", len(audio_ids), audio_ids)
    return len(audio_ids)


async def _find_stuck_jobs() -> list[UUID]:
    """Stuck jobs, marked as just queued (so they aren't picked up again on
    the next run while their new message waits in the queue)."""
    now = utc_now()
    pending_before = now - timedelta(
        minutes=get_worker_settings().PENDING_REQUEUE_AFTER_MINUTES
    )
    processing_before = now - timedelta(seconds=settings.stale_processing_seconds)
    async with _session_maker() as session:
        result = await session.exec(
            select(AudioFile)
            .where(
                or_(
                    (col(AudioFile.status) == AudioStatus.PENDING)
                    & (
                        func.coalesce(AudioFile.queued_at, AudioFile.created_at)
                        < pending_before
                    ),
                    (col(AudioFile.status) == AudioStatus.PROCESSING)
                    & (
                        func.coalesce(AudioFile.started_at, AudioFile.created_at)
                        < processing_before
                    )
                    & (
                        func.coalesce(AudioFile.queued_at, AudioFile.created_at)
                        < processing_before
                    ),
                )
            )
            # Skip rows a worker is claiming right now; next run gets them.
            .with_for_update(skip_locked=True)
        )
        records = list(result.all())
        for record in records:
            record.queued_at = now
            session.add(record)
        await session.commit()
        return [record.id for record in records]
