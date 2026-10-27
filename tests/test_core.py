import json
import unittest

from vialibera import db, gates
from vialibera.adapters.base import AdapterError
from vialibera.adapters.tariff import UKTradeTariff, USITCHts, http_get

MENU = {"tariff_lookup": {"price_cents": None}, "core_check": {"price_cents": 5000, "compliance": True},
        "label_review": {"price_cents": 3000}}


class Gates(unittest.TestCase):
    def setUp(self):
        self.con = db.connect()
        self.case = db.create_case(self.con, 1)

    def test_price_only_from_menu(self):
        with self.assertRaises(gates.GateError):
            gates.add_item(self.con, self.case, "made_up_item", MENU)
        iid = gates.add_item(self.con, self.case, "label_review", MENU)
        self.assertEqual(gates._item(self.con, iid)["price_cents"], 3000)

    def test_unpriced_item_cannot_be_paid(self):
        iid = gates.add_item(self.con, self.case, "tariff_lookup", MENU)
        with self.assertRaises(gates.GateError):
            gates.set_state(self.con, iid, "paid", "system")

    def test_no_work_before_payment(self):
        iid = gates.add_item(self.con, self.case, "label_review", MENU)
        with self.assertRaises(gates.GateError):
            gates.set_state(self.con, iid, "in progress", "staff")

    def test_agent_cannot_confirm(self):
        iid = gates.add_item(self.con, self.case, "label_review", MENU)
        for s in ("paid", "in progress", "delivered"):
            gates.set_state(self.con, iid, s, "system")
        with self.assertRaises(gates.GateError):
            gates.confirm_item(self.con, iid, "agent", 1)
        gates.confirm_item(self.con, iid, "client:thomas", 1)
        self.assertEqual(gates._item(self.con, iid)["state"], "client confirmed")
        self.assertEqual(self.con.execute("SELECT COUNT(*) AS n FROM confirmations").fetchone()["n"], 1)

    def test_compliance_needs_review(self):
        iid = gates.add_item(self.con, self.case, "core_check", MENU)
        for s in ("paid", "in progress"):
            gates.set_state(self.con, iid, s, "system")
        with self.assertRaises(gates.GateError):
            gates.set_state(self.con, iid, "delivered", "staff")
        gates.set_state(self.con, iid, "review", "staff")
        gates.set_state(self.con, iid, "delivered", "staff")

    def test_case_file_merge_and_log(self):
        db.case_write(self.con, self.case, "product", {"name": "pasta"})
        db.case_write(self.con, self.case, "product", {"hs": "1902"})
        self.assertEqual(db.case_read(self.con, self.case)["product"], {"name": "pasta", "hs": "1902"})
        kinds = [r["kind"] for r in self.con.execute("SELECT kind FROM events")]
        self.assertEqual(kinds.count("case_updated"), 2)


class Adapters(unittest.TestCase):
    def setUp(self):
        self.con = db.connect()

    def test_envelope_fields_and_logging(self):
        a = UKTradeTariff(http=lambda url: json.dumps({"ok": True}))
        out = a.call(self.con, "fetch", commodity_code="1902199090")
        for k in ("source", "retrieved_at", "provider_version", "confidence", "raw_ref"):
            self.assertIn(k, out)
        self.assertEqual(self.con.execute("SELECT COUNT(*) AS n FROM usage_events").fetchone()["n"], 1)
        self.assertEqual(self.con.execute("SELECT COUNT(*) AS n FROM raw_responses").fetchone()["n"], 1)

    def test_invalid_input_and_not_supported(self):
        a = UKTradeTariff(http=lambda url: "{}")
        with self.assertRaises(AdapterError) as e:
            a.call(self.con, "fetch", commodity_code="1902")
        self.assertEqual(e.exception.kind, "invalid_input")
        with self.assertRaises(AdapterError) as e:
            a.call(self.con, "cancel", provider_ref="x")
        self.assertEqual(e.exception.kind, "not_supported")

    def test_unavailable_is_typed(self):
        def boom(url):
            raise AdapterError("unavailable", "blocked")
        with self.assertRaises(AdapterError) as e:
            USITCHts(http=boom).call(self.con, "fetch", code="1509.20")
        self.assertEqual(e.exception.kind, "unavailable")


if __name__ == "__main__":
    unittest.main()
