"""The three Celery steps (transcribe, detect, render), run in-process (no
broker), with a fake AudioCensor.

These tests are synchronous because the tasks run their own event loops
(asyncio.run), exactly as they do inside the worker.
"""

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from app.audio_censor import AudioDecodeError, SoundEffectError, Word
from app.config import get_worker_settings, settings
from app.database.models import AudioStatus, CensorMode, JobStage, utc_now
from app.storage import censored_key, get_storage
from app.worker import celery_app as celery_module
from app.worker import tasks
from tests.helpers import (
    AppUser,
    get_audio_row,
    get_transcript_words,
    make_audio,
    make_sound_effect,
    make_transcript,
    read_stored,
    update_audio_row,
)


class FakeCensor:
    """Stands in for AudioCensor's three step methods, recording each call."""

    def __init__(self) -> None:
        self.transcript: list[Word] = [
            Word(word="hello", start=0.0, end=0.4),
            Word(word="darn", start=0.5, end=0.9),
            Word(word="it"),
        ]
        self.profane = {"darn"}
        self.errors: dict[str, BaseException] = {}  # step -> error to raise
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def transcribe_audio(self, audio_path: str, max_seconds: float | None = None) -> list[Word]:
        self.calls.append(
            ("transcribe", {"audio": Path(audio_path).read_bytes(), "max_seconds": max_seconds})
        )
        if "transcribe" in self.errors:
            raise self.errors["transcribe"]
        return [Word(**w) for w in self.transcript]  # type: ignore[typeddict-item]

    def detect_profanity(self, words: list[Word], custom_words=None) -> list[Word]:
        self.calls.append(("detect", {"custom_words": list(custom_words or [])}))
        if "detect" in self.errors:
            raise self.errors["detect"]
        bad = self.profane | set(custom_words or [])
        for word in words:
            word["flagged"] = word["word"] in bad
        return words

    def render_audio(
        self, audio_path, words, output_path, padding_ms, beep, sound_effect_path, copy_unchanged
    ):
        effect = Path(sound_effect_path).read_bytes() if sound_effect_path else None
        self.calls.append(
            ("render", {"padding_ms": padding_ms, "beep": beep, "effect": effect})
        )
        if "render" in self.errors:
            Path(output_path).write_bytes(b"partial")  # must be discarded
            raise self.errors["render"]
        flagged = [w["word"] for w in words if w.get("flagged")]
        if not flagged and not copy_unchanged:
            return None
        marker = ",".join(flagged).encode()
        Path(output_path).write_bytes(b"censored[" + marker + b"]:" + Path(audio_path).read_bytes())
        return output_path

    def steps(self) -> list[str]:
        return [name for name, _ in self.calls]

    def last(self, step: str) -> dict[str, Any]:
        return [args for name, args in self.calls if name == step][-1]


@pytest.fixture
def censor(monkeypatch: pytest.MonkeyPatch) -> FakeCensor:
    fake = FakeCensor()
    monkeypatch.setattr(tasks, "get_censor", lambda: fake)
    return fake


@pytest.fixture
def requeued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[UUID, JobStage | None]]:
    """Jobs recover_stuck_jobs puts back on the queue, with their stage."""
    sent: list[tuple[UUID, JobStage | None]] = []
    monkeypatch.setattr(tasks, "enqueue_censor", lambda audio_id, after=None: sent.append((audio_id, after)))
    return sent


@pytest.fixture
def user(make_user) -> AppUser:
    return asyncio.run(make_user())


STEPS = {
    "transcribe": tasks.transcribe_audio_task,
    "detect": tasks.detect_profanity_task,
    "render": tasks.render_audio_task,
}


def run(step: str, audio_id: UUID, task_id: str | None = None) -> None:
    """Run one step as a worker would, with a Celery task id."""
    cast(Task, STEPS[step]).apply(args=[audio_id], task_id=task_id or f"{step}-task", throw=True)


def run_all(audio_id: UUID) -> None:
    for step in STEPS:
        run(step, audio_id)


def row(audio_id: UUID):
    record = asyncio.run(get_audio_row(audio_id))
    assert record is not None
    return record


