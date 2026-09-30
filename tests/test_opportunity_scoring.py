"""Offline tests for the money-opportunity scoring and dedupe logic."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "opportunities"))

import scrape_money_opportunities as money


class KeywordTests(unittest.TestCase):
    def test_short_keywords_match_whole_words_only(self):
        self.assertTrue(money.has_keyword("New AI agent for sellers", ["ai"]))
        self.assertTrue(money.has_keyword("open-source ai-powered crm", ["ai"]))
        for text in ("He said it works", "Email marketing tips", "Thailand travel deals", "Paid survey"):
            self.assertFalse(money.has_keyword(text, ["ai"]), text)

    def test_long_keywords_keep_substring_matching(self):
        self.assertTrue(money.has_keyword("Workflow automations for Etsy", ["automation"]))
        self.assertFalse(money.has_keyword("", ["automation"]))


class ScoreTests(unittest.TestCase):
    def test_ai_boost_is_not_triggered_by_substrings(self):
        base = {"trend_score": 50, "competition_level": "medium"}
        self.assertEqual(money.score_opportunity({**base, "title": "Thailand hotel said"}), 50)
        self.assertEqual(money.score_opportunity({**base, "title": "AI invoice tool"}), 60)

    def test_score_is_clamped(self):
        self.assertEqual(money.score_opportunity({"title": "AI money", "trend_score": 99, "competition_level": "low"}), 100)
        self.assertEqual(money.score_opportunity({"title": "x", "trend_score": 5, "competition_level": "high"}), 0)


class DedupeTests(unittest.TestCase):
    def test_short_titles_do_not_merge_on_partial_overlap(self):
        self.assertFalse(money.fuzzy_title_match("Show HN", "Show HN: a new database engine"))
        self.assertTrue(money.fuzzy_title_match("Show HN", "show hn"))
        self.assertTrue(
            money.fuzzy_title_match("Sell printable planners on Etsy", "sell printable planners etsy 2026")
        )

    def test_cross_source_merge_keeps_highest_score(self):
        items = [
            {"title": "Printable planner bundle for Etsy", "url": "https://a.example/1", "trend_score": 70, "source": "Reddit", "notes": ""},
            {"title": "Other thing entirely here", "url": "https://b.example/2", "trend_score": 60, "source": "HN", "notes": ""},
            {"title": "Printable planner bundle Etsy sellers", "url": "https://c.example/3", "trend_score": 80, "source": "Etsy", "notes": ""},
            {"title": "Dup by url", "url": "https://b.example/2", "trend_score": 40, "source": "GitHub", "notes": ""},
        ]
        merged = money.deduplicate_cross_source(items)
        self.assertEqual(len(merged), 2)
        planner = next(item for item in merged if "Printable" in item["title"])
        self.assertEqual(planner["source"], "Etsy")
        self.assertEqual(planner["trend_score"], 83)
        other = next(item for item in merged if item["url"] == "https://b.example/2")
        self.assertEqual(other["trend_score"], 63)
        self.assertIn("Cross-source: HN, GitHub", other["notes"])


class StandaloneTests(unittest.TestCase):
    def test_imports_without_parent_checkout_and_keeps_db_disabled(self):
        self.assertEqual(money.REPO_ROOT, ROOT)
        if money.get_db_connection is None:
            self.assertFalse(money.DB_PATH.exists())
            self.assertFalse(money.init_action_tracker())


if __name__ == "__main__":
    unittest.main()
