# Audio Censor API

FastAPI service that transcribes English audio with WhisperX and mutes or beeps out profanity.

## Setup

```powershell
uv sync                         # install dependencies into .venv
copy .env.example .env          # then fill in DB_URL and JWT_SECRET_KEY
uv run alembic upgrade head     # create/update the database schema
uv run fastapi dev app/main.py  # http://127.0.0.1:8000/scalar for API docs
```

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
