"""The Celery tasks, run in-process (no broker), with a fake AudioCensor.

These tests are synchronous because the tasks run their own event loops
(asyncio.run), exactly as they do inside the worker.
"""

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from app.audio_censor import AudioDecodeError, Word
from app.config import get_worker_settings, settings
from app.database.models import AudioStatus, utc_now
from app.storage import get_storage
from app.worker import tasks
from tests.helpers import AppUser, get_audio_row, make_audio, read_stored


class FakeCensor:
    def __init__(self, words: list[Word] | None = None, error: BaseException | None = None):
        self.words = words if words is not None else []
        self.error = error
        # True: behave like a clean file in the same format (nothing written).
        self.unchanged = False
        self.calls: list[tuple[str, str, int, bool]] = []
        self.copy_unchanged: list[bool] = []

    def censor_audio(
        self,
        audio_path: str,
        output_path: str,
        padding_ms: int,
        beep: bool,
        copy_unchanged: bool = True,
    ):
        self.calls.append((audio_path, output_path, padding_ms, beep))
        self.copy_unchanged.append(copy_unchanged)
        if self.error is not None:
            Path(output_path).write_bytes(b"partial")  # must be cleaned up
            raise self.error
        if self.unchanged and not copy_unchanged:
            return None, self.words
        Path(output_path).write_bytes(b"censored:" + Path(audio_path).read_bytes())
        return output_path, self.words


@pytest.fixture
def censor(monkeypatch: pytest.MonkeyPatch) -> FakeCensor:
    fake = FakeCensor(
        words=[
            {"word": "hello", "start": 0.0, "end": 0.4, "flagged": False},
            {"word": "darn", "start": 0.5, "end": 0.9, "flagged": True},
            {"word": "it", "flagged": False},
        ]
    )
    monkeypatch.setattr(tasks, "get_censor", lambda: fake)
    return fake


