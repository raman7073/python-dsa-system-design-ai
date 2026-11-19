# Two images from one file (docker-compose.yml picks the target):
#   api     the FastAPI app: no WhisperX, no ffmpeg (a few hundred MB)
#   worker  the Celery worker and beat: WhisperX on CPU, ffmpeg (~3 GB)

FROM python:3.13-slim-bookworm AS base

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

# Run as an unprivileged user. Its ~/.cache holds the worker's downloaded
# models and is a named volume, so they are downloaded only once.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /home/app/.cache /app/storage \
    && chown -R app:app /home/app/.cache /app
WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

COPY --chown=app:app pyproject.toml uv.lock ./
COPY --chown=app:app docker/entrypoint.sh /usr/local/bin/entrypoint
ENTRYPOINT ["sh", "/usr/local/bin/entrypoint"]


FROM base AS api

# Base dependencies only (no `worker` or `dev` group). In their own layer,
# so editing app code doesn't reinstall them.
USER app
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --locked --no-default-groups --no-install-project

# The API checks at startup that the database is at the latest migration,
# so it needs the migration scripts.
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app

EXPOSE 8000
# Behind a reverse proxy, add --proxy-headers --forwarded-allow-ips=<proxy IP>
# so rate limits see the real client IP.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM base AS worker

# ffmpeg decodes the uploads (WhisperX and pydub both call it).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Base + `worker` group. On Linux the lockfile resolves PyTorch's CPU build.
USER app
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --locked --no-default-groups --group worker --no-install-project

COPY --chown=app:app app ./app

CMD ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=INFO"]