def transcript(audio_id: UUID) -> list[dict] | None:
    return asyncio.run(get_transcript_words(audio_id))


# --- the pipeline -----------------------------------------------------------------


def test_full_pipeline(censor: FakeCensor, user: AppUser) -> None:
    record = asyncio.run(
        make_audio(user.id, original=b"song", padding_ms=300, censor_mode=CensorMode.BEEP)
    )

    run_all(record.id)

    done = row(record.id)
    assert (done.status, done.stage) == (AudioStatus.COMPLETED, JobStage.RENDERED)
    assert (done.words_count, done.flagged_count) == (3, 1)
    assert done.finished_at is not None and done.error is None
    assert (done.task_id, done.attempts) == (None, 0)
    assert censor.steps() == ["transcribe", "detect", "render"]
    assert censor.last("render") == {"padding_ms": 300, "beep": True, "effect": None}
    # The transcript is stored, with the flags from detection.
    assert [(w["word"], w["flagged"]) for w in transcript(record.id) or []] == [
        ("hello", False), ("darn", True), ("it", False),
    ]
    assert done.censored_file_path == censored_key(record.id, ".mp3")
    assert read_stored(done.censored_file_path) == b"censored[darn]:song"


def test_each_step_runs_on_its_own(censor: FakeCensor, user: AppUser) -> None:
    record = asyncio.run(make_audio(user.id))

    run("transcribe", record.id)
    after = row(record.id)
    assert (after.status, after.stage, after.words_count) == (
        AudioStatus.PROCESSING, JobStage.TRANSCRIBED, 3,
    )
    assert after.flagged_count is None
    assert not any("flagged" in w for w in transcript(record.id) or [])

    run("detect", record.id)
    after = row(record.id)
    assert (after.status, after.stage, after.flagged_count) == (
        AudioStatus.PROCESSING, JobStage.DETECTED, 1,
    )
    assert read_stored(after.censored_file_path) is None  # not rendered yet

    run("render", record.id)
    assert row(record.id).status == AudioStatus.COMPLETED


def test_steps_wait_for_the_step_before(censor: FakeCensor, user: AppUser) -> None:
    record = asyncio.run(make_audio(user.id))

    run("detect", record.id)
    run("render", record.id)

    assert censor.calls == []
    still = row(record.id)
    assert (still.status, still.stage) == (AudioStatus.PENDING, None)


def test_a_finished_step_is_not_run_again(censor: FakeCensor, user: AppUser) -> None:
    record = asyncio.run(make_audio(user.id))
    run_all(record.id)

    run_all(record.id)  # e.g. a duplicate chain

    assert censor.steps() == ["transcribe", "detect", "render"]
    assert row(record.id).status == AudioStatus.COMPLETED


def test_detection_uses_the_jobs_custom_words(censor: FakeCensor, user: AppUser) -> None:
    record = asyncio.run(make_audio(user.id, custom_words=["hello"]))

    run_all(record.id)

    assert censor.last("detect") == {"custom_words": ["hello"]}
    assert row(record.id).flagged_count == 2


# --- running steps again ------------------------------------------------------------


def test_detect_and_render_again_with_new_words(censor: FakeCensor, user: AppUser) -> None:
    record = asyncio.run(make_audio(user.id, original=b"song"))
    run_all(record.id)
    assert row(record.id).flagged_count == 1

    # The user adds a custom word: run from detection, without re-transcribing.
    asyncio.run(update_audio_row(record.id, custom_words=["hello"], stage=JobStage.TRANSCRIBED))
    run("detect", record.id, task_id="detect-again")
    run("render", record.id, task_id="render-again")

    again = row(record.id)
    assert censor.steps().count("transcribe") == 1
    assert (again.status, again.flagged_count) == (AudioStatus.COMPLETED, 2)
    assert read_stored(again.censored_file_path) == b"censored[hello,darn]:song"


