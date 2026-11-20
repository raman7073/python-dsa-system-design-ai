"""Celery tasks, run only by the worker (see docker-compose.yml).

A censor job is three steps, each its own task taking only the audio id:

1. transcribe_audio_task: transcribe the upload (word timestamps included)
   and store the transcript (audio_transcripts).
2. detect_profanity_task: flag profane words (built-in list plus the job's
   custom words) in the stored transcript.
3. render_audio_task: write the censored audio from the flagged transcript
   and the job's settings (mute, beep or sound effect); the job completes.

An upload queues all three as a chain (enqueue_censor). Each can also run on
its own: a step runs only when the job's `stage` says the step before it has
finished and this one hasn't, so steps can be re-run by setting the stage
back, and duplicate or late deliveries of a step simply skip.
"""

import asyncio
from collections.abc import Callable, Generator
from contextlib import contextmanager, nullcontext
from datetime import timedelta
from pathlib import PurePosixPath
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

from app.audio_censor import (
    AudioCensor,
    AudioDecodeError,
    AudioTooLongError,
    SoundEffectError,
    Word,
)
from app.config import get_worker_settings, settings
from app.database.models import (
    AudioFile,
    AudioStatus,
    AudioTranscript,
    CensorMode,
    JobStage,
    SoundEffect,
    utc_now,
)
from app.storage import censored_key, get_storage, output_suffix
from app.worker.celery_app import (
    DETECT_TASK,
    RECOVER_TASK,
    RENDER_TASK,
    TRANSCRIBE_TASK,
    celery_app,
    enqueue_censor,
)

logger = get_task_logger(__name__)

# Messages stored on the record, so the client sees why a job failed. They
# must not include internal details such as paths or tracebacks.
DECODE_ERROR = "Could not decode the upload as audio."
UNEXPECTED_ERROR = "Censoring failed unexpectedly. Try uploading the file again."
TIMEOUT_ERROR = "Censoring took too long. Try a shorter file."
GAVE_UP_ERROR = "Censoring failed repeatedly. Try uploading the file again."
MISSING_UPLOAD_ERROR = "The uploaded file is missing. Try uploading it again."
MISSING_TRANSCRIPT_ERROR = "The transcript is missing. Try uploading the file again."
SOUND_EFFECT_MISSING_ERROR = "The chosen sound effect no longer exists."
SOUND_EFFECT_ERROR = "The chosen sound effect could not be read as audio."
TOO_LONG_ERROR = f"The audio is longer than {settings.MAX_AUDIO_MINUTES} minutes."


class _CensorFailed(Exception):
    """A step failed for good: record `message` on the job."""

    def __init__(self, message: str, reraise: bool = False):
        self.message = message
        self.reraise = reraise  # unexpected: also fail the task, so it's logged
        super().__init__(message)


# Each task runs its database work with asyncio.run(), i.e. on a new event
# loop every time. Pooled asyncpg connections belong to the loop that opened
# them, so the worker doesn't pool: NullPool opens a connection per use.
# (A connection per database step is nothing next to a minutes-long job.)
_engine = create_async_engine(settings.DB_URL, echo=settings.DB_ECHO, poolclass=NullPool)
_session_maker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

_censor: AudioCensor | None = None


def get_censor() -> AudioCensor:
    """This worker process's AudioCensor.

    Its models load when a step first needs them, not at worker start-up (a
    load takes minutes), and are then kept. Only transcription uses models;
    detection and rendering don't. A plain global is enough: each worker
    process runs one task at a time, in one thread.
    """
    global _censor
    if _censor is None:
        worker_settings = get_worker_settings()
        _censor = AudioCensor(
            censor_words=worker_settings.CENSOR_WORDS,
            model_name=worker_settings.WHISPER_MODEL,
            threads=worker_settings.WHISPER_THREADS or None,
            max_effect_seconds=settings.MAX_SOUND_EFFECT_SECONDS,
        )
    return _censor


# Shared by the three steps.
_STEP_OPTIONS: dict[str, Any] = {
    "bind": True,
    # Brief database, storage or network outages: retry the step with
    # backoff (it is safe to run again, see _claim_step).
    "autoretry_for": (DBAPIError, BotoCoreError, ConnectionError),
    "retry_backoff": True,
    "retry_backoff_max": 5 * 60,
    "retry_jitter": True,
    "max_retries": 5,
    # Linux worker only (the soft limit raises SoftTimeLimitExceeded in the
    # task; the hard one kills it shortly after if it doesn't stop).
    "soft_time_limit": settings.job_time_limit_seconds,
    "time_limit": settings.job_time_limit_seconds + 60,
}


