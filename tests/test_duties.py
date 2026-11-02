import json
import os
import unittest

from vialibera import db, duties, tariff_watch
from vialibera.adapters.tariff import pct, uk_duties, us_general

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


def case(cat, country):
    return {"id": None, "product": {"category": cat}, "market": {"country": country}}


def store(con, ref, value):
    con.execute("INSERT INTO duty_snapshots(ref, value, checked_at) VALUES (?,?,?)", (ref, json.dumps(value), "2026-11-02T06:00:00+00:00"))


class Lanes(unittest.TestCase):
    """Clients see the duties for every product on every lane (2 Nov 2026)."""

    def setUp(self):
        self.con = db.connect()
        for ref, *_ in tariff_watch.LINES:
            store(self.con, ref, {"eu_rate": "0.00%", "normal_rate": "6.00%"} if ref.startswith(("UK", "CH"))
                  else {"general_rate": "Free"} if ref.startswith("US") else {"ceta_rate": "Free", "mfn_rate": "4%"})

    def test_every_non_eu_lane_has_duties(self):
        for cat in ("pasta", "wine", "olive oil", "cheese and dairy"):
            for country in ("UK", "USA", "Canada", "Switzerland"):
                out = duties.for_case(self.con, case(cat, country))
                self.assertTrue(out["groups"], (cat, country))
                self.assertIn("en", out["limit"])
                self.assertTrue(out["source"].startswith("https://"))
                for g in out["groups"]:
                    self.assertTrue(g["description"]["it"] and g["description"]["en"])

    def test_eu_lanes_have_no_customs_duty(self):
        for country in ("Germany", "France", "Spain", "Netherlands", "Belgium", "Austria"):
            out = duties.for_case(self.con, case("wine", country))
            self.assertTrue(out["eu"])
            self.assertIn("duty-free", out["note"]["en"])

    def test_both_pastas_shown(self):
        out = duties.for_case(self.con, case("pasta", "UK"))
        self.assertEqual({g["code"] for g in out["groups"]}, {"1902199090", "1902110090"})

    def test_labels_follow_the_stored_values(self):
        out = duties.for_case(self.con, case("cheese and dairy", "Canada"))
        labels = [l["label"]["en"] for l in out["groups"][0]["lines"]]
        self.assertEqual(labels, ["With EU origin (CETA)", "Without proof of EU origin (MFN)"])

    def test_not_read_yet_is_pending(self):
        self.assertTrue(duties.for_case(db.connect(), case("pasta", "UK"))["pending"])

    def test_outside_wave1(self):
        self.assertIsNone(duties.for_case(self.con, case("spirits", "UK")))

    def test_every_line_has_an_italian_description(self):
        for ref, *_ in tariff_watch.LINES:
            self.assertIn(ref, tariff_watch.DESC_IT)
