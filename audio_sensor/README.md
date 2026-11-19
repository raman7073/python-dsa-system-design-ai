# Audio Censor API

FastAPI service that transcribes English audio with WhisperX and mutes or beeps out profanity.

## Setup

```powershell
uv sync                         # install dependencies into .venv
copy .env.example .env          # then fill in DB_URL and JWT_SECRET_KEY
uv run alembic upgrade head     # create/update the database schema
docker compose up -d --build    # start Redis, the Celery worker and beat
uv run fastapi dev app/main.py  # http://127.0.0.1:8000/scalar for API docs
uv run pytest                   # run the tests (needs only Postgres)
```

## How censoring works

Censoring takes minutes, so it runs in the background:

1. `POST /censor` stores the upload, creates an `audio` row with status
   `pending` (including the job's options), queues a job on Redis, and
   returns **202** right away with the record (its URL is in `Location`).
2. The Celery worker (`app/worker/tasks.py`) claims the job (`processing`),
   runs WhisperX, stores the censored file, and sets `completed` (with
   `words_count` and `flagged_count`) or `failed` (with an `error`, e.g. for a
   file that isn't audio, or one that took longer than the time limit).
3. The client polls `GET /audio/{id}` until `status` is `completed`, then
   downloads `censored_url`. Asking for the censored file earlier returns 409.

The API never loads the Whisper models; only the worker does, and only when
a job needs them: the Whisper model on the first job, the alignment model
(word timestamps) on the first job that has something to censor. Both are
then kept in memory (about 1.7 GB together), since loading takes minutes.
A file with nothing to censor skips alignment entirely. If its format can be
written back, no second file is stored at all: the job's censored file is
the upload itself (otherwise it is converted).

### What happens when things go wrong

| Situation | What happens |
|---|---|
| Redis is down when uploading | 503; nothing is stored |
| The worker dies mid-job | Celery delivers the job again; the same task reclaims it |
| A job keeps killing the worker (e.g. out of memory) | Failed after `MAX_JOB_ATTEMPTS` (3) starts |
| Brief database/storage outage during a job | The job is retried with backoff |
| A job's message is lost, or its worker vanished | `beat` runs `recover_stuck_jobs` every 5 minutes and re-queues it |
| A job runs longer than `JOB_TIME_LIMIT_MINUTES` | Failed with "took too long" |

### Limits

- Request bodies over `MAX_UPLOAD_MB` (plus a little for form fields) are
  refused with **413** before they are read, so oversized uploads never reach
  the disk, even without a token.
- A user can have `MAX_ACTIVE_JOBS_PER_USER` (3) jobs pending or processing
  at once; further uploads get **429** until one finishes.
- Rate limits (counted in Redis): login 10/minute and signup 10/hour per
  client IP, `/censor` 30/hour per user. Over the limit: **429** with
  `Retry-After`. They count every request, so set `RATE_LIMIT_ENABLED=false`
  in `.env` when running the Postman collection repeatedly.

## Listing audio

`GET /audio` returns your records newest first, `limit` at a time (up to
100). For the next page, pass the `X-Next-Cursor` response header back as
`?before=`; it is absent on the last page. Cursor paging stays fast however
deep you go (`offset` still works, but slows down on deep pages).

## Storage

Uploads and censored files are stored by key (`uploads/<id>.mp3`,
`censored/<id>.mp3`) in one of two backends (`STORAGE_BACKEND`):

- **`local`** (default): the `storage/` folder. The API and worker share it,
  so they must run on one machine.
- **`s3`**: an S3 bucket (AWS S3, or any S3-compatible store), so the API and
  any number of workers can run on different machines. Downloads are
  streamed through the API, so links stay behind login, and the S3
  connection is closed even if the client disconnects mid-download. For local testing,
  `docker compose --profile s3 up -d s3` starts a SeaweedFS S3 server on
  `127.0.0.1:8333`; see `.env.example` for the matching settings.

Switching backends doesn't move existing files: records created before the
switch point at files the new backend doesn't have.

## Docker

Redis, the worker and beat run from `docker-compose.yml`; in development
the API runs on the host.

- **Two images** from one `Dockerfile`: `worker` (WhisperX, CPU-only
  PyTorch, ffmpeg; ~3 GB) and `api` (~300 MB, no WhisperX). Dependencies are
  split to match: the `worker` group in `pyproject.toml` holds WhisperX and
  friends; locally `uv sync` installs everything.
- **Each container gets only its own settings** (not the whole `.env`), e.g.
  the worker never sees `JWT_SECRET_KEY`. `localhost` in `DB_URL` and
  `S3_ENDPOINT_URL` is mapped to the host, so the same `.env` works.
- **beat** schedules `recover_stuck_jobs`. Run exactly one.
- The worker keeps downloaded models in the `model-cache` volume; the first
  job after a start loads them, which is slower.
- `app/` is mounted into the worker and beat, so **after changing code, run
  `docker compose restart worker beat`**. Rebuild (`--build`) only after
  changing dependencies.

| Command | What it does |
|---|---|
| `docker compose up -d --build` | Build and start Redis, worker and beat |
| `docker compose --profile api up -d` | Also run the API in a container (port `API_PORT`, default 8000) |
| `docker compose --profile s3 up -d s3` | Start the local S3 server |
| `docker compose ps` | Status |
| `docker compose logs -f worker` | Follow the worker's log (jobs, errors) |
| `docker compose restart worker beat` | Pick up code changes |
| `docker compose down` | Stop (data and models are kept) |
| `docker compose down -v` | Stop and delete Redis data, S3 data and the model cache |

## Tests

```powershell
uv run pytest
```

The tests use their own database (the dev database's name + `_test`, e.g.
`censor_test`, created and migrated automatically; override with
`TEST_DB_URL`) and a temporary storage folder, so they never touch development
data. The job queue and rate limiter are replaced by in-memory fakes. The S3
storage tests run against the local S3 server if it is up, and are skipped
otherwise.

## Database migrations (Alembic)

The schema is managed only by Alembic migrations in `alembic/versions/`. The app
never creates or alters tables itself: at startup it checks that the database is
at the latest migration and refuses to start otherwise.

After changing a model in `app/database/models.py`:

```powershell
uv run alembic revision --autogenerate -m "describe the change"
# review the generated file in alembic/versions/, then:
uv run alembic upgrade head
```

Other useful commands:

| Command | What it does |
|---|---|
| `uv run alembic current` | Revision the database is at |
| `uv run alembic history` | All migrations |
| `uv run alembic check` | Fails if the models have changes with no migration yet |
| `uv run alembic downgrade -1` | Undo the last migration |
| `uv run alembic upgrade head --sql` | Print the SQL without running it |

The database URL comes from `DB_URL` (in `.env` or the environment), not from
`alembic.ini`.

A database created before Alembic was adopted already has the baseline schema;
mark it once with `uv run alembic stamp 2fe68bca49d1` instead of upgrading.