def test_render_again_with_another_mode(censor: FakeCensor, user: AppUser) -> None:
    record = asyncio.run(make_audio(user.id))
    run_all(record.id)

    asyncio.run(update_audio_row(record.id, censor_mode=CensorMode.BEEP, stage=JobStage.DETECTED))
    run("render", record.id, task_id="render-again")

    assert censor.steps() == ["transcribe", "detect", "render", "render"]
    assert censor.last("render")["beep"] is True
    assert row(record.id).status == AudioStatus.COMPLETED


def test_clean_job_reuses_the_upload_and_a_rerender_never_overwrites_it(
    censor: FakeCensor, user: AppUser
) -> None:
    censor.profane = set()
    record = asyncio.run(make_audio(user.id, original=b"clean song"))
    run_all(record.id)
    clean = row(record.id)
    assert clean.censored_file_path == clean.file_path  # one stored file
    assert read_stored(censored_key(record.id, ".mp3")) is None

    # Now something is censored: the output must go to its own key, not over
    # the upload that censored_file_path currently points at.
    asyncio.run(update_audio_row(record.id, custom_words=["hello"], stage=JobStage.TRANSCRIBED))
    run("detect", record.id, task_id="d2")
    run("render", record.id, task_id="r2")

    censored = row(record.id)
    assert censored.censored_file_path == censored_key(record.id, ".mp3")
    assert read_stored(censored.file_path) == b"clean song"  # upload intact
    assert read_stored(censored.censored_file_path) == b"censored[hello]:clean song"


def test_rerender_with_nothing_censored_removes_the_old_censored_file(
    censor: FakeCensor, user: AppUser
) -> None:
    record = asyncio.run(make_audio(user.id, original=b"song"))
    run_all(record.id)
    old = row(record.id).censored_file_path
    assert read_stored(old) is not None

    censor.profane = set()
    asyncio.run(update_audio_row(record.id, stage=JobStage.TRANSCRIBED))
    run("detect", record.id, task_id="d2")
    run("render", record.id, task_id="r2")

    after = row(record.id)
    assert after.censored_file_path == after.file_path
    assert read_stored(old) is None  # no orphaned file
    assert read_stored(after.file_path) == b"song"


# --- sound effects ----------------------------------------------------------------------


def test_sound_effect_is_passed_to_rendering(censor: FakeCensor, user: AppUser) -> None:
    effect = asyncio.run(make_sound_effect(user.id, b"honk"))
    record = asyncio.run(
        make_audio(user.id, censor_mode=CensorMode.SOUND_EFFECT, sound_effect_id=effect.id)
    )

    run_all(record.id)

    assert censor.last("render")["effect"] == b"honk"
    assert censor.last("render")["beep"] is False
    assert row(record.id).status == AudioStatus.COMPLETED


def test_deleted_sound_effect_fails_the_job(censor: FakeCensor, user: AppUser) -> None:
    record = asyncio.run(make_audio(user.id, censor_mode=CensorMode.SOUND_EFFECT))  # id NULL

    run_all(record.id)

    failed = row(record.id)
    assert (failed.status, failed.error) == (AudioStatus.FAILED, tasks.SOUND_EFFECT_MISSING_ERROR)
    assert censor.steps() == ["transcribe", "detect"]


def test_sound_effect_file_gone_from_storage_fails_the_job(
    censor: FakeCensor, user: AppUser
) -> None:
    effect = asyncio.run(make_sound_effect(user.id))
    get_storage().delete(effect.file_path)
    record = asyncio.run(
        make_audio(user.id, censor_mode=CensorMode.SOUND_EFFECT, sound_effect_id=effect.id)
    )

    run_all(record.id)

    assert row(record.id).error == tasks.SOUND_EFFECT_MISSING_ERROR


def test_unreadable_sound_effect_fails_the_job(censor: FakeCensor, user: AppUser) -> None:
    censor.errors["render"] = SoundEffectError("bad")
    effect = asyncio.run(make_sound_effect(user.id))
    record = asyncio.run(
        make_audio(user.id, censor_mode=CensorMode.SOUND_EFFECT, sound_effect_id=effect.id)
    )

    run_all(record.id)

    failed = row(record.id)
    assert failed.error == tasks.SOUND_EFFECT_ERROR
    assert read_stored(censored_key(record.id, ".mp3")) is None  # partial output discarded


