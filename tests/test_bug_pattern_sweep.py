"""Regression tests for recurring cross-repo bug patterns."""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scrape_defi_yields  # noqa: E402
import scrape_fb_local  # noqa: E402
import scrape_flight_prices  # noqa: E402
import scrape_stock_prices  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _BangkokTZ:
    """Run with host TZ=Asia/Bangkok so host-local rendering would differ from UTC."""

    def __enter__(self):
        self.old = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Bangkok"
        time.tzset()

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.old
        time.tzset()


def _pool(pool_id, apy, tvl=1_000_000):
    return {"pool": pool_id, "chain": "Ethereum", "project": "x", "symbol": "USDC", "apy": apy, "tvlUsd": tvl}


class DefiNonFiniteTests(unittest.TestCase):
    def test_nan_and_inf_apy_or_tvl_are_rejected(self):
        pools = [
            _pool("nan-apy", float("nan")),
            _pool("inf-apy", float("inf")),
            _pool("nan-tvl", 10.0, float("nan")),
            _pool("str-nan", "NaN"),
            _pool("ok", 10.0),
        ]
        kept = scrape_defi_yields.filter_pools(pools, chains=[], min_apy=5.0)
        self.assertEqual([p["pool"] for p in kept], ["ok"])


class FlightDeterminismTests(unittest.TestCase):
    payload = {"data": [{
        "price": 3000,
        "route": [{"airline": a} for a in ("TG", "SQ", "FD", "VZ", "MH", "AK", "OD", "CX")],
        "dTime": 1_700_000_000,
        "aTime": 1_700_003_600,
        "deep_link": "https://example.test/f",
    }]}

    @unittest.skipUnless(hasattr(time, "tzset"), "needs time.tzset")
    def test_airlines_in_route_order_and_times_in_utc(self):
        with patch.object(scrape_flight_prices, "TEQUILA_API_KEY", "k"), \
                patch.object(scrape_flight_prices.httpx, "get", return_value=_Resp(self.payload)), \
                _BangkokTZ():
            flights = scrape_flight_prices.fetch_kiwi_tequila("BKK", "SIN", "01/01/2026", "02/01/2026")
        self.assertEqual(flights[0]["airline"], "TG,SQ,FD,VZ,MH,AK,OD,CX")
        self.assertEqual(flights[0]["departure"], "2023-11-14 22:13")
        self.assertEqual(flights[0]["return"], "2023-11-14 23:13")


@unittest.skipUnless(hasattr(time, "tzset"), "needs time.tzset")
class StockTimestampTests(unittest.TestCase):
    def test_market_time_rendered_in_utc(self):
        payload = {"chart": {"result": [{"meta": {
            "regularMarketPrice": 10.0, "chartPreviousClose": 9.0, "regularMarketTime": 1_700_000_000,
        }}]}}
        with patch.object(scrape_stock_prices.httpx, "get", return_value=_Resp(payload)), _BangkokTZ():
            quote = scrape_stock_prices.fetch_quote("AAPL")
        self.assertEqual(quote["timestamp"], "2023-11-14 22:13:20")


class EmailOrderTests(unittest.TestCase):
    def test_first_seen_order_is_kept(self):
        text = " ".join(f"person{i}@company{i}.co" for i in range(20))
        self.assertEqual(
            scrape_fb_local.extract_emails_from_text(text),
            [f"person{i}@company{i}.co" for i in range(20)],
        )


if __name__ == "__main__":
    unittest.main()
