import math
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from services.cache import get_cache, set_cache

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

CURRENCY_CACHE_TTL = 60 * 60


async def fetch_currency_rates(base_currency: str) -> dict[str, float]:
    """Return latest rates for one unit of the base currency, cached for an hour.

    Requires CURRENCY_API_KEY. Raises ValueError for invalid or unsupported
    currency codes and RuntimeError for configuration or provider failures.
    """
    base_currency = base_currency.strip().upper()
    if (len(base_currency) != 3 or not base_currency.isascii()
            or not base_currency.isalpha()):
        raise ValueError("Base currency must be a three-letter currency code")

    cache_key = f"currency:{base_currency}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached.copy()

    api_key = os.getenv("CURRENCY_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("CURRENCY_API_KEY is not configured")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://v6.exchangerate-api.com/v6/{api_key}/latest/{base_currency}"
            )
    except httpx.HTTPError:
        # Provider URLs contain the API key; do not expose HTTP exceptions.
        raise RuntimeError("Unable to fetch currency rates from the provider") from None

    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("The currency provider returned invalid data") from None
    if not isinstance(payload, dict):
        raise RuntimeError("The currency provider returned invalid data")
    if payload.get("result") == "error":
        if payload.get("error-type") in ("unsupported-code", "unknown-code"):
            raise ValueError(f"Unsupported base currency: {base_currency}")
        raise RuntimeError("The currency provider could not fulfill the request")
    try:
        response.raise_for_status()
    except httpx.HTTPError:
        raise RuntimeError("Unable to fetch currency rates from the provider") from None

    try:
        if payload.get("result") != "success" or payload.get("base_code") != base_currency:
            raise ValueError
        raw_rates = payload["conversion_rates"]
        if not isinstance(raw_rates, dict) or not raw_rates:
            raise ValueError
        rates = {}
        for code, rate in raw_rates.items():
            if (not isinstance(code, str) or len(code) != 3
                    or not code.isascii() or not code.isalpha() or not code.isupper()
                    or isinstance(rate, bool) or not isinstance(rate, (int, float))):
                raise ValueError
            rate = float(rate)
            if not math.isfinite(rate) or rate <= 0:
                raise ValueError
            rates[code] = rate
        if rates.get(base_currency) != 1.0:
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise RuntimeError("The currency provider returned invalid conversion rates") from None

    set_cache(cache_key, rates.copy(), ttl=CURRENCY_CACHE_TTL)
    return rates
