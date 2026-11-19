"""The Celery app, shared by the API (which queues jobs), the worker and beat.

This module is deliberately light: the API imports it to queue jobs, and
must not pull in WhisperX/torch, which only the worker (app.worker.tasks)
needs. Start everything with:
    docker compose up -d
"""

from uuid import UUID

from celery import Celery, chain

from app.config import get_worker_settings, settings
from app.database.models import JobStage

# Tasks are queued by name, so the API never imports app.worker.tasks.
# A censor job is three steps, each its own task (see app.worker.tasks):
TRANSCRIBE_TASK = "audio.transcribe"
DETECT_TASK = "audio.detect_profanity"
RENDER_TASK = "audio.render"
# Each step with the stage the job must be at for it to run.
PIPELINE: tuple[tuple[str, JobStage | None], ...] = (
    (TRANSCRIBE_TASK, None),
    (DETECT_TASK, JobStage.TRANSCRIBED),
    (RENDER_TASK, JobStage.DETECTED),
)
RECOVER_TASK = "audio.recover_stuck_jobs"
RECOVER_EVERY_SECONDS = 5 * 60

celery_app = Celery("audio_censor", broker=settings.REDIS_URL, include=["app.worker.tasks"])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    # Job status and results are kept in the `audio` table, so Celery's own
    # result storage isn't needed.
    task_ignore_result=True,
    # A censor job takes minutes. Acknowledge it only once it has finished,
    # so it is run again if the worker dies part-way through, and take one
    # job at a time, so a busy worker doesn't hold queued jobs that another
    # worker could start.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # With late acknowledgement, Redis hands a job to another worker if it
    # isn't acknowledged within this time, so it must exceed the longest job
    # step (which each task's time limit caps).
    broker_transport_options={
        "visibility_timeout": settings.job_time_limit_seconds + 30 * 60,
    },
    broker_connection_retry_on_startup=True,
    # Queuing happens inside the upload request: if Redis is down, give up
    # after one quick retry (the API then answers 503) instead of making the
    # client wait through Celery's default three.
    task_publish_retry_policy={
        "max_retries": 1,
        "interval_start": 0.2,
        "interval_step": 0,
        "interval_max": 0.2,
    },
    # Run by the `beat` service (docker-compose.yml).
    beat_schedule={
        "recover-stuck-jobs": {
            "task": RECOVER_TASK,
            "schedule": RECOVER_EVERY_SECONDS,
            # While the worker is busy with a long job these pile up behind
            # it; only the newest is worth running.
            "options": {"expires": RECOVER_EVERY_SECONDS - 30},
        }
    },
)


if max_memory_mb := get_worker_settings().WORKER_MAX_MEMORY_PER_CHILD_MB:
    celery_app.conf.worker_max_memory_per_child = max_memory_mb * 1024  # in KiB


def enqueue_censor(audio_id: UUID, after: JobStage | None = None) -> None:
    """Queue the censor steps that follow `after`, as a chain. Raises if
    Redis is unreachable.

    after=None (a new upload): transcribe, detect, render. To run steps again,
    first set the job's stage back to `after`, e.g. JobStage.TRANSCRIBED to
    detect with new custom words and render again without re-transcribing.

    Each task gets only the audio id and reads everything else from the
    record, so the same steps can be queued again if their messages are lost.
    """
    names = [name for name, requires in PIPELINE if _order(requires) >= _order(after)]
    if not names:
        raise ValueError(f"No steps follow {after!r}")
    # immutable: each task gets only the audio id, not the previous result.
    steps = [celery_app.signature(name, args=[audio_id], immutable=True) for name in names]
    chain(*steps).apply_async()


def _order(stage: JobStage | None) -> int:
    """Position in the pipeline: None (nothing done) < TRANSCRIBED < ..."""
    return 0 if stage is None else list(JobStage).index(stage) + 1
