import time
import uuid

import httpx
import pytest
from redis.exceptions import RedisError

from app.api.rate_limit import RedisRateLimiter
from app.config import get_api_settings, settings
from app.database.models import AudioStatus
from tests.helpers import FakeQueue, MakeUser, make_audio


def mp3() -> dict:
    return {"file": ("song.mp3", b"fake mp3 bytes", "audio/mpeg")}


# --- active jobs per user -------------------------------------------------------


async def test_upload_refused_while_user_has_max_active_jobs(
    client: httpx.AsyncClient, make_user: MakeUser, queue: FakeQueue
) -> None:
    user = await make_user()
    limit = get_api_settings().MAX_ACTIVE_JOBS_PER_USER
    for i in range(limit):
        await make_audio(user.id, AudioStatus.PENDING if i % 2 else AudioStatus.PROCESSING)

    r = await client.post("/censor", headers=user.headers, files=mp3())

    assert r.status_code == 429
    assert f"already have {limit}" in r.json()["detail"]
    assert "Retry-After" in r.headers
    assert queue.jobs == []


async def test_finished_jobs_dont_count_toward_the_cap(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    for _ in range(get_api_settings().MAX_ACTIVE_JOBS_PER_USER):
        await make_audio(user.id, AudioStatus.COMPLETED)
    await make_audio(user.id, AudioStatus.FAILED)

    r = await client.post("/censor", headers=user.headers, files=mp3())
    assert r.status_code == 202


async def test_cap_is_per_user(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    busy, other = await make_user(), await make_user()
    for _ in range(get_api_settings().MAX_ACTIVE_JOBS_PER_USER):
        await make_audio(busy.id)

    r = await client.post("/censor", headers=other.headers, files=mp3())
    assert r.status_code == 202


# --- request rate limits --------------------------------------------------------


async def test_login_is_rate_limited_per_ip(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    form = {"username": user.email, "password": "wrong-pass-1"}
    for _ in range(get_api_settings().LOGIN_RATE_LIMIT_PER_MINUTE):
        assert (await client.post("/auth/login", data=form)).status_code == 401

    r = await client.post("/auth/login", data=form)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0

    # Even the right password is refused until the window resets.
    form["password"] = user.password
    assert (await client.post("/auth/login", data=form)).status_code == 429


async def test_signup_is_rate_limited_per_ip(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_api_settings(), "SIGNUP_RATE_LIMIT_PER_HOUR", 2)
    codes = [
        (
            await client.post(
                "/auth/signup",
                json={"email": f"u{i}@example.com", "password": "correct-horse-42"},
            )
        ).status_code
        for i in range(3)
    ]
    assert codes == [201, 201, 429]


async def test_censor_is_rate_limited_per_user(
    client: httpx.AsyncClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_api_settings(), "CENSOR_RATE_LIMIT_PER_HOUR", 1)
    monkeypatch.setattr(get_api_settings(), "MAX_ACTIVE_JOBS_PER_USER", 10)
    alice, bob = await make_user(), await make_user()

    assert (await client.post("/censor", headers=alice.headers, files=mp3())).status_code == 202
    assert (await client.post("/censor", headers=alice.headers, files=mp3())).status_code == 429
    assert (await client.post("/censor", headers=bob.headers, files=mp3())).status_code == 202


async def test_limits_can_be_switched_off(
    client: httpx.AsyncClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_api_settings(), "RATE_LIMIT_ENABLED", False)
    user = await make_user()
    form = {"username": user.email, "password": "wrong-pass-1"}
    for _ in range(get_api_settings().LOGIN_RATE_LIMIT_PER_MINUTE + 2):
        assert (await client.post("/auth/login", data=form)).status_code == 401


# --- the Redis limiter itself -----------------------------------------------------


async def test_redis_limiter_counts_and_expires() -> None:
    limiter = RedisRateLimiter(settings.REDIS_URL)  # db 15 in tests
    try:
        await limiter._redis.ping()
    except (RedisError, OSError):
        await limiter.close()
        pytest.skip("Redis not running (docker compose up -d redis)")

    key = f"ratelimit:test:{uuid.uuid4()}"
    assert await limiter.hit(key, limit=2, window_seconds=60) is None
    assert await limiter.hit(key, limit=2, window_seconds=60) is None
    retry_after = await limiter.hit(key, limit=2, window_seconds=60)
    assert retry_after is not None and 0 < retry_after <= 60
    assert 0 < await limiter._redis.ttl(key) <= 60  # the window expires
    await limiter.close()


async def test_redis_limiter_allows_requests_when_redis_is_down() -> None:
    limiter = RedisRateLimiter("redis://127.0.0.1:6390/0")  # nothing listens here
    start = time.monotonic()
    assert await limiter.hit("ratelimit:test:down", limit=0, window_seconds=60) is None
    assert time.monotonic() - start < 5  # short timeouts, no long hang
    await limiter.close()