# --- failures ------------------------------------------------------------------------


def test_undecodable_upload_fails_and_later_steps_skip(censor: FakeCensor, user: AppUser) -> None:
    censor.errors["transcribe"] = AudioDecodeError("bad")
    record = asyncio.run(make_audio(user.id))

    run_all(record.id)  # handled: no exception

    failed = row(record.id)
    assert (failed.status, failed.error) == (AudioStatus.FAILED, tasks.DECODE_ERROR)
    assert censor.steps() == ["transcribe"]
    assert transcript(record.id) is None


def test_render_over_time_limit_fails(censor: FakeCensor, user: AppUser) -> None:
    censor.errors["render"] = SoftTimeLimitExceeded()
    record = asyncio.run(make_audio(user.id))

    run_all(record.id)

    failed = row(record.id)
    assert (failed.status, failed.error) == (AudioStatus.FAILED, tasks.TIMEOUT_ERROR)
    assert read_stored(censored_key(record.id, ".mp3")) is None  # partial output discarded


def test_unexpected_error_fails_job_and_reraises(censor: FakeCensor, user: AppUser) -> None:
    censor.errors["detect"] = RuntimeError("detector crashed")
    record = asyncio.run(make_audio(user.id))
    run("transcribe", record.id)

    with pytest.raises(RuntimeError, match="detector crashed"):
        run("detect", record.id)

    failed = row(record.id)
    assert (failed.status, failed.error) == (AudioStatus.FAILED, tasks.UNEXPECTED_ERROR)


def test_missing_upload_fails_job(censor: FakeCensor, user: AppUser) -> None:
    record = asyncio.run(make_audio(user.id))
    get_storage().delete(record.file_path)

    run("transcribe", record.id)

    assert row(record.id).error == tasks.MISSING_UPLOAD_ERROR
    assert censor.calls == []


def test_missing_transcript_fails_job(censor: FakeCensor, user: AppUser) -> None:
    record = asyncio.run(make_audio(user.id, stage=JobStage.TRANSCRIBED))  # no transcript row

    run("detect", record.id)

    assert row(record.id).error == tasks.MISSING_TRANSCRIPT_ERROR


