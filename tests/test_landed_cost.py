"""B3 (22 Nov 2026): landed cost estimate from the exporter's numbers plus the official duty."""
import json
import os
import tempfile
import unittest

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
os.environ.setdefault("DB_PATH", ":memory:")
from vialibera import app, landed_cost, tariff_watch
from test_start_form import user


class Parse(unittest.TestCase):
    def test_only_plain_percentages_and_free_are_rates(self):
        self.assertEqual(landed_cost.duty_rate("6.00%"), 6.0)
        self.assertEqual(landed_cost.duty_rate("4 %"), 4.0)
        self.assertEqual(landed_cost.duty_rate("Free"), 0.0)
        self.assertIsNone(landed_cost.duty_rate("5 cents/kg"))
        self.assertIsNone(landed_cost.duty_rate("10% + 5 GBP/100kg"))


class Estimate(unittest.TestCase):
    def setUp(self):
        c = app.con()
        c.execute("DELETE FROM duty_snapshots")
        for ref, *_ in tariff_watch.LINES:
            v = {"eu_rate": "0.00%", "normal_rate": "6.00%", "vat": "20%"} if ref.startswith("UK") else \
                {"general_rate": "5 cents/kg"} if ref.startswith("US") else {"ceta_rate": "Free", "mfn_rate": "4%"}
            c.execute("INSERT INTO duty_snapshots(ref, value, checked_at) VALUES (?,?,?)", (ref, json.dumps(v), "2026-11-20T06:00:00+00:00"))
        c.commit()

    n = 0

    def run_case(self, country, **kw):
        Estimate.n += 1
        who = user("lc-%s-%d" % (country, Estimate.n))
        cid = app.handle_start({"category": "pasta" if country != "USA" else "olive oil", "country": country}, who)[1]["case_id"]
        ch = app.handle_tools("/tools/landed_choices", {"case_id": cid}, who)[1]
        return ch, app.handle_tools("/tools/landed_cost", {"case_id": cid, **kw}, who)

    def test_percent_duty_on_goods_value_only_and_vat_is_not_a_choice(self):
        ch, (code, out) = self.run_case("UK", goods="1000", freight="200", insurance="10", other="0", units="100")
        self.assertNotIn("Import VAT", [c["label"]["en"] for c in ch["choices"]])
        normal = next(c["id"] for c in ch["choices"] if c["value"] == "6.00%")
        _, (code, out) = self.run_case("UK", goods="1000", freight="200", insurance="10", other="0", units="100", line=normal)
        self.assertEqual((out["duty"], out["total"], out["per_unit"], out["duty_mode"]), (60.0, 1270.0, 12.7, "percent"))
        self.assertIn("EU origin", out["limit"]["en"])

    def test_specific_duty_is_not_applied(self):
        _, (code, out) = self.run_case("USA", goods="1000", freight="300", insurance="0", other="0", units="0")
        self.assertEqual((out["duty"], out["duty_mode"], out["per_unit"]), (0.0, "not_percent", None))
        self.assertEqual(out["line"]["value"], "5 cents/kg")

    def test_eu_has_no_customs_duty(self):
        ch, (code, out) = self.run_case("Germany", goods="500", freight="50", insurance="0", other="10", units="10")
        self.assertTrue(ch["eu"])
        self.assertEqual((out["duty_mode"], out["total"], out["per_unit"]), ("eu", 560.0, 56.0))

    def test_bad_numbers_and_outsiders(self):
        _, (code, _) = self.run_case("UK", goods="", freight="1")
        self.assertEqual(code, 400)
        _, (code, _) = self.run_case("UK", goods="-5")
        self.assertEqual(code, 400)
        who = user("lc-own")
        cid = app.handle_start({"category": "pasta", "country": "UK"}, who)[1]["case_id"]
        self.assertEqual(app.handle_tools("/tools/landed_cost", {"case_id": cid, "goods": "1"}, user("lc-stranger"))[0], 404)