# --- 1. transcribe -------------------------------------------------------------


@celery_app.task(name=TRANSCRIBE_TASK, **_STEP_OPTIONS)
def transcribe_audio_task(self: Task, audio_id: UUID) -> None:
    """Transcribe the upload and store the transcript, with every word's
    timestamps (detection may later flag any word, e.g. with new custom
    words, and rendering needs to know where each one is)."""
    record = asyncio.run(_claim_step(audio_id, self.request.id, requires=None))
    if record is None:
        return

    def transcribe() -> list[Word]:
        with get_storage().local_copy(record.file_path) as src, _censoring(audio_id):
            # Never decodes more than the limit, whatever the headers claim.
            return get_censor().transcribe_audio(
                str(src), max_seconds=settings.MAX_AUDIO_MINUTES * 60
            )

    words = _run_step(audio_id, transcribe)
    if words is not None:
        asyncio.run(_save_transcript(audio_id, words))


async def _save_transcript(audio_id: UUID, words: list[Word]) -> None:
    async with _session_maker() as session:
        transcript = await session.get(AudioTranscript, audio_id)
        if transcript is None:
            transcript = AudioTranscript(audio_id=audio_id, words=_as_json(words))
        else:
            transcript.words = _as_json(words)  # a new list, so the change is saved
        session.add(transcript)
        await _complete_step(session, audio_id, JobStage.TRANSCRIBED, words_count=len(words))


# --- 2. detect -------------------------------------------------------------------


@celery_app.task(name=DETECT_TASK, **_STEP_OPTIONS)
def detect_profanity_task(self: Task, audio_id: UUID) -> None:
    """Flag profane words in the stored transcript: the built-in list, the
    worker's CENSOR_WORDS and the job's custom_words. Needs no models."""
    record = asyncio.run(_claim_step(audio_id, self.request.id, requires=JobStage.TRANSCRIBED))
    if record is None:
        return
    words = asyncio.run(_load_transcript(audio_id))
    if words is None:
        asyncio.run(_fail_job(audio_id, MISSING_TRANSCRIPT_ERROR))
        return

    def detect() -> list[Word]:
        with _censoring(audio_id):
            # Fresh dicts: flags from an earlier run with other words go.
            fresh = [Word(**{k: v for k, v in w.items() if k != "flagged"}) for w in words]  # type: ignore[typeddict-item]
            return get_censor().detect_profanity(fresh, record.custom_words)

    flagged = _run_step(audio_id, detect)
    if flagged is not None:
        asyncio.run(_save_detection(audio_id, flagged))


async def _save_detection(audio_id: UUID, words: list[Word]) -> None:
    async with _session_maker() as session:
        transcript = await session.get(AudioTranscript, audio_id)
        if transcript is not None:
            transcript.words = _as_json(words)
            session.add(transcript)
        await _complete_step(
            session,
            audio_id,
            JobStage.DETECTED,
            flagged_count=sum(1 for w in words if w.get("flagged")),
        )


# --- 3. render ---------------------------------------------------------------------


@celery_app.task(name=RENDER_TASK, **_STEP_OPTIONS)
def render_audio_task(self: Task, audio_id: UUID) -> None:
    """Write the censored audio from the flagged transcript and the job's
    settings, store it, and complete the job."""
    record = asyncio.run(_claim_step(audio_id, self.request.id, requires=JobStage.DETECTED))
    if record is None:
        return
    words = asyncio.run(_load_transcript(audio_id))
    if words is None:
        asyncio.run(_fail_job(audio_id, MISSING_TRANSCRIPT_ERROR))
        return

    effect_key = None
    if record.censor_mode == CensorMode.SOUND_EFFECT:
        effect_key = asyncio.run(_sound_effect_key(record.sound_effect_id))
        if effect_key is None:
            asyncio.run(_fail_job(audio_id, SOUND_EFFECT_MISSING_ERROR))
            return

    # Always the job's own censored/ key: after an earlier render with
    # nothing to censor, censored_file_path is the upload itself, and writing
    # there would overwrite the original.
    target = censored_key(audio_id, output_suffix(PurePosixPath(record.file_path).suffix))
    storage = get_storage()

    def render() -> str:
        with (
            storage.local_copy(record.file_path) as src,
            storage.local_copy(effect_key) if effect_key else nullcontext(None) as effect,
            storage.local_output(target) as out,
            _censoring(audio_id),
        ):
            written = get_censor().render_audio(
                str(src),
                words,
                output_path=str(out),
                padding_ms=record.padding_ms,
                beep=record.censor_mode == CensorMode.BEEP,
                sound_effect_path=str(effect) if effect else None,
                # Nothing to censor and the same format: don't store a
                # second, identical file (an upload, on S3).
                copy_unchanged=False,
            )
        # Nothing censored: the "censored" file is the upload itself. (A
        # future delete must not remove a shared key twice over.)
        return target if written is not None else record.file_path

    censored = _run_step(audio_id, render, missing_effect_key=effect_key)
    if censored is None:
        return
    asyncio.run(_save_render(audio_id, censored))
    # A re-render may leave the previous censored file unused.
    previous = record.censored_file_path
    if previous not in (censored, record.file_path) and not previous.startswith("uploads/"):
        storage.delete(previous)


