"""Shared test setup.

Tests never touch development data:
- Database: a separate one, the dev database's name + "_test" (e.g.
  censor_test), created and migrated on first run. Override with TEST_DB_URL.
  Every test starts with empty tables.
- Storage: a temporary folder, emptied before every test.
- Job queue and rate limiter: replaced by in-memory fakes for every test,
  so nothing reaches Redis.

Needs only Postgres running (the server from DB_URL in .env).
"""

import asyncio
import os
import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _test_db_url() -> str:
    if url := os.environ.get("TEST_DB_URL"):
        return url
    dev_url = os.environ.get("DB_URL") or dotenv_values(PROJECT_ROOT / ".env").get("DB_URL")
    if not dev_url:
        raise RuntimeError("Set DB_URL in .env (or TEST_DB_URL) to run the tests.")
    url = make_url(dev_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


TEST_DB_URL = _test_db_url()
if not (make_url(TEST_DB_URL).database or "").endswith("_test"):
    raise RuntimeError("Refusing to run tests against a database not named *_test.")
STORAGE_DIR = Path(tempfile.mkdtemp(prefix="audio-censor-tests-"))

# Settings are read when `app` is first imported, so these must be set first.
os.environ["DB_URL"] = TEST_DB_URL
os.environ["DB_ECHO"] = "false"
os.environ["STORAGE_BACKEND"] = "local"  # S3Storage has its own tests
os.environ["STORAGE_DIR"] = str(STORAGE_DIR)
os.environ["MAX_UPLOAD_MB"] = "1"
os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-that-is-long-enough-for-hs256"
# Only the Redis rate limiter test talks to Redis; keep its keys in a
# separate database from the app's (db 0).
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/15"

import httpx
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import text

from app import security
from app.api import dependencies
from app.api.rate_limit import get_rate_limiter
from app.config import settings
from app.database.models import User
from app.main import app
from app.security import hash_password
from app.storage import CENSORED, EFFECTS, UPLOADS, get_storage
from tests.helpers import (
    AppUser,
    FakeQueue,
    InMemoryRateLimiter,
    MakeUser,
    helper_engine,
    helper_sessions,
)

# Argon2 is slow on purpose (tens of ms and 64 MB per hash). Tests hash and
# verify passwords constantly, so use the cheapest parameters: same code
# path, still real Argon2. Production keeps pwdlib's recommended ones.
security._password_hash = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),))
security._DUMMY_HASH = security._password_hash.hash("dummy-password-for-timing")


async def _create_database_if_missing(url: str) -> None:
    import asyncpg

    u = make_url(url)
    conn = await asyncpg.connect(
        user=u.username, password=u.password, host=u.host, port=u.port, database="postgres"
    )
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", u.database):
            await conn.execute(f'CREATE DATABASE "{u.database}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def _test_database() -> Iterator[None]:
    """Create the test database if needed and bring it to the latest migration."""
    from alembic.config import Config

    from alembic import command

    asyncio.run(_create_database_if_missing(TEST_DB_URL))
    command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    yield
    shutil.rmtree(STORAGE_DIR, ignore_errors=True)


async def _truncate_tables() -> None:
    async with helper_engine.begin() as conn:
        await conn.execute(text("TRUNCATE audio, users CASCADE"))


@pytest.fixture(autouse=True)
def _clean_state() -> None:
    """Empty tables and storage before every test."""
    asyncio.run(_truncate_tables())
    for folder in (UPLOADS, CENSORED, EFFECTS):
        shutil.rmtree(settings.storage_path / folder, ignore_errors=True)
    get_storage().ensure_ready()


@pytest.fixture(autouse=True)
def queue(monkeypatch: pytest.MonkeyPatch) -> FakeQueue:
    fake = FakeQueue()
    monkeypatch.setattr(dependencies, "enqueue_censor", fake)
    return fake


@pytest.fixture(autouse=True)
def rate_limiter() -> Iterator[InMemoryRateLimiter]:
    """A fresh in-memory rate limiter per test (no Redis needed)."""
    limiter = InMemoryRateLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    yield limiter
    app.dependency_overrides.pop(get_rate_limiter, None)


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def make_user() -> MakeUser:
    async def _make(email: str | None = None, password: str = "secret-pass-1") -> AppUser:
        email = email or f"user-{uuid4().hex[:8]}@example.com"
        async with helper_sessions() as s:
            user = User(email=email, hashed_password=hash_password(password))
            s.add(user)
            await s.commit()
        return AppUser(id=user.id, email=email, password=password)

    return _make
