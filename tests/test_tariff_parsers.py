"""Offline tests: parsers replay real responses saved on 27 Oct 2026."""
import json
import os
import unittest

from vialibera import db
from vialibera.adapters.tariff import UKTradeTariff, USITCHts, parse_uk, parse_usitc

FX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


class Parsers(unittest.TestCase):
    def test_uk_pasta_italy(self):
        p = parse_uk(json.loads(load("uk_1902199090_IT.json")))
        self.assertEqual(p["duty_pct"], 0.0)
        self.assertTrue(p["duty_is_simple_pct"])
        self.assertEqual(p["duty_basis"], "preference")
        self.assertEqual(p["import_vat_pct"], 0.0)

    def test_uk_empty_doc(self):
        p = parse_uk({})
        self.assertIsNone(p["duty_pct"])
        self.assertIsNone(p["import_vat_pct"])

    def test_usitc_retail(self):
        p = parse_usitc(json.loads(load("usitc_1509_20.json")), "1509.20.20")
        self.assertEqual(p["cents_per_kg"], 5.0)

    def test_usitc_other(self):
        p = parse_usitc(json.loads(load("usitc_1509_20.json")), "1509.20.90")
        self.assertEqual(p["cents_per_kg"], 3.4)

    def test_usitc_missing_code(self):
        self.assertIsNone(parse_usitc(json.loads(load("usitc_1509_20.json")), "9999.99"))

    def test_adapters_end_to_end_offline(self):
        con = db.connect()
        uk = UKTradeTariff(http=lambda url: load("uk_1902199090_IT.json"))
        out = uk.call(con, "fetch", commodity_code="1902199090", origin="IT")
        self.assertIn("filter%5Bgeographical_area_id%5D=IT", out["source"])
        self.assertEqual(out["data"]["parsed"]["import_vat_pct"], 0.0)
        us = USITCHts(http=lambda url: load("usitc_1509_20.json"))
        out = us.call(con, "fetch", code="1509.20.20")
        self.assertEqual(out["data"]["parsed"]["cents_per_kg"], 5.0)
        self.assertEqual(uk.mode, "stub")
        self.assertEqual(us.mode, "stub")


if __name__ == "__main__":
    unittest.main()
