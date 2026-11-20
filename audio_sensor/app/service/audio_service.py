import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import BinaryIO, Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, tuple_
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.audio_probe import header_duration
from app.censor_words import normalize_custom_words
from app.config import get_api_settings, settings
from app.database.models import (
    AudioFile,
    AudioStatus,
    AudioTranscript,
    CensorMode,
    JobStage,
    SoundEffect,
    User,
    utc_now,
)

# One error type for "no such sound effect" across both services.
from app.service.sound_effect_service import SoundEffectNotFoundError
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


class EnqueueCensor(Protocol):
    """Queues a job's censor steps after `after` (all of them for None); the
    job's options are on its record. In the app this is
    app.worker.celery_app.enqueue_censor; tests pass a fake."""

    def __call__(self, audio_id: UUID, after: JobStage | None = None) -> None: ...


MAX_PADDING_MS = 1000
def _check_padding(padding_ms: int) -> None:
    if not 0 <= padding_ms <= MAX_PADDING_MS:
        raise InvalidSettingsError(f"padding_ms must be between 0 and {MAX_PADDING_MS}")


# Pipeline order of JobStage (None: nothing done yet), to compare stages.
_STAGE_ORDER: dict[JobStage | None, int] = {None: 0} | {
    stage: i + 1 for i, stage in enumerate(JobStage)
}


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


class AudioTooLongError(ValueError):
    """The upload's headers declare more than MAX_AUDIO_MINUTES of audio."""

    def __init__(self, minutes: float):
        self.minutes = minutes
        super().__init__(
            f"The audio is {minutes:.0f} minutes long; at most "
            f"{settings.MAX_AUDIO_MINUTES} minutes are accepted"
        )


class TranscriptNotAvailableError(LookupError):
    """The job has no stored transcript: not transcribed yet (`pending` is
    True), or never will be (failed before transcription, or ran before
    transcripts were kept)."""

    def __init__(self, record: AudioFile):
        self.pending = record.status in (AudioStatus.PENDING, AudioStatus.PROCESSING)
        super().__init__(
            f"Audio {record.id} hasn't been transcribed yet; try again shortly"
            if self.pending
            else f"Audio {record.id} has no transcript"
        )


class QueueUnavailableError(RuntimeError):
    """The censor job could not be queued (Redis is unreachable)."""


class TooManyActiveJobsError(RuntimeError):
    """The user already has the maximum number of jobs pending or processing."""

    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f"You already have {limit} audio files being censored")


class JobBusyError(RuntimeError):
    """The job is still pending or processing, so its settings can't change yet."""


class RerunNotPossibleError(RuntimeError):
    """The job has no stored transcript to re-run from: it failed before
    transcription finished, or ran before transcripts were kept."""


class InvalidSettingsError(ValueError):
    """Censor settings that don't fit together (e.g. sound_effect mode
    without a sound effect). Bad custom words raise InvalidCustomWordsError."""


ACTIVE_STATUSES = (AudioStatus.PENDING, AudioStatus.PROCESSING)

# update_settings() refusals (raised before anything is changed).
_REFUSALS = (
    JobBusyError,
    RerunNotPossibleError,
    InvalidSettingsError,
    SoundEffectNotFoundError,
    TooManyActiveJobsError,
)