async def _save_render(audio_id: UUID, censored_path: str) -> None:
    async with _session_maker() as session:
        await _complete_step(
            session,
            audio_id,
            JobStage.RENDERED,
            status=AudioStatus.COMPLETED,
            censored_file_path=censored_path,
            finished_at=utc_now(),
        )


async def _sound_effect_key(effect_id: UUID | None) -> str | None:
    if effect_id is None:
        return None
    async with _session_maker() as session:
        effect = await session.get(SoundEffect, effect_id)
        return effect.file_path if effect else None


# --- shared by the steps ----------------------------------------------------------------


@contextmanager
def _censoring(audio_id: UUID) -> Generator[None]:
    """Turn the censoring work's own errors into job failures. Storage errors
    stay outside this block, so brief outages are retried instead."""
    try:
        yield
    except AudioDecodeError as exc:
        raise _CensorFailed(DECODE_ERROR) from exc
    except AudioTooLongError as exc:
        raise _CensorFailed(TOO_LONG_ERROR) from exc
    except SoundEffectError as exc:
        raise _CensorFailed(SOUND_EFFECT_ERROR) from exc
    except SoftTimeLimitExceeded as exc:
        logger.warning(
            "Audio %s exceeded the %s s time limit", audio_id, settings.job_time_limit_seconds
        )
        raise _CensorFailed(TIMEOUT_ERROR) from exc
    except Exception as exc:
        raise _CensorFailed(UNEXPECTED_ERROR, reraise=True) from exc


def _run_step[T](
    audio_id: UUID,
    work: Callable[[], T],
    missing_effect_key: str | None = None,
) -> T | None:
    """Run a step's work; on failure, fail the job and return None.

    A missing upload (or sound effect) fails the job; an unexpected error
    also fails the task, so Celery logs it. Other errors (storage or
    database outages) propagate, so the step is retried.
    """
    try:
        return work()
    except FileNotFoundError as exc:
        # From storage.local_copy (the censoring work's own errors are all
        # _CensorFailed by now): which file is gone?
        missing = exc.args[0] if exc.args else None
        message = (
            SOUND_EFFECT_MISSING_ERROR
            if missing_effect_key and missing == missing_effect_key
            else MISSING_UPLOAD_ERROR
        )
        asyncio.run(_fail_job(audio_id, message))
    except _CensorFailed as failed:
        asyncio.run(_fail_job(audio_id, failed.message))
        if failed.reraise and failed.__cause__ is not None:
            raise failed.__cause__ from None  # Celery logs the original traceback
    return None


async def _claim_step(
    audio_id: UUID, task_id: str | None, requires: JobStage | None
) -> AudioFile | None:
    """Mark the job PROCESSING for this step's task and return it, or return
    None if this task shouldn't run.

    The row is locked while deciding, so two deliveries can't both claim it.
    The step may run when the job is at `requires` (the step before it has
    finished and this one hasn't) and no other task is running it: the slot
    is free, or held by this same task (Celery redelivered it after the
    worker died, or is retrying it), or held so long its worker must be
    gone. After MAX_JOB_ATTEMPTS starts of the step, the job is failed.
    """
    async with _session_maker() as session:
        result = await session.exec(
            select(AudioFile).where(AudioFile.id == audio_id).with_for_update()
        )
        record = result.first()
        if record is None:
            logger.warning("Audio %s no longer exists; skipping", audio_id)
            return None
        if record.status == AudioStatus.FAILED:
            logger.info("Audio %s has failed; skipping", audio_id)
            return None
        if record.stage != requires:
            # Already done (a duplicate or late delivery), or not ready yet.
            logger.info(
                "Audio %s is at stage %s, not %s; skipping", audio_id, record.stage, requires
            )
            return None
        if record.task_id is not None and record.task_id != task_id:
            stale_before = utc_now() - timedelta(seconds=settings.stale_processing_seconds)
            if record.started_at is not None and record.started_at > stale_before:
                logger.info("Audio %s is being processed by another task; skipping", audio_id)
                return None

        now = utc_now()
        if record.attempts >= get_worker_settings().MAX_JOB_ATTEMPTS:
            logger.error("Audio %s failed after %s attempts; giving up", audio_id, record.attempts)
            record.status = AudioStatus.FAILED
            record.error = GAVE_UP_ERROR
            record.task_id = None
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


