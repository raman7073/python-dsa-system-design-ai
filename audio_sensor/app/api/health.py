"""GET /health: is the API up, and can it reach what it depends on?

For load balancers, container orchestrators and uptime monitors. No login.
Each dependency gets a short timeout, so a hung database can't hang the
check; failures are reported by name only, without internal details.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.api.rate_limit import rate_limiter
from app.database.session import engine

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])
CHECK_TIMEOUT_SECONDS = 2.0

CheckResult = Literal["ok", "unavailable"]


class HealthRead(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, CheckResult]


async def check_database() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def check_redis() -> None:
    await rate_limiter.ping()


# Name -> check; each raises (or times out) when the dependency is down.
CHECKS: dict[str, Callable[[], Awaitable[None]]] = {
    "database": check_database,
    "redis": check_redis,
}


async def _run(name: str, check: Callable[[], Awaitable[None]]) -> CheckResult:
    try:
        await asyncio.wait_for(check(), CHECK_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("Health check %r failed", name, exc_info=True)
        return "unavailable"
    return "ok"


@router.get(
    "/health",
    summary="Health check",
    response_model=HealthRead,
    responses={
        503: {"model": HealthRead, "description": "A dependency is unreachable."}
    },
)
async def health(response: Response) -> HealthRead:
    """200 when the database (Postgres) and the job queue (Redis) both answer."""
    names = list(CHECKS)
    results = await asyncio.gather(*(_run(n, CHECKS[n]) for n in names))
    checks = dict(zip(names, results, strict=True))
    healthy = all(r == "ok" for r in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthRead(status="ok" if healthy else "unavailable", checks=checks)
