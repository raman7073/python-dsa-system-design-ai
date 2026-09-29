import asyncio
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from main import app
from model import TravelRequestModel, CustomWeatherResponse
from routes.stream import stream_travel_plan


def parse_events(body):
    return [(lines[0][7:], json.loads(lines[1][6:]))
            for block in body.strip().split("\n\n")
            if (lines := block.splitlines()) and lines[0].startswith("event: ")]


class StreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.travel = TravelRequestModel(
            destination="Delhi", start_date=date.today(), end_date=date.today()
        )

    async def test_results_stream_before_other_service_finishes_and_cleanup(self):
        weather_started = asyncio.Event()
        weather_cancelled = asyncio.Event()

        async def weather(**kwargs):
            weather_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                weather_cancelled.set()

        async def currency(**kwargs):
            await weather_started.wait()
            return {"INR": 1.0}

        with patch("routes.stream.fetch_weather", side_effect=weather), patch(
            "routes.stream.fetch_currency_rates", side_effect=currency
        ):
            response = await stream_travel_plan(self.travel)
            iterator = response.body_iterator
            try:
                first = await asyncio.wait_for(iterator.__anext__(), 2)
                self.assertEqual(parse_events(first), [("currency", {"INR": 1.0})])
            finally:
                await iterator.aclose()
            self.assertTrue(weather_cancelled.is_set())

    async def test_registered_endpoint_serializes_models(self):
        forecast = CustomWeatherResponse(
            date=date.today().isoformat(), condition="Rain\nShowers",
            temperature_high=30, temperature_low=20, humidity=60, rain_chance=70,
        )
        with patch("routes.stream.fetch_weather", return_value=[forecast]), patch(
            "routes.stream.fetch_currency_rates", return_value={"INR": 1.0}
        ), TestClient(app) as client:
            response = client.post("/stream/", json=self.travel.model_dump(mode="json"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(response.headers["cache-control"], "no-cache")
        events = parse_events(response.text)
        self.assertEqual(events[-1], ("done", {"success": True}))
        self.assertEqual(dict(events)["weather"], [forecast.model_dump()])
        self.assertEqual(dict(events)["currency"], {"INR": 1.0})

    async def test_service_errors_preserve_other_result(self):
        for error, status in [(ValueError("Invalid currency"), 400),
                              (RuntimeError("Provider unavailable"), 502),
                              (Exception("secret"), 500)]:
            with self.subTest(status=status), patch(
                "routes.stream.fetch_weather", return_value=[]
            ), patch("routes.stream.fetch_currency_rates", side_effect=error):
                response = await stream_travel_plan(self.travel)
                events = parse_events("".join([chunk async for chunk in response.body_iterator]))
            self.assertEqual(dict(events)["weather"], [])
            self.assertEqual(dict(events)["error"]["source"], "currency")
            self.assertEqual(dict(events)["error"]["status_code"], status)
            self.assertNotIn("secret", str(events))
            self.assertEqual(events[-1], ("done", {"success": False}))

    async def test_invalid_dates_rejected_before_streaming(self):
        with patch("routes.stream.fetch_weather") as weather, patch(
            "routes.stream.fetch_currency_rates"
        ) as currency, TestClient(app) as client:
            for offset in (-1, 14):
                payload = self.travel.model_dump(mode="json")
                payload["end_date"] = (date.today() + timedelta(days=offset)).isoformat()
                response = client.post("/stream/", json=payload)
                self.assertEqual(response.status_code, 400)
            weather.assert_not_called()
            currency.assert_not_called()


if __name__ == "__main__":
    unittest.main()