async def _complete_step(
    session: AsyncSession, audio_id: UUID, stage: JobStage, **fields: Any
) -> None:
    """Record a finished step (with `fields`) and free the job for the next
    one, in the session's transaction (committed here)."""
    record = await session.get(AudioFile, audio_id)
    if record is None:
        logger.warning("Audio %s was deleted during the %s step", audio_id, stage)
        return
    record.stage = stage
    record.task_id = None
    record.attempts = 0  # attempts count per step
    for name, value in fields.items():
        setattr(record, name, value)
    session.add(record)
    await session.commit()


async def _fail_job(audio_id: UUID, error: str) -> None:
    async with _session_maker() as session:
        record = await session.get(AudioFile, audio_id)
        if record is None:
            logger.warning("Audio %s was deleted while it was being censored", audio_id)
            return
        record.status = AudioStatus.FAILED
        record.error = error
        record.task_id = None
        record.finished_at = utc_now()
        session.add(record)
        await session.commit()


def _as_json(words: list[Word]) -> list[dict[str, Any]]:
    """Words as plain dicts for the JSONB column (always a new list, so
    SQLAlchemy sees the change)."""
    return [dict(w) for w in words]


async def _load_transcript(audio_id: UUID) -> list[Word] | None:
    async with _session_maker() as session:
        transcript = await session.get(AudioTranscript, audio_id)
        return [Word(**w) for w in transcript.words] if transcript else None  # type: ignore[typeddict-item]


# --- recovery ------------------------------------------------------------------------------


@celery_app.task(name=RECOVER_TASK)
def recover_stuck_jobs() -> int:
    """Queue again the steps that no worker will otherwise run.

    Run every few minutes by the beat service. Covers a step whose message
    never reached Redis or was lost (including the next step of a chain, if
    the worker died between steps), and a step whose worker died without
    Celery delivering it again. Each job is queued from its next step.
    Returns how many jobs were queued.
    """
    stuck = asyncio.run(_find_stuck_jobs())
    for audio_id, stage in stuck:
        enqueue_censor(audio_id, after=stage)
    if stuck:
        logger.warning("Queued %d stuck job(s) again: %s", len(stuck), stuck)
    return len(stuck)


async def _find_stuck_jobs() -> list[tuple[UUID, JobStage | None]]:
    """Stuck jobs and their stage, marked as just queued (so they aren't
    picked up again on the next run while their new message waits)."""
    now = utc_now()
    waiting_before = now - timedelta(
        minutes=get_worker_settings().PENDING_REQUEUE_AFTER_MINUTES
    )
    running_before = now - timedelta(seconds=settings.stale_processing_seconds)
    unfinished = col(AudioFile.status).in_((AudioStatus.PENDING, AudioStatus.PROCESSING))
    async with _session_maker() as session:
        result = await session.exec(
            select(AudioFile)
            .where(
                unfinished,
                or_(
                    # Waiting for a step no task has picked up: the message
                    # is lost. "Waiting since" is the later of when it was
                    # queued and when the previous step finished.
                    col(AudioFile.task_id).is_(None)
                    & (
                        func.greatest(
                            func.coalesce(AudioFile.queued_at, AudioFile.created_at),
                            AudioFile.updated_at,
                        )
                        < waiting_before
                    ),
                    # A step running far longer than allowed: its worker died.
                    col(AudioFile.task_id).is_not(None)
                    & (func.coalesce(AudioFile.started_at, AudioFile.created_at) < running_before)
                    & (func.coalesce(AudioFile.queued_at, AudioFile.created_at) < running_before),
                ),
            )
            # Skip rows a worker is claiming right now; next run gets them.
            .with_for_update(skip_locked=True)
        )
        records = list(result.all())
        stuck = [(record.id, record.stage) for record in records]
        for record in records:
            record.queued_at = now
            session.add(record)
        await session.commit()
        return stuck
