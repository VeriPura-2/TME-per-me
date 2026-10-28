import os
import unittest
from types import SimpleNamespace as NS

os.environ["DB_PATH"] = ":memory:"
from vialibera import app, db, plans
from vialibera.sim import packet


def who(u):
    return {"user": u, "org": None, "roles": []}


def make_case(u, needs="tariff and duty | document check"):
    c = app.con()
    cid = db.create_case(c, 1, owner_sub=u)
    db.case_write(c, cid, "product", {"category": "wine", "name_brand": "Barolo X"})
    db.case_write(c, cid, "market", {"country": "USA", "needs": needs})
    c.commit()
    return cid


class JourneyTest(unittest.TestCase):
    def test_journey_is_simulated_and_labelled(self):
        cid = make_case("j1")
        code, out = app.handle_journey({"case_id": cid}, who("j1"))
        self.assertEqual(code, 200)
        self.assertTrue(out["required_docs"]["simulated"])
        self.assertTrue(out["packet"]["simulated"])
        self.assertEqual(out["plan"], "esplora")

    def test_other_users_cannot_see_the_case(self):
        cid = make_case("j2")
        self.assertEqual(app.handle_journey({"case_id": cid}, who("intruder"))[0], 404)

    def test_wine_gets_wine_specific_items(self):
        cid = make_case("j3")
        _, out = app.handle_journey({"case_id": cid}, who("j3"))
        ids = [i["id"] for i in out["required_docs"]["data"]["items"]]
        self.assertIn("wine_doc", ids)

    def test_dependencies_add_required_items_with_reason(self):
        items, why = packet.expand(["document_check"])
        self.assertEqual(items, ["tariff_lookup", "export_documents", "document_check"])
        self.assertEqual(why["export_documents"], ["document_check"])

    def test_plan_choice_changes_prices(self):
        cid = make_case("j4")
        a = app.handle_journey({"case_id": cid, "selected": ["label_check"]}, who("j4"))[1]["packet"]["data"]["total_cents"]
        app.handle_plan({"plan": "cresci"}, who("j4"))
        b = app.handle_journey({"case_id": cid, "selected": ["label_check"]}, who("j4"))[1]["packet"]["data"]["total_cents"]
        self.assertLess(b, a)

    def test_bad_plan_is_ignored(self):
        self.assertEqual(app.handle_plan({"plan": "gold"}, who("j5"))[1]["plan"], plans.DEFAULT)

    def test_simulated_payment_charges_nothing_and_logs(self):
        cid = make_case("j6")
        code, out = app.handle_simpay({"case_id": cid, "selected": ["tariff_lookup", "label_check"]}, who("j6"))
        self.assertEqual(code, 200)
        self.assertFalse(out["payment"]["data"]["charged"])
        self.assertTrue(out["payment"]["simulated"])
        row = app.con().execute("SELECT 1 FROM events WHERE case_id=? AND kind='sim_payment'", (cid,)).fetchone()
        self.assertIsNotNone(row)

    def test_double_submit_is_replayed_once(self):
        cid = make_case("j8")
        sel = {"case_id": cid, "selected": ["tariff_lookup", "label_check"]}
        a = app.handle_simpay(dict(sel), who("j8"))[1]
        b = app.handle_simpay(dict(sel), who("j8"))[1]
        self.assertTrue(b["payment"]["data"].get("duplicate"))
        self.assertEqual(a["payment"]["data"]["ref"], b["payment"]["data"]["ref"])
        n = app.con().execute("SELECT COUNT(*) FROM events WHERE case_id=? AND kind='sim_payment'", (cid,)).fetchone()[0]
        self.assertEqual(n, 1)

    def test_payment_needs_items(self):
        cid = make_case("j7")
        self.assertEqual(app.handle_simpay({"case_id": cid, "selected": []}, who("j7"))[0], 400)

    def test_unknown_items_are_dropped(self):
        cid = make_case("j8")
        out = app.handle_journey({"case_id": cid, "selected": ["nonsense", "label_check"]}, who("j8"))[1]
        self.assertEqual(out["selected"], ["label_check"])


if __name__ == "__main__":
    unittest.main()
