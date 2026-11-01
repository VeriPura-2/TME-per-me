import json
import os
import unittest

from vialibera import db, duties
from vialibera.adapters.tariff import UKTradeTariff, USITCHts, pct, uk_duties, us_general

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FX, name)) as f:
        return f.read()


class Parsers(unittest.TestCase):
    """Saved live responses from 1 Nov 2026, matching the known-answer pack."""

    def test_uk_pasta_from_eu(self):
        d = uk_duties(json.loads(load("uk_1902199090.json")))
        self.assertEqual(pct(d["preferential_eu"]), 0.0)
        self.assertEqual(pct(d["vat"]), 0.0)
        self.assertEqual(d["third_country"], "6.00% + £17.00 / 100 kg")

    def test_us_olive_oil(self):
        self.assertEqual(us_general(json.loads(load("us_1509.20.20.json")), "1509.20.20")["normalised"], "5 cents/kg")
        self.assertEqual(us_general(json.loads(load("us_1509.20.90.json")), "1509.20.90")["normalised"], "3.4 cents/kg")
        self.assertIsNone(us_general(json.loads(load("us_1509.20.90.json")), "9999.99.99"))


def case(cat, country, **prod):
    return {"id": None, "product": {"category": cat, **prod}, "market": {"country": country}}


class Lanes(unittest.TestCase):
    def setUp(self):
        self.con = db.connect()
        self.calls = []

        def uk_http(url):
            self.calls.append(url)
            return load("uk_1902199090.json")

        def us_http(url):
            self.calls.append(url)
            return load("us_" + url.rsplit("=", 1)[1] + ".json")
        self.uk, self.us = UKTradeTariff(http=uk_http), USITCHts(http=us_http)

    def test_pasta_uk(self):
        out = duties.for_case(self.con, case("pasta", "UK"), uk=self.uk)
        self.assertTrue(out["zero_duty"])
        self.assertTrue(out["source"].startswith("https://www.trade-tariff.service.gov.uk/"))
        self.assertIn("origin", out["limit"]["en"])

    def test_cached_for_a_day(self):
        duties.for_case(self.con, case("pasta", "UK"), uk=self.uk)
        duties.for_case(self.con, case("pasta", "UK"), uk=self.uk)
        self.assertEqual(len(self.calls), 1)

    def test_oil_us_shows_both_pack_sizes_and_the_limit(self):
        out = duties.for_case(self.con, case("olive oil", "USA"), us=self.us)
        self.assertEqual([l["value"] for l in out["lines"]], ["5 cents/kg", "3.4 cents/kg"])
        self.assertIn("chapter 99", out["limit"]["en"])

    def test_staff_flags(self):
        self.assertIn("staff", duties.for_case(self.con, case("cheese and dairy", "Canada")))
        self.assertIn("staff", duties.for_case(self.con, case("pasta", "UK", egg_wheat_type="durum with egg"), uk=self.uk))
        self.assertIsNone(duties.for_case(self.con, case("wine", "USA")))

    def test_service_down_is_reported_not_raised(self):
        out = duties.for_case(self.con, case("pasta", "UK"))  # network is off in tests
        self.assertEqual(out, {"unavailable": True})
