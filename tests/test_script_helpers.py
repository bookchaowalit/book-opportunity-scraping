"""Offline tests for helper functions in the root scrape_* scripts."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scrape_fb_local
import scrape_flight_prices


class FlightRouteTests(unittest.TestCase):
    def test_routes_flag(self):
        self.assertEqual(
            scrape_flight_prices.parse_routes("bkk-sin, BKK-TYO,bad,-x"),
            [("BKK", "SIN"), ("BKK", "TYO")],
        )

    def test_origin_with_destinations(self):
        self.assertEqual(
            scrape_flight_prices.parse_routes(None, "cnx", "sin,hkg"),
            [("CNX", "SIN"), ("CNX", "HKG")],
        )

    def test_defaults_and_passthrough(self):
        self.assertEqual(scrape_flight_prices.parse_routes(None), list(scrape_flight_prices.DEFAULT_ROUTES))
        self.assertEqual(scrape_flight_prices.parse_routes([("BKK", "SIN")]), [("BKK", "SIN")])

    def test_outputs_stay_inside_the_repository(self):
        self.assertEqual(scrape_flight_prices.ROOT, ROOT)
        self.assertTrue(str(scrape_flight_prices.OUTPUT_DIR).startswith(str(ROOT / "data")))


class EmailPrivacyTests(unittest.TestCase):
    def test_mask_email_hides_local_part(self):
        self.assertEqual(scrape_fb_local.mask_email("jane.doe@company.co.th"), "j***@company.co.th")
        self.assertEqual(scrape_fb_local.mask_email("not-an-email"), "***")

    def test_contact_data_stays_inside_repository(self):
        self.assertEqual(scrape_fb_local.DATA_DIR, ROOT / "data")

    def test_extract_emails_skips_generic_and_placeholder_addresses(self):
        text = "Send CV to hr@acme.com or jane@acme.com, see test@example.com"
        self.assertEqual(scrape_fb_local.extract_emails_from_text(text), ["jane@acme.com"])


if __name__ == "__main__":
    unittest.main()