def test_storage_outage_is_retried_not_failed(
    censor: FakeCensor, user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A storage error while fetching the upload must not fail the job for
    good: it propagates, so Celery retries the step (autoretry_for)."""
    from botocore.exceptions import EndpointConnectionError

    record = asyncio.run(make_audio(user.id))

    def unreachable(key: str):
        raise EndpointConnectionError(endpoint_url="http://s3.invalid")

    monkeypatch.setattr(get_storage(), "local_copy", unreachable)
    monkeypatch.setattr(tasks.transcribe_audio_task, "max_retries", 0)

    with pytest.raises(EndpointConnectionError):
        run("transcribe", record.id)
    still = row(record.id)
    assert (still.status, still.error) == (AudioStatus.PROCESSING, None)


def test_deleted_record_is_skipped(censor: FakeCensor) -> None:
    for step in STEPS:
        run(step, uuid4())
    assert censor.calls == []


# --- claiming a step: duplicates, redelivery, giving up --------------------------------


def running(user: AppUser, stage: JobStage | None, **fields: Any):
    """A job whose next step (after `stage`) a task has claimed."""
    return asyncio.run(
        make_audio(
            user.id,
            AudioStatus.PROCESSING,
            stage=stage,
            task_id=fields.pop("task_id", "task-1"),
            attempts=fields.pop("attempts", 1),
            started_at=fields.pop("started_at", utc_now()),
            **fields,
        )
    )


def test_redelivered_step_takes_its_job_back(censor: FakeCensor, user: AppUser) -> None:
    """The worker died mid-step and Celery delivered the same task again."""
    record = running(user, None, task_id="task-1")
    run("transcribe", record.id, task_id="task-1")

    after = row(record.id)
    assert after.stage == JobStage.TRANSCRIBED
    assert after.attempts == 0  # reset once the step finished


def test_duplicate_step_skips_while_another_task_runs_it(
    censor: FakeCensor, user: AppUser
) -> None:
    record = running(user, None, task_id="task-1")
    run("transcribe", record.id, task_id="task-2")

    assert censor.calls == []
    still = row(record.id)
    assert (still.task_id, still.attempts, still.stage) == ("task-1", 1, None)


def test_step_whose_worker_vanished_can_be_taken_over(censor: FakeCensor, user: AppUser) -> None:
    long_ago = utc_now() - timedelta(seconds=settings.stale_processing_seconds + 60)
    record = running(user, None, task_id="task-1", started_at=long_ago)
    run("transcribe", record.id, task_id="task-2")

    assert row(record.id).stage == JobStage.TRANSCRIBED


def test_gives_up_after_max_attempts(censor: FakeCensor, user: AppUser) -> None:
    """E.g. a file that runs the worker out of memory every time."""
    record = running(user, None, task_id="task-1", attempts=get_worker_settings().MAX_JOB_ATTEMPTS)
    run("transcribe", record.id, task_id="task-1")

    assert censor.calls == []
    failed = row(record.id)
    assert (failed.status, failed.error) == (AudioStatus.FAILED, tasks.GAVE_UP_ERROR)


def test_attempts_count_per_step(censor: FakeCensor, user: AppUser) -> None:
    """Three steps of one job aren't three attempts: each step starts at zero."""
    record = asyncio.run(make_audio(user.id))
    for step in STEPS:
        run(step, record.id)
        assert row(record.id).attempts == 0
    assert row(record.id).status == AudioStatus.COMPLETED


# --- queuing (enqueue_censor) --------------------------------------------------------------


class _FakeChain:
    def __init__(self, sent: list[list[tuple[str, list]]], *steps) -> None:
        self.steps = [(s.task, list(s.args)) for s in steps]
        self.immutable = [s.immutable for s in steps]
        self.sent = sent

    def apply_async(self) -> None:
        self.sent.append(self.steps)
        assert all(self.immutable)  # no step gets the previous one's result


@pytest.fixture
def chains(monkeypatch: pytest.MonkeyPatch) -> list[list[tuple[str, list]]]:
    sent: list[list[tuple[str, list]]] = []
    monkeypatch.setattr(celery_module, "chain", lambda *steps: _FakeChain(sent, *steps))
    return sent


def test_enqueue_queues_the_steps_after_a_stage(chains) -> None:
    audio_id = uuid4()
    celery_module.enqueue_censor(audio_id)
    celery_module.enqueue_censor(audio_id, after=JobStage.TRANSCRIBED)
    celery_module.enqueue_censor(audio_id, after=JobStage.DETECTED)

    assert chains == [
        [("audio.transcribe", [audio_id]), ("audio.detect_profanity", [audio_id]), ("audio.render", [audio_id])],
        [("audio.detect_profanity", [audio_id]), ("audio.render", [audio_id])],
        [("audio.render", [audio_id])],
    ]
    with pytest.raises(ValueError, match="No steps follow"):
        celery_module.enqueue_censor(audio_id, after=JobStage.RENDERED)


def test_queued_chain_runs_end_to_end(censor: FakeCensor, user: AppUser) -> None:
    """The real chain, run eagerly in-process: wiring, names and arguments."""
    record = asyncio.run(make_audio(user.id))
    conf = celery_module.celery_app.conf
    conf.task_always_eager = True  # Celery's settings can't be monkeypatched back
    try:
        celery_module.enqueue_censor(record.id)
    finally:
        conf.task_always_eager = False

    assert censor.steps() == ["transcribe", "detect", "render"]
    assert row(record.id).status == AudioStatus.COMPLETED


# --- recover_stuck_jobs ----------------------------------------------------------------------


def test_recovery_requeues_each_job_from_its_next_step(requeued, user: AppUser) -> None:
    now = utc_now()
    old = now - timedelta(minutes=get_worker_settings().PENDING_REQUEUE_AFTER_MINUTES + 1)
    long_ago = now - timedelta(seconds=settings.stale_processing_seconds + 60)

    # Stuck: the first message was lost...
    lost = asyncio.run(make_audio(user.id, queued_at=old, updated_at=old))
    # ...the next step's message was lost (the worker died between steps)...
    between = asyncio.run(
        make_audio(user.id, AudioStatus.PROCESSING, stage=JobStage.TRANSCRIBED,
                   queued_at=old, updated_at=old)
    )
    # ...a step's worker died and it was never redelivered.
    vanished = running(user, JobStage.DETECTED, started_at=long_ago, queued_at=long_ago)
    # Not stuck: recently queued, between steps just now, running, finished.
    asyncio.run(make_audio(user.id, queued_at=now))
    asyncio.run(make_audio(user.id, AudioStatus.PROCESSING, stage=JobStage.TRANSCRIBED, queued_at=old))
    running(user, None)
    asyncio.run(make_audio(user.id, AudioStatus.COMPLETED, stage=JobStage.RENDERED, queued_at=old, updated_at=old))

    assert tasks.recover_stuck_jobs() == 3
    assert sorted(requeued, key=str) == sorted(
        [(lost.id, None), (between.id, JobStage.TRANSCRIBED), (vanished.id, JobStage.DETECTED)],
        key=str,
    )

    # Marked as just queued, so the next run leaves them alone.
    requeued.clear()
    assert tasks.recover_stuck_jobs() == 0


def test_recovered_job_runs_to_completion(censor: FakeCensor, requeued, user: AppUser) -> None:
    long_ago = utc_now() - timedelta(seconds=settings.stale_processing_seconds + 60)
    record = running(user, JobStage.TRANSCRIBED, task_id="dead", started_at=long_ago, queued_at=long_ago)
    asyncio.run(make_transcript(record.id, [dict(w) for w in censor.transcript]))

    tasks.recover_stuck_jobs()
    assert requeued == [(record.id, JobStage.TRANSCRIBED)]

    run("detect", record.id, task_id="new-detect")  # the re-queued chain runs
    run("render", record.id, task_id="new-render")
    assert row(record.id).status == AudioStatus.COMPLETED
    assert censor.steps() == ["detect", "render"]  # no re-transcription


# --- AudioService.update_settings + the worker -----------------------------------------


def test_update_settings_then_worker_completes_with_new_words(
    censor: FakeCensor, user: AppUser
) -> None:
    """The service decides what to re-run; the worker's steps then pick up
    exactly there (no re-transcription)."""
    from app.service.audio_service import AudioService
    from tests.helpers import FakeQueue, helper_sessions

    record = asyncio.run(make_audio(user.id, original=b"song"))
    run_all(record.id)
    queue = FakeQueue()

    async def change() -> None:
        async with helper_sessions() as session:
            await AudioService(session, queue).update_settings(
                record.id, user.id, custom_words=["hello"]
            )

    asyncio.run(change())
    assert queue.after == [JobStage.TRANSCRIBED]
    for step in ("detect", "render"):  # what enqueue_censor(after=TRANSCRIBED) queues
        run(step, record.id, task_id=f"{step}-rerun")

    done = row(record.id)
    assert (done.status, done.flagged_count) == (AudioStatus.COMPLETED, 2)
    assert censor.steps() == ["transcribe", "detect", "render", "detect", "render"]
    assert read_stored(done.censored_file_path) == b"censored[hello,darn]:song"


def test_transcription_is_capped_and_too_long_audio_fails_clearly(
    censor: FakeCensor, user: AppUser
) -> None:
    from app.audio_censor import AudioTooLongError

    record = asyncio.run(make_audio(user.id))
    run("transcribe", record.id)
    assert censor.last("transcribe")["max_seconds"] == settings.MAX_AUDIO_MINUTES * 60

    censor.errors["transcribe"] = AudioTooLongError(settings.MAX_AUDIO_MINUTES * 60)
    long_one = asyncio.run(make_audio(user.id))
    run_all(long_one.id)

    failed = row(long_one.id)
    assert (failed.status, failed.error) == (AudioStatus.FAILED, tasks.TOO_LONG_ERROR)
    assert censor.steps().count("detect") == 0  # later steps skipped
