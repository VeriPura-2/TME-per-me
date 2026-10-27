"""Offline replay of real tariff responses saved on 27 Oct 2026 (trimmed)."""
import json
import os
import unittest

from vialibera import db
from vialibera.adapters.base import AdapterError
from vialibera.adapters.tariff import (UKTradeTariff, USITCHts, parse_cbsa_rows,
                                       parse_uk_commodity, parse_usitc_rows)

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


class UKParser(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads(load("uk_1902199090.json"))

    def test_pasta_italy_zero_duty_zero_vat(self):
        r = parse_uk_commodity(self.doc, "IT")
        self.assertEqual(r["duty_pct"], 0.0)
        self.assertEqual(r["import_vat_pct"], 0.0)
        self.assertEqual(r["duty_basis"], "preference")
        self.assertFalse(r["duty_has_specific_part"])

    def test_third_country_rate_is_kept_separately(self):
        r = parse_uk_commodity(self.doc, "IT")
        self.assertEqual(r["third_country_expression"], "6.00 % + 17.00 GBP / 100 kg")

    def test_unknown_origin_gets_no_duty_not_a_guess(self):
        r = parse_uk_commodity(self.doc, "ZZ")
        self.assertIsNone(r["duty_pct"])

    def test_specific_duty_part_is_flagged(self):
        r = parse_uk_commodity(self.doc, "TR")
        self.assertTrue(r["duty_has_specific_part"])

    def test_adapter_fetch_uses_parser(self):
        con = db.connect()
        out = UKTradeTariff(http=lambda url: json.dumps(self.doc)).call(con, "fetch", commodity_code="1902199090")
        self.assertEqual(out["data"]["parsed"]["duty_pct"], 0.0)

    def test_bad_structure_is_typed_error(self):
        con = db.connect()
        with self.assertRaises(AdapterError) as e:
            UKTradeTariff(http=lambda url: "{}").call(con, "fetch", commodity_code="1902199090")
        self.assertEqual(e.exception.kind, "unavailable")


class USITCParser(unittest.TestCase):
    def setUp(self):
        self.rows = json.loads(load("usitc_1509.20.json"))

    def test_evoo_retail_5_cents(self):
        self.assertEqual(parse_usitc_rows(self.rows, "1509.20.20")["cents_per_kg"], 5.0)

    def test_evoo_other_3_4_cents(self):
        self.assertEqual(parse_usitc_rows(self.rows, "1509.20.90")["cents_per_kg"], 3.4)

    def test_missing_code_returns_none(self):
        self.assertIsNone(parse_usitc_rows(self.rows, "9999.99"))

    def test_adapter_fetch(self):
        con = db.connect()
        out = USITCHts(http=lambda url: json.dumps(self.rows)).call(con, "fetch", code="1509.20.90")
        self.assertEqual(out["data"]["parsed"]["cents_per_kg"], 3.4)

    def test_non_list_is_typed_error(self):
        con = db.connect()
        with self.assertRaises(AdapterError):
            USITCHts(http=lambda url: "{}").call(con, "fetch", code="1509.20.90")


class CBSAParser(unittest.TestCase):
    def test_parmesan_rows(self):
        rows = parse_cbsa_rows(load("cbsa_ch04_trimmed.html"), "0406.90.9")
        by = {r["item"]: r for r in rows}
        self.assertEqual(by["0406.90.93"]["mfn"], "3.32¢/kg")
        self.assertTrue(by["0406.90.93"]["ceta_in_preference_list"])
        self.assertFalse(by["0406.90.94"]["ceta_in_preference_list"])
        self.assertTrue(by["0406.90.94"]["mfn"].startswith("245.5%"))


if __name__ == "__main__":
    unittest.main()
