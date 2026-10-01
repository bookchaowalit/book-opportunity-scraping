"""Regression tests for recurring cross-repo bug patterns."""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scrape_ai_tools  # noqa: E402
import scrape_defi_yields  # noqa: E402
import scrape_fb_local  # noqa: E402
import scrape_flight_prices  # noqa: E402
import scrape_seo_rankings  # noqa: E402
import scrape_stock_prices  # noqa: E402

sys.path.insert(0, str(ROOT / "opportunities"))
import scrape_money_opportunities as money  # noqa: E402


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


SPOOFS = [
    "https://evil.example/redirect?to={d}",
    "https://{d}.evil.example/x",
    "https://not{d}/x",
]


class HostMatchTests(unittest.TestCase):
    def test_host_matches_rejects_substring_lookalikes(self):
        for mod in (scrape_ai_tools, scrape_fb_local, scrape_seo_rankings, money):
            for domain in ("producthunt.com", "facebook.com"):
                self.assertTrue(mod.host_matches(f"https://www.{domain}/p/1", domain), mod.__name__)
                self.assertTrue(mod.host_matches(f"https://{domain}", domain), mod.__name__)
                for spoof in SPOOFS:
                    self.assertFalse(mod.host_matches(spoof.format(d=domain), domain), (mod.__name__, spoof))

    def test_seo_rank_counts_only_the_target_host(self):
        results = [
            {"url": "https://evil.example/?u=bookchaowalit.com", "title": "spoof"},
            {"url": "https://www.google.com/search?q=bookchaowalit.com", "title": "google"},
            {"url": "https://www.bookchaowalit.com/about", "title": "real"},
        ]
        with patch.object(scrape_seo_rankings, "google_search", return_value=results):
            ranking = scrape_seo_rankings.check_ranking("book", ["bookchaowalit.com"])
        self.assertEqual(ranking["best_rank"], 3)
        self.assertEqual([p["rank"] for p in ranking["all_positions"]], [3])

    def test_producthunt_search_keeps_only_producthunt_hosts(self):
        results = [
            {"title": "Spoof", "url": "https://evil.example/producthunt.com/posts/x"},
            {"title": "Real", "url": "https://www.producthunt.com/posts/real"},
        ]
        with patch.object(money, "ddg_search", return_value=results), patch("builtins.print"):
            found = money.scrape_producthunt_rss()
        self.assertEqual([o["title"] for o in found], ["Real"])

    def test_fb_search_keeps_only_facebook_links(self):
        html = (
            '<li class="b_algo"><h2><a href="https://evil.example/?next=facebook.com">Spoof</a></h2><p>x</p></li>'
            '<li class="b_algo"><h2><a href="https://www.facebook.com/groups/1/posts/2">Real</a></h2><p>y</p></li>'
        )

        class _HtmlResp:
            status_code = 200
            text = html

            def raise_for_status(self):
                return None

        with patch.object(scrape_fb_local.requests, "get", return_value=_HtmlResp()):
            found = scrape_fb_local.search_bing("q")
        self.assertEqual([t for t, _link, _s in found], ["Real"])


class _HtmlResp:
    status_code = 200

    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class SearchRedirectTests(unittest.TestCase):
    POST = "https://www.facebook.com/groups/1/posts/2?ref=share"

    def test_unwrap_search_href(self):
        from urllib.parse import quote

        ddg = "//duckduckgo.com/l/?uddg=" + quote(self.POST, safe="") + "&rut=abc"
        google = "/url?q=" + quote(self.POST, safe=":/") + "&sa=U&ved=x"
        self.assertEqual(scrape_fb_local.unwrap_search_href(ddg), self.POST)
        self.assertEqual(scrape_fb_local.unwrap_search_href(google), self.POST)
        self.assertEqual(scrape_fb_local.unwrap_search_href(self.POST), self.POST)
        # A redirect to a non-http target is not followed.
        self.assertEqual(
            scrape_fb_local.unwrap_search_href("/url?q=javascript:alert(1)"), "/url?q=javascript:alert(1)"
        )

    def test_duckduckgo_wrapped_facebook_links_are_kept_unwrapped(self):
        from urllib.parse import quote

        def item(target, title):
            href = "//duckduckgo.com/l/?uddg=" + quote(target, safe="") + "&rut=abc"
            return (
                f'<div class="result"><a class="result__a" href="{href}">{title}</a>'
                '<a class="result__snippet">s</a></div>'
            )

        html = item("https://evil.example/?next=facebook.com", "Spoof") + item(self.POST, "Real")
        with patch.object(scrape_fb_local.requests, "get", return_value=_HtmlResp(html)):
            found = scrape_fb_local.search_duckduckgo("q")
        self.assertEqual([(t, link) for t, link, _s in found], [("Real", self.POST)])

    def test_google_wrapped_facebook_links_are_kept_unwrapped(self):
        from urllib.parse import quote

        def item(target, title):
            href = "/url?q=" + quote(target, safe=":/") + "&amp;sa=U&amp;ved=x"
            return f'<div class="g"><a href="{href}"><h3>{title}</h3></a><div class="VwiC3b">s</div></div>'

        html = item("https://evil.example/facebook.com", "Spoof") + item(self.POST, "Real")
        with patch.object(scrape_fb_local.requests, "get", return_value=_HtmlResp(html)):
            found = scrape_fb_local.search_google("q")
        self.assertEqual([(t, link) for t, link, _s in found], [("Real", self.POST)])

    def test_seo_domain_with_www_prefix_matches_bare_host(self):
        self.assertTrue(scrape_seo_rankings.host_matches("https://bookchaowalit.com/a", "www.bookchaowalit.com"))
        self.assertTrue(scrape_seo_rankings.host_matches("https://www.bookchaowalit.com/a", "www.bookchaowalit.com"))
        self.assertFalse(scrape_seo_rankings.host_matches("https://evilbookchaowalit.com/", "www.bookchaowalit.com"))
        results = [{"url": "https://bookchaowalit.com/about", "title": "real"}]
        with patch.object(scrape_seo_rankings, "google_search", return_value=results):
            ranking = scrape_seo_rankings.check_ranking("book", ["www.bookchaowalit.com"])
        self.assertEqual(ranking["best_rank"], 1)


if __name__ == "__main__":
    unittest.main()