@pytest.fixture
def requeued(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """Jobs recover_stuck_jobs puts back on the queue."""
    sent: list[UUID] = []
    monkeypatch.setattr(tasks, "enqueue_censor", sent.append)
    return sent


@pytest.fixture
def user(make_user) -> AppUser:
    return asyncio.run(make_user())


def run(audio_id: UUID, task_id: str = "task-1") -> None:
    """Run the censor task as a worker would, with a Celery task id."""
    cast(Task, tasks.censor_audio).apply(args=[audio_id], task_id=task_id, throw=True)


def row(audio_id: UUID):
    record = asyncio.run(get_audio_row(audio_id))
    assert record is not None
    return record


# --- the censor job ---------------------------------------------------------


def test_clean_job_reuses_the_upload_instead_of_a_copy(
    censor: FakeCensor, user: AppUser
) -> None:
    censor.unchanged = True
    censor.words = [Word(word="hello", flagged=False)]
    record = asyncio.run(make_audio(user.id, original=b"clean audio"))

    run(record.id)

    done = row(record.id)
    assert censor.copy_unchanged == [False]  # the worker asks for no copy
    assert done.status == AudioStatus.COMPLETED
    assert (done.words_count, done.flagged_count) == (1, 0)
    assert done.censored_file_path == done.file_path  # one stored file
    assert read_stored(record.censored_file_path) is None  # no duplicate written
    assert read_stored(done.censored_file_path) == b"clean audio"


def test_completes_job_with_stored_options(censor: FakeCensor, user: AppUser) -> None:
    record = asyncio.run(make_audio(user.id, padding_ms=300, beep=True))

    run(record.id)

    done = row(record.id)
    assert done.status == AudioStatus.COMPLETED
    assert (done.words_count, done.flagged_count) == (3, 1)
    assert done.attempts == 1 and done.task_id == "task-1"
    assert done.started_at is not None and done.finished_at is not None
    assert done.error is None
    assert censor.calls[0][2:] == (300, True)  # options read from the row
    assert (read_stored(done.censored_file_path) or b"").startswith(b"censored:")


def test_undecodable_upload_fails_with_message(censor: FakeCensor, user: AppUser) -> None:
    censor.error = AudioDecodeError("bad")
    record = asyncio.run(make_audio(user.id))

    run(record.id)  # handled: no exception

    failed = row(record.id)
    assert failed.status == AudioStatus.FAILED
    assert failed.error == tasks.DECODE_ERROR
    assert read_stored(failed.censored_file_path) is None  # partial output discarded


def test_job_over_time_limit_fails(censor: FakeCensor, user: AppUser) -> None:
    censor.error = SoftTimeLimitExceeded()
    record = asyncio.run(make_audio(user.id))

    run(record.id)

    failed = row(record.id)
    assert failed.status == AudioStatus.FAILED
    assert failed.error == tasks.TIMEOUT_ERROR
    assert read_stored(failed.censored_file_path) is None  # partial output discarded


def test_unexpected_error_fails_job_and_reraises(censor: FakeCensor, user: AppUser) -> None:
    censor.error = RuntimeError("model crashed")
    record = asyncio.run(make_audio(user.id))

    with pytest.raises(RuntimeError, match="model crashed"):
        run(record.id)

    failed = row(record.id)
    assert failed.status == AudioStatus.FAILED
    assert failed.error == tasks.UNEXPECTED_ERROR  # no internals shown to the client
    assert read_stored(failed.censored_file_path) is None  # partial output discarded


def test_missing_upload_fails_job(censor: FakeCensor, user: AppUser) -> None:
    record = asyncio.run(make_audio(user.id))
    get_storage().delete(record.file_path)

    run(record.id)

    failed = row(record.id)
    assert failed.status == AudioStatus.FAILED
    assert failed.error == tasks.MISSING_UPLOAD_ERROR
    assert censor.calls == []


def test_storage_outage_is_retried_not_failed(
    censor: FakeCensor, user: AppUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A storage error while fetching the upload must not fail the job for
    good: it propagates, so Celery retries it (autoretry_for)."""
    from botocore.exceptions import EndpointConnectionError

    record = asyncio.run(make_audio(user.id))
    storage = get_storage()

    def unreachable(key: str):
        raise EndpointConnectionError(endpoint_url="http://s3.invalid")

    monkeypatch.setattr(storage, "local_copy", unreachable)
    monkeypatch.setattr(tasks.censor_audio, "max_retries", 0)  # retry once in-process, then stop

    with pytest.raises(EndpointConnectionError):
        run(record.id)
    still = row(record.id)
    assert still.status == AudioStatus.PROCESSING  # not FAILED: retried / recovered later
    assert still.error is None


# --- claiming: duplicates, redelivery, giving up --------------------------------


def test_deleted_record_is_skipped(censor: FakeCensor) -> None:
    run(uuid4())
    assert censor.calls == []


@pytest.mark.parametrize("status", [AudioStatus.COMPLETED, AudioStatus.FAILED])
def test_finished_job_is_not_run_again(censor: FakeCensor, user: AppUser, status) -> None:
    record = asyncio.run(make_audio(user.id, status))
    run(record.id)
    assert censor.calls == []
    assert row(record.id).status == status


def test_redelivered_task_takes_its_job_back(censor: FakeCensor, user: AppUser) -> None:
    """The worker died mid-job and Celery delivered the same task again."""
    record = asyncio.run(
        make_audio(
            user.id, AudioStatus.PROCESSING, task_id="task-1", attempts=1, started_at=utc_now()
        )
    )
    run(record.id, task_id="task-1")

    done = row(record.id)
    assert done.status == AudioStatus.COMPLETED
    assert done.attempts == 2


def test_duplicate_task_skips_job_another_task_is_running(
    censor: FakeCensor, user: AppUser
) -> None:
    record = asyncio.run(
        make_audio(
            user.id, AudioStatus.PROCESSING, task_id="task-1", attempts=1, started_at=utc_now()
        )
    )
    run(record.id, task_id="task-2")

    assert censor.calls == []
    still = row(record.id)
    assert (still.status, still.task_id, still.attempts) == (AudioStatus.PROCESSING, "task-1", 1)


def test_job_whose_worker_vanished_can_be_taken_over(censor: FakeCensor, user: AppUser) -> None:
    long_ago = utc_now() - timedelta(seconds=settings.stale_processing_seconds + 60)
    record = asyncio.run(
        make_audio(
            user.id, AudioStatus.PROCESSING, task_id="task-1", attempts=1, started_at=long_ago
        )
    )
    run(record.id, task_id="task-2")

    done = row(record.id)
    assert done.status == AudioStatus.COMPLETED
    assert (done.task_id, done.attempts) == ("task-2", 2)


def test_gives_up_after_max_attempts(censor: FakeCensor, user: AppUser) -> None:
    """E.g. a file that runs the worker out of memory every time."""
    record = asyncio.run(
        make_audio(
            user.id,
            AudioStatus.PROCESSING,
            task_id="task-1",
            attempts=get_worker_settings().MAX_JOB_ATTEMPTS,
            started_at=utc_now(),
        )
    )
    run(record.id, task_id="task-1")

    assert censor.calls == []
    failed = row(record.id)
    assert failed.status == AudioStatus.FAILED
    assert failed.error == tasks.GAVE_UP_ERROR
    assert failed.finished_at is not None


# --- recover_stuck_jobs ---------------------------------------------------------


def test_recovery_requeues_only_stuck_jobs(requeued: list[UUID], user: AppUser) -> None:
    now = utc_now()
    pending_cutoff = timedelta(minutes=get_worker_settings().PENDING_REQUEUE_AFTER_MINUTES)
    stale_cutoff = timedelta(seconds=settings.stale_processing_seconds)

    lost = asyncio.run(make_audio(user.id, queued_at=now - pending_cutoff - timedelta(minutes=1)))
    vanished = asyncio.run(
        make_audio(
            user.id,
            AudioStatus.PROCESSING,
            started_at=now - stale_cutoff - timedelta(minutes=1),
            queued_at=now - stale_cutoff - timedelta(minutes=1),
        )
    )
    # Not stuck: recently queued, still running, or finished long ago.
    asyncio.run(make_audio(user.id, queued_at=now))
    asyncio.run(make_audio(user.id, AudioStatus.PROCESSING, started_at=now, queued_at=now))
    asyncio.run(
        make_audio(user.id, AudioStatus.COMPLETED, queued_at=now - timedelta(days=1))
    )

    assert tasks.recover_stuck_jobs() == 2
    assert sorted(requeued) == sorted([lost.id, vanished.id])

    # Marked as just queued, so the next run leaves them alone.
    assert row(lost.id).queued_at > now  # type: ignore[operator]
    requeued.clear()
    assert tasks.recover_stuck_jobs() == 0
    assert requeued == []


def test_recovered_job_runs_to_completion(
    censor: FakeCensor, requeued: list[UUID], user: AppUser
) -> None:
    long_ago = utc_now() - timedelta(seconds=settings.stale_processing_seconds + 60)
    record = asyncio.run(
        make_audio(
            user.id,
            AudioStatus.PROCESSING,
            task_id="dead-task",
            attempts=1,
            started_at=long_ago,
            queued_at=long_ago,
        )
    )
    tasks.recover_stuck_jobs()
    assert requeued == [record.id]

    run(record.id, task_id="new-task")  # the requeued message is delivered
    assert row(record.id).status == AudioStatus.COMPLETED
