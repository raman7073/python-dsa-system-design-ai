import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from services.cache import clear_cache
from services.currency import CURRENCY_CACHE_TTL, fetch_currency_rates


class CurrencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        clear_cache()
        self.addCleanup(clear_cache)
        self.requests = []
        self.response = httpx.Response(200, json={
            "result": "success", "base_code": "USD",
            "conversion_rates": {"USD": 1, "INR": 83.5},
        })
        real_client = httpx.AsyncClient

        def handler(request):
            self.requests.append(request)
            if isinstance(self.response, Exception):
                raise self.response
            return self.response

        client_patch = patch("services.currency.httpx.AsyncClient", side_effect=lambda **kw:
                             real_client(transport=httpx.MockTransport(handler), **kw))
        client_patch.start()
        self.addCleanup(client_patch.stop)
        key_patch = patch.dict("os.environ", {"CURRENCY_API_KEY": "test-key"})
        key_patch.start()
        self.addCleanup(key_patch.stop)

    async def test_cache_normalization_expiry_and_copy(self):
        with patch("services.cache.time.time", return_value=1000) as clock:
            rates = await fetch_currency_rates(" usd ")
            self.assertEqual(rates, {"USD": 1.0, "INR": 83.5})
            rates["INR"] = 0
            self.assertEqual((await fetch_currency_rates("USD"))["INR"], 83.5)
            self.assertEqual(len(self.requests), 1)
            self.assertTrue(self.requests[0].url.path.endswith("/latest/USD"))
            clock.return_value += CURRENCY_CACHE_TTL + 1
            await fetch_currency_rates("USD")
            self.assertEqual(len(self.requests), 2)

    async def test_invalid_input_and_missing_key(self):
        for code in ("", "US", "123", "USD/EUR", "€UR"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                await fetch_currency_rates(code)
        with patch.dict("os.environ", {"CURRENCY_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "not configured"):
                await fetch_currency_rates("USD")
        self.assertEqual(self.requests, [])

    async def test_provider_errors_are_not_cached(self):
        for error, expected in (("unsupported-code", ValueError),
                                ("invalid-key", RuntimeError),
                                ("quota-reached", RuntimeError)):
            self.response = httpx.Response(400, json={"result": "error", "error-type": error})
            for _ in range(2):
                with self.subTest(error=error), self.assertRaises(expected):
                    await fetch_currency_rates("USD")
        self.assertEqual(len(self.requests), 6)

    async def test_invalid_responses(self):
        for response in (
            httpx.Response(503, text="Unavailable"),
            httpx.Response(200, json=[]),
            httpx.Response(200, json={"result": "success", "base_code": "EUR",
                                     "conversion_rates": {"EUR": 1}}),
            *[httpx.Response(200, json={"result": "success", "base_code": "USD",
                                       "conversion_rates": {"USD": 1, "INR": rate}})
              for rate in (0, -1, True, "bad", None)],
        ):
            self.response = response
            with self.assertRaises(RuntimeError):
                await fetch_currency_rates("USD")

    async def test_timeout_does_not_expose_key(self):
        self.response = httpx.ReadTimeout("secret-key")
        with self.assertRaises(RuntimeError) as caught:
            await fetch_currency_rates("USD")
        self.assertNotIn("secret-key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
