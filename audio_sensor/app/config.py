"""Settings, split by who needs them, so each process only needs (and is only
given) its own secrets:

- `settings`: shared by the API, the worker and Alembic (database, Redis,
  storage). Loaded on import.
- `get_api_settings()`: the API only (JWT signing, upload and abuse limits).
- `get_worker_settings()`: the Celery worker only (Whisper, job retries).

The API and worker groups are loaded on first use, so e.g. the worker never
needs JWT_SECRET_KEY. Each field is read from an environment variable of the
same name, falling back to the .env file at the project root; real
environment variables take precedence over .env.
"""

from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (the folder containing pyproject.toml), resolved from this
# file's location so the .env file is found no matter which directory the
# app is started from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class _EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env holds every group's keys
        # An empty variable means "use the default": docker-compose.yml passes
        # each setting as ${NAME:-}, which is empty when .env doesn't set it.
        env_ignore_empty=True,
    )


class SharedSettings(_EnvSettings):
    DB_URL: str
    # Log every SQL statement (with parameters). Useful locally, noisy and
    # potentially sensitive elsewhere.
    DB_ECHO: bool = False
    # The API's connection pool (app.database.session). The worker doesn't
    # pool (see app.worker.tasks).
    DB_POOL_SIZE: int = Field(default=5, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=10, ge=0)
    # Celery broker (Redis in docker-compose.yml). The containers override
    # this to reach Redis by its service name. 127.0.0.1 rather than
    # localhost: on Windows, localhost tries IPv6 first, and Redis listens on
    # IPv4 only, which adds seconds to the first connection.
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    # Where uploaded and censored audio files are kept (app.storage):
    # - "local": a folder, STORAGE_DIR (relative paths are resolved against
    #   the project root). The API and worker must share it.
    # - "s3": an S3 bucket (AWS, or a compatible store such as MinIO), so the
    #   API and workers can run on different machines.
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_DIR: Path = Path("storage")
    S3_BUCKET: str = "audio-censor"
    # Only for S3-compatible stores, e.g. http://127.0.0.1:9000 for MinIO.
    # Leave unset for AWS S3.
    S3_ENDPOINT_URL: str | None = None
    S3_REGION: str = "us-east-1"
    # Leave unset to use boto3's usual credentials (AWS_* variables,
    # ~/.aws, or the IAM role on AWS).
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: SecretStr | None = None
    # Create the bucket at startup if it's missing (handy for local MinIO;
    # on AWS, create it yourself and leave this off).
    S3_AUTO_CREATE_BUCKET: bool = False

    # Longest a single censor job may run before it is failed as too long.
    # Must cover the largest allowed upload (MAX_UPLOAD_MB). Shared because
    # the queue's redelivery timeout is derived from it.
    JOB_TIME_LIMIT_MINUTES: int = Field(default=90, gt=0)

    @property
    def storage_path(self) -> Path:
        if self.STORAGE_DIR.is_absolute():
            return self.STORAGE_DIR
        return PROJECT_ROOT / self.STORAGE_DIR

    @property
    def job_time_limit_seconds(self) -> int:
        return self.JOB_TIME_LIMIT_MINUTES * 60

    @property
    def stale_processing_seconds(self) -> int:
        """A job still PROCESSING after this long has lost its worker."""
        return self.job_time_limit_seconds + 15 * 60


class ApiSettings(_EnvSettings):
    # JWT signing. The secret is a SecretStr so it never shows up in logs or
    # reprs; generate one with: python -c "import secrets; print(secrets.token_urlsafe(64))"
    JWT_SECRET_KEY: SecretStr = Field(min_length=32)
    # HMAC algorithms only: they sign with the shared secret above. (RS*/ES*
    # would need a private/public key pair instead.)
    JWT_ALGORITHM: Literal["HS256", "HS384", "HS512"] = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0)

    MAX_UPLOAD_MB: int = Field(default=50, gt=0)
    # Sound effects (POST /sound-effects): short clips, so a small limit.
    MAX_SOUND_EFFECT_MB: int = Field(default=2, gt=0)
    MAX_SOUND_EFFECTS_PER_USER: int = Field(default=20, ge=1)

    # Abuse limits. A user may have this many jobs pending/processing at once
    # (each costs minutes of worker CPU); more uploads get 429 until one ends.
    MAX_ACTIVE_JOBS_PER_USER: int = Field(default=3, ge=1)
    # Request rate limits, counted in Redis (app.api.rate_limit). Login and
    # signup are per client IP, /censor is per user.
    RATE_LIMIT_ENABLED: bool = True
    LOGIN_RATE_LIMIT_PER_MINUTE: int = Field(default=10, ge=1)
    SIGNUP_RATE_LIMIT_PER_HOUR: int = Field(default=10, ge=1)
    CENSOR_RATE_LIMIT_PER_HOUR: int = Field(default=30, ge=1)

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def max_sound_effect_bytes(self) -> int:
        return self.MAX_SOUND_EFFECT_MB * 1024 * 1024


class WorkerSettings(_EnvSettings):
    # A job that starts this many times without finishing is marked failed.
    MAX_JOB_ATTEMPTS: int = Field(default=3, ge=1)
    # A queued job no worker has started after this long is queued again
    # (its message was lost). Extra copies of a job are skipped cheaply.
    PENDING_REQUEUE_AFTER_MINUTES: int = Field(default=15, gt=0)

    # Whisper model size: tiny, base, small, medium, large-v2, large-v3, ...
    WHISPER_MODEL: str = "small"
    # CPU threads for transcription; 0 = one per physical core.
    WHISPER_THREADS: int = Field(default=0, ge=0)
    # Replace a worker process once it uses more than this much memory, after
    # its current job (guards against memory growing over many jobs). 0 = off.
    # Must be well above the ~1.7 GB the loaded models take, and each
    # replacement reloads them (minutes), so only set it if memory does grow.
    WORKER_MAX_MEMORY_PER_CHILD_MB: int = Field(default=0, ge=0)
    # Extra words to censor on top of better_profanity's default list.
    # In .env, as JSON: CENSOR_WORDS=["word1", "word2"]
    CENSOR_WORDS: list[str] = []


# DB_URL and JWT_SECRET_KEY have no defaults: pydantic-settings fills them from
# the environment / .env at runtime, which type checkers can't see.
settings = SharedSettings()  # pyright: ignore[reportCallIssue]


@cache
def get_api_settings() -> ApiSettings:
    return ApiSettings()  # pyright: ignore[reportCallIssue]


@cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
