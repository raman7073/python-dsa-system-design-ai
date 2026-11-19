"""Request rate limits: a fixed window per key, counted in Redis.

Add a limit to a route with `dependencies=[Depends(limit_login)]` etc. Over
the limit, the route answers 429 with a Retry-After header.

If Redis is unreachable the limiter lets requests through (and logs a
warning) rather than locking everyone out of login.

Client IPs come from the connection. Behind a reverse proxy, run uvicorn
with --proxy-headers and --forwarded-allow-ips so that is the real client.
"""

import logging
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.api.dependencies import CurrentUserDep
from app.config import get_api_settings, settings

logger = logging.getLogger(__name__)


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int) -> int | None:
        """Count one request for `key`. Returns the seconds until the window
        resets if this request is over `limit`, else None."""
        ...


class RedisRateLimiter:
    def __init__(self, url: str):
        # Short timeouts: a slow Redis must not slow down every login.
        self._redis = Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)

    async def hit(self, key: str, limit: int, window_seconds: int) -> int | None:
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                # The window starts at the first request; NX keeps later
                # requests from pushing the reset further out.
                pipe.expire(key, window_seconds, nx=True)
                pipe.ttl(key)
                count, _, ttl = await pipe.execute()
        except (RedisError, OSError):
            logger.warning("Rate limiter unavailable; allowing request", exc_info=True)
            return None
        return max(int(ttl), 1) if count > limit else None

    async def close(self) -> None:
        await self._redis.aclose()


rate_limiter = RedisRateLimiter(settings.REDIS_URL)


def get_rate_limiter() -> RateLimiter:
    """Override in tests: app.dependency_overrides[get_rate_limiter] = ..."""
    return rate_limiter


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


async def _enforce(limiter: RateLimiter, key: str, limit: int, window_seconds: int) -> None:
    if not get_api_settings().RATE_LIMIT_ENABLED:
        return
    retry_after = await limiter.hit(f"ratelimit:{key}", limit, window_seconds)
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests; try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def limit_login(request: Request, limiter: RateLimiterDep) -> None:
    await _enforce(
        limiter, f"login:{_client_ip(request)}", get_api_settings().LOGIN_RATE_LIMIT_PER_MINUTE, 60
    )


async def limit_signup(request: Request, limiter: RateLimiterDep) -> None:
    await _enforce(
        limiter, f"signup:{_client_ip(request)}", get_api_settings().SIGNUP_RATE_LIMIT_PER_HOUR, 3600
    )


async def limit_censor(user: CurrentUserDep, limiter: RateLimiterDep) -> None:
    await _enforce(limiter, f"censor:{user.id}", get_api_settings().CENSOR_RATE_LIMIT_PER_HOUR, 3600)


TOO_MANY_REQUESTS: dict[int | str, dict] = {
    429: {
        "description": "Rate limit exceeded; retry after `Retry-After` seconds.",
        "headers": {"Retry-After": {"description": "Seconds until the limit resets."}},
    }
}
