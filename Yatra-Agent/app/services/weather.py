import os
from datetime import date
from pathlib import Path

import httpx
from dotenv import load_dotenv

from model import CustomWeatherResponse
from services.cache import get_cache, set_cache

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

WEATHER_CACHE_TTL = 15 * 60


async def fetch_weather(
    destination: str,
    start_date: date,
    end_date: date
) -> list[CustomWeatherResponse]:
    """Return inclusive daily forecasts, with Celsius temperatures and percentages.

    Raises ValueError for invalid input and RuntimeError for configuration or
    provider failures, including incomplete forecast coverage.
    """
    destination = destination.strip()
    if not destination:
        raise ValueError("Destination cannot be empty")
    if start_date > end_date:
        raise ValueError("Start date cannot be after end date")

    today = date.today()
    forecast_days = (end_date - today).days + 1
    if start_date < today or forecast_days > 14:
        raise ValueError(
            "Weather forecasts are available only for today and the next 13 days")

    cache_key = f"weather:{destination.casefold()}:{start_date.isoformat()}:{end_date.isoformat()}"
    cached = get_cache(cache_key)
    if cached is not None:
        return [CustomWeatherResponse(**item) for item in cached["forecasts"]]

    api_key = os.getenv("WEATHER_API_KEY")
    if not api_key or not api_key.strip():
        raise RuntimeError("WEATHER_API_KEY is not configured")
    # days = min((end_date-start_date).days, 14)
    #  print(days)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.weatherapi.com/v1/forecast.json",
                params={
                    "key": api_key,
                    "q": destination,
                    # Provider and server dates can differ. Request the full
                    # window and select the requested dates below.
                    "days": 14,
                    "aqi": "no",
                    "alerts": "no",
                },
            )
            response.raise_for_status()
    except httpx.HTTPError:
        # HTTP exceptions can contain the request URL and its secret API key.
        raise RuntimeError(
            "Unable to fetch weather from the weather provider") from None

    try:
        forecasts = {}
        for entry in response.json()["forecast"]["forecastday"]:
            forecast_date = date.fromisoformat(entry["date"])
            if start_date <= forecast_date <= end_date:
                day = entry["day"]
                forecasts[forecast_date] = CustomWeatherResponse(
                    date=forecast_date.isoformat(),
                    condition=day["condition"]["text"],
                    temperature_high=day["maxtemp_c"],
                    temperature_low=day["mintemp_c"],
                    humidity=day["avghumidity"],
                    rain_chance=day["daily_chance_of_rain"],
                )
    except (KeyError, TypeError, ValueError):
        raise RuntimeError(
            "The weather provider returned invalid forecast data") from None

    if len(forecasts) != (end_date - start_date).days + 1:
        raise RuntimeError(
            "Weather forecasts are not available for every requested date "
            f"({start_date.isoformat()} to {end_date.isoformat()}). "
            "Try a shorter date range or check your weather API plan's forecast coverage."
        )

    result = [forecasts[day] for day in sorted(forecasts)]
    set_cache(
        cache_key,
        {"forecasts": [item.model_dump() for item in result]},
        ttl=WEATHER_CACHE_TTL,
    )
    return result
