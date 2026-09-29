import asyncio
import sys
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from main import app
from services.cache import clear_cache
from services.weather import WEATHER_CACHE_TTL


class PlannerTests(unittest.TestCase):
    def setUp(self):
        clear_cache()
        self.addCleanup(clear_cache)
        self.client = TestClient(app)
        self.today = date.today()
        currency_patch = patch("routes.planner.fetch_currency_rates", return_value={"INR": 1.0})
        self.currency_fetch = currency_patch.start()
        self.addCleanup(currency_patch.stop)

    def request(self, start=1, end=6, destination="delhi", base_currency=None):
        payload = {
            "destination": destination,
            "start_date": (self.today + timedelta(days=start)).isoformat(),
            "end_date": (self.today + timedelta(days=end)).isoformat(),
        }
        if base_currency is not None:
            payload["base_currency"] = base_currency
        return self.client.post("/plan/", json=payload)

    def test_currency_rates_in_response(self):
        with patch("routes.planner.fetch_weather", return_value=[]):
            for base in (None, "USD"):
                with self.subTest(base=base):
                    self.currency_fetch.reset_mock()
                    rates = {base or "INR": 1.0, "EUR": 0.9}
                    self.currency_fetch.return_value = rates
                    response = self.request(base_currency=base)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["currency_data"], rates)
                    self.assertEqual(response.json()["weather_data"], [])
                    self.currency_fetch.assert_awaited_once_with(base_currency=base or "INR")

    def test_weather_and_currency_run_concurrently(self):
        async def check():
            from model import TravelRequestModel
            from routes.planner import create_travel_plan

            weather_started = asyncio.Event()
            currency_started = asyncio.Event()

            async def weather(**kwargs):
                weather_started.set()
                await currency_started.wait()
                return []

            async def currency(**kwargs):
                currency_started.set()
                await weather_started.wait()
                return {"INR": 1.0}

            with patch("routes.planner.fetch_weather", side_effect=weather):
                self.currency_fetch.side_effect = currency
                result = await asyncio.wait_for(create_travel_plan(TravelRequestModel(
                    destination="delhi", start_date=self.today, end_date=self.today
                )), timeout=2)
            self.assertEqual(result["weather_data"], [])
            self.assertEqual(result["currency_data"], {"INR": 1.0})

        asyncio.run(check())

    def test_currency_errors_have_json_responses(self):
        with patch("routes.planner.fetch_weather", return_value=[]):
            for error, status in [(ValueError("Unsupported base currency"), 400),
                                  (RuntimeError("Currency provider unavailable"), 502)]:
                with self.subTest(status=status):
                    self.currency_fetch.side_effect = error
                    response = self.request()
                    self.assertEqual(response.status_code, status)
                    self.assertEqual(response.json()["detail"], str(error))

    def test_provider_calendar_one_day_behind(self):
        real_client = httpx.AsyncClient
        requests = []
        now = time.time()

        def handler(request):
            requests.append(request)
            days = int(request.url.params["days"])
            entries = [{
                "date": (self.today + timedelta(days=i - 1)).isoformat(),
                "day": {"condition": {"text": "Sunny"}, "maxtemp_c": 30,
                        "mintemp_c": 20, "avghumidity": 60,
                        "daily_chance_of_rain": 10},
            } for i in range(days)]
            return httpx.Response(200, json={"forecast": {"forecastday": entries}})

        with patch("services.weather.os.getenv", return_value="test-key"), patch(
            "services.weather.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        ), patch("services.cache.time.time", return_value=now) as clock:
            response = self.request()
            cached_response = self.request(destination=" Delhi ")
            self.assertEqual(cached_response.json(), response.json())
            self.assertEqual(len(requests), 1)

            clock.return_value = now + WEATHER_CACHE_TTL + 1
            self.assertEqual(self.request().json(), response.json())
            self.assertEqual(len(requests), 2)

            self.assertEqual(self.request(1, 2).status_code, 200)
            self.assertEqual(len(requests), 3)
            self.assertEqual(self.request(destination="Mumbai").status_code, 200)
            self.assertEqual(len(requests), 4)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["date"] for item in response.json()["weather_data"]],
            [(self.today + timedelta(days=i)).isoformat() for i in range(1, 7)],
        )

    def test_service_errors_have_json_responses(self):
        for error, status in [(ValueError("Invalid dates"), 400),
                              (RuntimeError("Provider unavailable"), 502)]:
            with self.subTest(status=status), patch(
                "routes.planner.fetch_weather", side_effect=error
            ):
                response = self.request()
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["detail"], str(error))

    def test_provider_failures_are_not_cached(self):
        real_client = httpx.AsyncClient
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(503)

        with patch("services.weather.os.getenv", return_value="test-key"), patch(
            "services.weather.httpx.AsyncClient",
            side_effect=lambda **kwargs: real_client(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        ):
            self.assertEqual(self.request().status_code, 502)
            self.assertEqual(self.request().status_code, 502)
        self.assertEqual(len(requests), 2)

    def test_inclusive_trip_length(self):
        with patch("routes.planner.fetch_weather", return_value=[]) as fetch:
            self.assertEqual(self.request(0, 0).status_code, 200)
            fetch.reset_mock()
            self.currency_fetch.reset_mock()
            self.assertEqual(self.request(0, 14).status_code, 400)
            fetch.assert_not_called()
            self.currency_fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
