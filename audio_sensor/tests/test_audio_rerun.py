"""AudioService.update_settings: change a finished job's settings and re-run
only the steps the change affects."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest

from app.censor_words import InvalidCustomWordsError
from app.config import get_api_settings
from app.database.models import AudioFile, AudioStatus, CensorMode, JobStage, utc_now
from app.database.session import async_session_maker
from app.service.audio_service import (
    AudioNotFoundError,
    AudioService,
    InvalidSettingsError,
    JobBusyError,
    QueueUnavailableError,
    RerunNotPossibleError,
    SoundEffectNotFoundError,
    TooManyActiveJobsError,
)
from tests.helpers import (
    AppUser,
    FakeQueue,
    MakeUser,
    get_audio_row,
    make_audio,
    make_sound_effect,
    make_transcript,
)

WORDS = [
    {"word": "hello", "start": 0.0, "end": 0.4, "flagged": False},
    {"word": "darn", "start": 0.5, "end": 0.9, "flagged": True},
]


@pytest.fixture
async def service(queue: FakeQueue) -> AsyncIterator[AudioService]:
    async with async_session_maker() as session:
        yield AudioService(session, queue)


async def finished_job(user: AppUser, **fields: Any) -> AudioFile:
    """A completed job with a stored transcript (what update_settings needs)."""
    fields = {
        "stage": JobStage.RENDERED,
        "finished_at": utc_now() - timedelta(minutes=5),
        "words_count": 2,
        "flagged_count": 1,
        "attempts": 0,
    } | fields
    record = await make_audio(user.id, fields.pop("status", AudioStatus.COMPLETED), **fields)
    await make_transcript(record.id, WORDS)
    return record


async def row(audio_id) -> AudioFile:
    record = await get_audio_row(audio_id)
    assert record is not None
    return record


# --- what gets re-run ----------------------------------------------------------------


async def test_new_custom_words_rerun_detection_and_rendering(
    service: AudioService, queue: FakeQueue, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await finished_job(user)

    result = await service.update_settings(record.id, user.id, custom_words=["Banana", " heck "])

    assert queue.jobs == [record.id] and queue.after == [JobStage.TRANSCRIBED]
    after = await row(record.id)
    assert after.custom_words == ["banana", "heck"]  # normalized
    assert (after.stage, after.status) == (JobStage.TRANSCRIBED, AudioStatus.PENDING)
    assert (after.error, after.task_id, after.attempts, after.finished_at) == (None, None, 0, None)
    assert after.queued_at is not None and after.queued_at > record.created_at
    assert result.status == AudioStatus.PENDING


async def test_render_settings_rerun_rendering_only(
    service: AudioService, queue: FakeQueue, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await finished_job(user)

    await service.update_settings(record.id, user.id, censor_mode=CensorMode.BEEP, padding_ms=300)

    assert queue.after == [JobStage.DETECTED]
    after = await row(record.id)
    assert (after.censor_mode, after.padding_ms, after.stage) == (
        CensorMode.BEEP, 300, JobStage.DETECTED,
    )


async def test_words_and_render_settings_together_start_from_detection(
    service: AudioService, queue: FakeQueue, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await finished_job(user)

    await service.update_settings(
        record.id, user.id, custom_words=["banana"], censor_mode=CensorMode.BEEP
    )

    assert queue.after == [JobStage.TRANSCRIBED]


async def test_unchanged_settings_queue_nothing(
    service: AudioService, queue: FakeQueue, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await finished_job(user, custom_words=["banana"], censor_mode=CensorMode.BEEP)

    # Same words (other case and spacing), same mode, same padding.
    await service.update_settings(
        record.id,
        user.id,
        custom_words=[" BANANA "],
        censor_mode=CensorMode.BEEP,
        padding_ms=record.padding_ms,
    )
    await service.update_settings(record.id, user.id)  # nothing given at all

    assert queue.jobs == []
    after = await row(record.id)
    assert (after.status, after.stage) == (AudioStatus.COMPLETED, JobStage.RENDERED)


async def test_clearing_custom_words_is_a_change(
    service: AudioService, queue: FakeQueue, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await finished_job(user, custom_words=["banana"])

    await service.update_settings(record.id, user.id, custom_words=[])

    assert queue.after == [JobStage.TRANSCRIBED]
    assert (await row(record.id)).custom_words == []


async def test_failed_job_reruns_from_where_it_stopped(
    service: AudioService, queue: FakeQueue, make_user: MakeUser
) -> None:
    """Detection failed: even a render-only change must detect first."""
    user = await make_user()
    record = await finished_job(
        user, status=AudioStatus.FAILED, stage=JobStage.TRANSCRIBED, error="boom"
    )

    await service.update_settings(record.id, user.id, censor_mode=CensorMode.BEEP)

    assert queue.after == [JobStage.TRANSCRIBED]
    after = await row(record.id)
    assert (after.status, after.error) == (AudioStatus.PENDING, None)


async def test_job_failed_for_a_missing_effect_can_get_a_new_one(
    service: AudioService, queue: FakeQueue, make_user: MakeUser
) -> None:
    user = await make_user()
    effect = await make_sound_effect(user.id)
    record = await finished_job(
        user,
        status=AudioStatus.FAILED,
        stage=JobStage.DETECTED,
        censor_mode=CensorMode.SOUND_EFFECT,
        error="The chosen sound effect no longer exists.",
    )

    await service.update_settings(record.id, user.id, sound_effect_id=effect.id)

    assert queue.after == [JobStage.DETECTED]
    assert (await row(record.id)).sound_effect_id == effect.id


# --- sound effects ---------------------------------------------------------------------


async def test_sound_effect_must_be_the_users_own_or_built_in(
    service: AudioService, queue: FakeQueue, make_user: MakeUser
) -> None:
    user, other = await make_user(), await make_user()
    record = await finished_job(user)
    others_effect = await make_sound_effect(other.id)
    built_in = await make_sound_effect(None, name="classic")

    with pytest.raises(SoundEffectNotFoundError):
        await service.update_settings(
            record.id, user.id, censor_mode=CensorMode.SOUND_EFFECT, sound_effect_id=others_effect.id
        )
    await service.update_settings(
        record.id, user.id, censor_mode=CensorMode.SOUND_EFFECT, sound_effect_id=built_in.id
    )
    assert queue.after == [JobStage.DETECTED]


async def test_switching_away_from_a_sound_effect_clears_it(
    service: AudioService, make_user: MakeUser
) -> None:
    user = await make_user()
    effect = await make_sound_effect(user.id)
    record = await finished_job(
        user, censor_mode=CensorMode.SOUND_EFFECT, sound_effect_id=effect.id
    )

    await service.update_settings(record.id, user.id, censor_mode=CensorMode.MUTE)

    assert (await row(record.id)).sound_effect_id is None


@pytest.mark.parametrize(
    "changes",
    [
        {"censor_mode": CensorMode.SOUND_EFFECT},  # no effect chosen
        {"censor_mode": CensorMode.BEEP, "sound_effect_id": "any"},  # effect without its mode
        {"padding_ms": 1001},
        {"padding_ms": -1},
    ],
    ids=["effect-mode-without-effect", "effect-without-mode", "padding-high", "padding-low"],
)
async def test_settings_that_dont_fit_are_refused(
    service: AudioService, queue: FakeQueue, make_user: MakeUser, changes: dict
) -> None:
    user = await make_user()
    record = await finished_job(user)
    if changes.get("sound_effect_id") == "any":
        changes["sound_effect_id"] = (await make_sound_effect(user.id)).id

    with pytest.raises(InvalidSettingsError):
        await service.update_settings(record.id, user.id, **changes)
    assert queue.jobs == []


# --- refusals --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [AudioStatus.PENDING, AudioStatus.PROCESSING])
async def test_busy_job_is_refused(
    service: AudioService, queue: FakeQueue, make_user: MakeUser, status: AudioStatus
) -> None:
    user = await make_user()
    record = await finished_job(user, status=status, stage=JobStage.TRANSCRIBED)

    with pytest.raises(JobBusyError):
        await service.update_settings(record.id, user.id, custom_words=["banana"])
    assert queue.jobs == []


async def test_job_without_a_transcript_cannot_rerun(
    service: AudioService, queue: FakeQueue, make_user: MakeUser
) -> None:
    """E.g. jobs that ran before transcripts were stored."""
    user = await make_user()
    record = await make_audio(user.id, AudioStatus.COMPLETED, stage=JobStage.RENDERED)

    with pytest.raises(RerunNotPossibleError):
        await service.update_settings(record.id, user.id, custom_words=["banana"])
    after = await row(record.id)
    assert (after.status, after.custom_words) == (AudioStatus.COMPLETED, [])  # unchanged


async def test_job_that_failed_before_transcription_cannot_rerun(
    service: AudioService, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await make_audio(user.id, AudioStatus.FAILED, stage=None, error="bad audio")

    with pytest.raises(RerunNotPossibleError):
        await service.update_settings(record.id, user.id, censor_mode=CensorMode.BEEP)


async def test_other_users_job_is_not_found(service: AudioService, make_user: MakeUser) -> None:
    owner, other = await make_user(), await make_user()
    record = await finished_job(owner)

    with pytest.raises(AudioNotFoundError):
        await service.update_settings(record.id, other.id, custom_words=["banana"])


async def test_bad_custom_words_are_refused(service: AudioService, make_user: MakeUser) -> None:
    user = await make_user()
    record = await finished_job(user)

    with pytest.raises(InvalidCustomWordsError):
        await service.update_settings(record.id, user.id, custom_words=["ice cream"])


async def test_rerun_counts_toward_the_active_jobs_cap(
    service: AudioService, queue: FakeQueue, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_api_settings(), "MAX_ACTIVE_JOBS_PER_USER", 1)
    user = await make_user()
    service.max_active_jobs = 1
    record = await finished_job(user)
    await make_audio(user.id)  # another job is already running

    with pytest.raises(TooManyActiveJobsError):
        await service.update_settings(record.id, user.id, custom_words=["banana"])
    assert queue.jobs == []


async def test_queue_down_leaves_the_job_as_it_was(
    service: AudioService, queue: FakeQueue, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await finished_job(user)
    queue.available = False

    with pytest.raises(QueueUnavailableError):
        await service.update_settings(record.id, user.id, custom_words=["banana"])

    after = await row(record.id)
    assert (after.status, after.stage, after.custom_words) == (
        AudioStatus.COMPLETED, JobStage.RENDERED, [],
    )
    assert after.finished_at == record.finished_at


async def test_session_stays_usable_after_a_refusal(
    service: AudioService, make_user: MakeUser
) -> None:
    """Refusals release the locks without expiring loaded objects (the API's
    request still holds the logged-in user)."""
    from app.database.models import User

    user = await make_user()
    record = await finished_job(user, status=AudioStatus.PROCESSING, stage=JobStage.TRANSCRIBED)
    loaded = await service.session.get(User, user.id)
    assert loaded is not None

    with pytest.raises(JobBusyError):
        await service.update_settings(record.id, user.id, custom_words=["banana"])

    assert loaded.email == user.email  # still loaded, no lazy reload
    assert not service.session.in_transaction()  # locks released