# What update_settings() snapshots, to put back if queuing fails.
_RERUN_FIELDS = (
    "custom_words",
    "censor_mode",
    "sound_effect_id",
    "padding_ms",
    "stage",
    "status",
    "error",
    "task_id",
    "attempts",
    "queued_at",
    "finished_at",
)


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
        censor_mode: CensorMode = CensorMode.MUTE,
        custom_words: Sequence[str] = (),
        sound_effect_id: UUID | None = None,
    ) -> AudioFile:
        """Save the upload as a PENDING record of `owner_id` and queue its job.

        `custom_words` are censored on top of the built-in list (validated by
        normalize_custom_words); `sound_effect_id` (the user's own effect or
        a built-in one) goes with censor_mode SOUND_EFFECT.

        Returns straight away; the worker censors the file and moves the
        record to COMPLETED or FAILED. Nothing is kept unless the file, the
        row and the queued job all succeed. The settings are checked before
        anything is stored. Raises InvalidCustomWordsError,
        InvalidSettingsError and SoundEffectNotFoundError for bad settings,
        TooManyActiveJobsError if the user already has the maximum number of
        jobs in progress, UploadTooLargeError if the upload exceeds the size
        limit, and QueueUnavailableError if the job can't be queued.
        """
        words = list(normalize_custom_words(custom_words))
        _check_padding(padding_ms)
        effect_id = await self._resolve_effect(censor_mode, sound_effect_id, owner_id)
        in_suffix = input_suffix(filename)
        # Refuse obviously long files now. Headers can be missing (unknown
        # format) or lie, so the worker enforces the limit again on decode.
        duration = await asyncio.to_thread(header_duration, data, in_suffix)
        if duration is not None and duration > settings.MAX_AUDIO_MINUTES * 60:
            raise AudioTooLongError(duration / 60)
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
                censor_mode=censor_mode,
                sound_effect_id=effect_id,
                custom_words=words,
                queued_at=utc_now(),
            )
            self.session.add(record)
            try:
                await self.session.commit()
            except IntegrityError as exc:
                # The only reference that can vanish in between: the sound
                # effect, deleted since it was checked above.
                raise SoundEffectNotFoundError(
                    f"No sound effect with id {sound_effect_id}"
                ) from exc
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

    async def update_settings(
        self,
        audio_id: UUID,
        owner_id: UUID,
        *,
        custom_words: Sequence[str] | None = None,
        censor_mode: CensorMode | None = None,
        sound_effect_id: UUID | None = None,
        padding_ms: int | None = None,
    ) -> AudioFile:
        """Change a finished job's censor settings and re-run only the steps
        they affect. Arguments left as None keep their current value.

        New custom words re-run detection and rendering; the stored
        transcript is reused, so nothing is transcribed again. A new censor
        mode, sound effect or padding re-runs rendering only. A job that
        failed part-way re-runs from wherever it stopped, if that's earlier.
        If nothing actually changes, nothing is queued and the record is
        returned as it is. Otherwise it comes back PENDING, like a new
        upload; switching away from the sound_effect mode clears the effect.

        Raises AudioNotFoundError (not the user's job), JobBusyError (still
        pending or processing), RerunNotPossibleError (no stored transcript),
        InvalidCustomWordsError, InvalidSettingsError,
        SoundEffectNotFoundError, TooManyActiveJobsError, and
        QueueUnavailableError (the job is then left exactly as it was).
        """
        # Validate the input before locking anything.
        new_words = (
            list(normalize_custom_words(custom_words)) if custom_words is not None else None
        )
        if padding_ms is not None:
            _check_padding(padding_ms)

        # Lock the user's row first, as submit_upload does (the active-jobs
        # cap), then the job's: the same order everywhere, so no deadlocks.
        await self.session.exec(select(User).where(User.id == owner_id).with_for_update())
        record = (
            await self.session.exec(
                select(AudioFile)
                .where(AudioFile.id == audio_id, AudioFile.user_id == owner_id)
                .with_for_update()
            )
        ).first()
        if record is None:
            await self.session.commit()  # release the lock
            raise AudioNotFoundError(f"No audio with id {audio_id}")
        # Before _plan_rerun applies the changes: what to put back if queuing fails.
        previous = {name: getattr(record, name) for name in _RERUN_FIELDS}
        try:
            after = await self._plan_rerun(
                record, owner_id, new_words, censor_mode, sound_effect_id, padding_ms
            )
        except _REFUSALS:
            # Nothing was changed yet: commit() just releases the locks
            # (rollback() would also expire the already-loaded user).
            await self.session.commit()
            raise
        except BaseException:
            await self.session.rollback()
            raise
        if after is None:  # nothing changed
            await self.session.commit()  # release the locks
            return record

        record.stage = after
        record.status = AudioStatus.PENDING
        record.error = None
        record.task_id = None
        record.attempts = 0
        record.queued_at = utc_now()
        record.finished_at = None
        self.session.add(record)
        effect_id = record.sound_effect_id  # read now: rollback() expires the record
        try:
            await self.session.commit()
        except IntegrityError as exc:
            # The only reference that can vanish in between: the sound effect,
            # deleted since _plan_rerun checked it. Nothing was saved.
            await self.session.rollback()
            raise SoundEffectNotFoundError(f"No sound effect with id {effect_id}") from exc

        try:
            await asyncio.to_thread(self.enqueue_censor, audio_id, after)
        except Exception as exc:
            # Nothing will run: put the job back as it was.
            for name, value in previous.items():
                setattr(record, name, value)
            self.session.add(record)
            await self.session.commit()
            raise QueueUnavailableError("Could not queue the censor steps") from exc
        return record

    async def _plan_rerun(
        self,
        record: AudioFile,
        owner_id: UUID,
        new_words: list[str] | None,
        censor_mode: CensorMode | None,
        sound_effect_id: UUID | None,
        padding_ms: int | None,
    ) -> JobStage | None:
        """Apply the changes to `record` (not committed) and return the stage
        to re-run after, or None if nothing changes."""
        if record.status in ACTIVE_STATUSES:
            raise JobBusyError(f"Audio {record.id} is still {record.status}")

        mode = censor_mode or CensorMode(record.censor_mode)
        # Keep the job's current effect if the mode stays sound_effect and no
        # new one is given; any other mode drops it.
        if sound_effect_id is None and mode == CensorMode.SOUND_EFFECT:
            sound_effect_id = record.sound_effect_id
            if sound_effect_id is None and record.censor_mode == CensorMode.SOUND_EFFECT:
                # It had one: deleting an effect clears it from its jobs.
                raise InvalidSettingsError(
                    "This job's sound effect was deleted: choose another one "
                    "(sound_effect_id) or another censor_mode"
                )
        effect_id = await self._resolve_effect(mode, sound_effect_id, owner_id)

        words_changed = new_words is not None and new_words != list(record.custom_words)
        render_changed = (
            mode != record.censor_mode
            or effect_id != record.sound_effect_id
            or (padding_ms is not None and padding_ms != record.padding_ms)
        )
        if not words_changed and not render_changed:
            return None

        after = JobStage.TRANSCRIBED if words_changed else JobStage.DETECTED
        # A job that failed part-way may not have reached `after`.
        if _STAGE_ORDER[record.stage] < _STAGE_ORDER[after]:
            after = record.stage  # type: ignore[assignment]
        if after is None or not await self._has_transcript(record.id):
            raise RerunNotPossibleError(
                f"Audio {record.id} has no stored transcript to re-run from"
            )
        # Re-running uses the worker like a new upload does.
        await self._check_active_jobs(owner_id, lock=False)  # user row already locked

        if new_words is not None:
            record.custom_words = new_words
        record.censor_mode = mode
        record.sound_effect_id = effect_id
        if padding_ms is not None:
            record.padding_ms = padding_ms
        return after

    async def _resolve_effect(
        self, mode: CensorMode, effect_id: UUID | None, owner_id: UUID
    ) -> UUID | None:
        """The sound effect to store with `mode`: required (and the user's own
        or built in) for SOUND_EFFECT, not allowed with any other mode."""
        if mode != CensorMode.SOUND_EFFECT:
            if effect_id is not None:
                raise InvalidSettingsError(
                    "A sound effect only applies with censor_mode sound_effect"
                )
            return None
        if effect_id is None:
            raise InvalidSettingsError("Choose a sound effect for censor_mode sound_effect")
        await self._check_sound_effect(effect_id, owner_id)
        return effect_id

    async def _check_sound_effect(self, effect_id: UUID, owner_id: UUID) -> None:
        """Raise SoundEffectNotFoundError unless the effect is the user's own
        or built in (no owner)."""
        found = await self.session.scalar(
            select(SoundEffect.id).where(
                SoundEffect.id == effect_id,
                or_(col(SoundEffect.user_id) == owner_id, col(SoundEffect.user_id).is_(None)),
            )
        )
        if found is None:
            raise SoundEffectNotFoundError(f"No sound effect with id {effect_id}")

    async def _has_transcript(self, audio_id: UUID) -> bool:
        # Selects only the key, not the (possibly large) words.
        found = await self.session.scalar(
            select(AudioTranscript.audio_id).where(AudioTranscript.audio_id == audio_id)
        )
        return found is not None

    async def get_transcript(self, audio_id: UUID, owner_id: UUID) -> AudioTranscript:
        """The job's word-level transcript (with each word's "flagged" once
        detection has run). Raises AudioNotFoundError, or
        TranscriptNotAvailableError if there is none (yet)."""
        record = await self.get_audio(audio_id, owner_id)
        transcript = await self.session.get(AudioTranscript, audio_id)
        if transcript is None:
            raise TranscriptNotAvailableError(record)
        return transcript

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
