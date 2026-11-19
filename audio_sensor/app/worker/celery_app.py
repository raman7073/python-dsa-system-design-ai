"""The Celery app, shared by the API (which queues jobs), the worker and beat.

This module is deliberately light: the API imports it to queue jobs, and
must not pull in WhisperX/torch, which only the worker (app.worker.tasks)
needs. Start everything with:
    docker compose up -d
"""

from uuid import UUID

from celery import Celery

from app.config import get_worker_settings, settings

# Tasks are queued by name, so the API never imports app.worker.tasks.
CENSOR_TASK = "audio.censor"
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
    # (which the time limit on the censor task caps).
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


def enqueue_censor(audio_id: UUID) -> None:
    """Queue the censor job for a stored upload. Raises if Redis is unreachable.

    The job's options (padding_ms, beep) are read from the record, so the
    same message can be sent again if it is lost.
    """
    celery_app.send_task(CENSOR_TASK, args=[audio_id])
