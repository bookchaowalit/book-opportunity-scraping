"""Fixture-replay tests for the JSON API sources (no network)."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "opportunities"))

import scrape_defi_yields  # noqa: E402
import scrape_money_opportunities as money  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class HackerNewsTests(unittest.TestCase):
    def setUp(self):
        self.data = _load("hn_items.json")

    def _fake_get(self, url, **_kwargs):
        if url.endswith("topstories.json"):
            return FakeResponse(self.data["topstories"])
        story_id = url.rsplit("/", 1)[-1].removesuffix(".json")
        return FakeResponse(self.data["items"].get(story_id))

    def test_keeps_only_relevant_high_score_stories(self):
        with patch.object(money.httpx, "get", side_effect=self._fake_get):
            rows = money.scrape_hackernews()
        titles = [row["title"] for row in rows]
        # "said" must not count as "ai"; jobs and low-score stories are dropped.
        self.assertEqual(
            titles,
            ["Show HN: An AI tool that automates invoices", "Building a SaaS business on weekends"],
        )
        self.assertEqual(rows[0]["category"], "ai-content")
        self.assertEqual(rows[1]["category"], "trending-products")
        # Stories without an external URL link to the HN discussion.
        self.assertEqual(rows[1]["url"], "https://news.ycombinator.com/item?id=5")
        self.assertTrue(all(row["trend_score"] <= 95 for row in rows))

    def test_top_list_failure_returns_empty(self):
        with patch.object(money.httpx, "get", return_value=FakeResponse(None, status=503)):
            self.assertEqual(money.scrape_hackernews(), [])


class GitHubTrendingTests(unittest.TestCase):
    def test_filters_by_whole_word_keywords(self):
        with patch.object(money.httpx, "get", return_value=FakeResponse(_load("github_search.json"))):
            rows = money.scrape_github_trending()
        self.assertEqual([row["url"] for row in rows], [
            "https://github.com/acme/agent-kit",
            "https://github.com/acme/shop-scraper",
        ])
        self.assertEqual(rows[0]["category"], "ai-content")
        self.assertEqual(rows[0]["trend_score"], 90)
        self.assertEqual(rows[1]["title"], "acme/shop-scraper: ")

    def test_rate_limited_returns_empty(self):
        with patch.object(money.httpx, "get", return_value=FakeResponse({}, status=403)):
            self.assertEqual(money.scrape_github_trending(), [])


class DeFiYieldTests(unittest.TestCase):
    def setUp(self):
        with patch.object(scrape_defi_yields.httpx, "get", return_value=FakeResponse(_load("defillama_pools.json"))):
            self.pools = scrape_defi_yields.fetch_pools()

    def test_filter_drops_small_tvl_suspicious_apy_and_nulls(self):
        kept = scrape_defi_yields.filter_pools(self.pools, chains=[], min_apy=5.0)
        self.assertEqual([p["pool"] for p in kept], ["p-stable", "p-new", "p-spike"])
        eth_only = scrape_defi_yields.filter_pools(self.pools, chains=["Ethereum"], min_apy=5.0, categories=["Lending"])
        self.assertEqual([p["pool"] for p in eth_only], ["p-stable"])

    def test_stablecoin_detection_tolerates_missing_symbol(self):
        stable = scrape_defi_yields.detect_stablecoin_pools(self.pools)
        self.assertEqual([p["pool"] for p in stable], ["p-stable", "p-small", "p-spike"])

    def test_new_pool_and_apy_spike_detection(self):
        kept = scrape_defi_yields.filter_pools(self.pools, chains=[], min_apy=5.0)
        found = scrape_defi_yields.detect_opportunities(kept, {"p-stable": 8.0, "p-spike": 10.0})
        self.assertEqual([(o["type"], o["pool"]["pool"]) for o in found], [
            ("NEW_HIGH_YIELD", "p-new"),
            ("APY_SPIKE", "p-spike"),
        ])

    def test_fetch_failure_returns_empty_list(self):
        with patch.object(scrape_defi_yields.httpx, "get", return_value=FakeResponse({}, status=500)):
            self.assertEqual(scrape_defi_yields.fetch_pools(), [])


if __name__ == "__main__":
    unittest.main()
