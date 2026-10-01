"""The shared scraper dashboard must never be overwritten after a failed read."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "opportunities"))

import scrape_money_opportunities as money  # noqa: E402

HEALTH = [{"source": "hn", "status": "ok", "items": 1, "duration": 0.1}]
OPPS = [{"title": "Idea", "trend_score": 80, "category": "ai", "source": "hn", "url": "https://x.test"}]


class DashboardMergeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root / "data" / "briefings" / "scraper_dashboard.json"
        self.path.parent.mkdir(parents=True)
        for p in (patch.object(money, "ROOT", self.root), patch("builtins.print")):
            p.start()
            self.addCleanup(p.stop)

    def test_unreadable_dashboard_is_left_untouched(self):
        broken = '{"sources": {"jobs": {"rows": 12}}, '  # truncated by a concurrent writer
        self.path.write_text(broken, encoding="utf-8")
        money.generate_dashboard_json(HEALTH, OPPS, 1)
        self.assertEqual(self.path.read_text(encoding="utf-8"), broken)

    def test_other_sources_are_preserved(self):
        self.path.write_text(json.dumps({"sources": {"jobs": {"rows": 12}}}), encoding="utf-8")
        money.generate_dashboard_json(HEALTH, OPPS, 1)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["sources"]["jobs"], {"rows": 12})
        self.assertEqual(data["sources"]["opportunities"]["rows"], 1)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["scraper_dashboard.json"])


if __name__ == "__main__":
    unittest.main()
