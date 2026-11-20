"""Exporters looking for a TEM (20 Nov 2026): request with consent, TEM list and offers, withdraw, staff close."""
import os
import tempfile
import unittest
import uuid

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
os.environ.pop("ANTHROPIC_API_KEY", None)
from vialibera import accounts, app, intros, tems, tools  # noqa: E402

ADMIN = {"user": "admin", "org": None, "roles": ["veripura_superadmin"]}


def u(prefix):
    w = {"user": prefix + "-" + uuid.uuid4().hex[:8], "org": None, "roles": []}
    accounts.record_consent(app.con(), w["user"], app.TERMS_VERSION, "en", True)
    return w


def firm_lead(name):
    c = app.con()
    _, f = tems.create_firm(c, ADMIN, name + " " + uuid.uuid4().hex[:6])
    lead = u("lead")
    tems.join(c, lead, f["lead_token"])
    return f["firm"], lead


class Intros(unittest.TestCase):
    def setUp(self):
        self.exp = u("exp")
        code, out = app.handle_start({"category": "cheese and dairy", "country": "USA", "description": "Parmigiano Reggiano DOP"}, self.exp)
        self.assertEqual(code, 200)
        self.cid = out["case_id"]

    def ask(self, consent=True):
        return app.handle_tools("/tools/interest", {"case_id": self.cid, "tool": "tem_intro", "consent": consent, "email": "e@example.com"}, self.exp)

    def test_no_request_without_consent(self):
        self.assertEqual(self.ask(consent=False)[0], 400)
        self.assertIsNone(app.handle_tools("/tools/intro_status", {"case_id": self.cid}, self.exp)[1]["request"])

    def test_request_offer_withdraw_and_close(self):
        self.assertEqual(self.ask()[0], 200)
        self.ask()  # answering twice keeps one open request
        n = app.con().execute("SELECT COUNT(*) AS n FROM intro_requests WHERE case_id=? AND status='open'", (self.cid,)).fetchone()["n"]
        self.assertEqual(n, 1)
        st = app.handle_tools("/tools/intro_status", {"case_id": self.cid}, self.exp)[1]["request"]
        self.assertEqual((st["status"], st["offers"]), ("open", []))
        fa, la = firm_lead("Alfa TEM")
        fb, lb = firm_lead("Beta TEM")
        lst = app.handle_tools("/tools/intro_list", {}, la)[1]["requests"]
        mine = [r for r in lst if r["category"] == "cheese and dairy" and r["country"] == "USA" and not r["offered"]]
        self.assertTrue(mine)
        rid = [r for r in lst if r["id"] in {x["id"] for x in app.con().execute(
            "SELECT id FROM intro_requests WHERE case_id=?", (self.cid,)).fetchall()}][0]["id"]
        self.assertNotIn("email", [k for r in lst for k in r])  # no contact details reach TEMs
        self.assertEqual(app.handle_tools("/tools/intro_offer", {"request": rid, "note": "Happy to help"}, la)[0], 200)
        self.assertTrue(app.handle_tools("/tools/intro_offer", {"request": rid}, la)[1].get("already"))
        self.assertEqual(app.handle_tools("/tools/intro_offer", {"request": rid}, lb)[0], 200)
        st = app.handle_tools("/tools/intro_status", {"case_id": self.cid}, self.exp)[1]["request"]
        self.assertEqual(len(st["offers"]), 2)
        self.assertEqual(app.handle_tools("/tools/intro_offer", {"request": rid}, self.exp)[0], 403)  # only TEMs offer
        self.assertEqual(app.handle_tools("/tools/intro_list", {}, self.exp)[0], 403)
        staff = app.handle_admin("/admin/intro_requests", {}, ADMIN)[1]["requests"]
        row = [r for r in staff if r["id"] == rid][0]
        self.assertEqual((row["email"], len(row["offers"])), ("e@example.com", 2))
        self.assertEqual(app.handle_admin("/admin/intro_requests", {}, la)[0], 403)
        self.assertEqual(app.handle_admin("/admin/intro_introduced", {"request": rid}, la)[0], 403)
        self.assertEqual(app.handle_admin("/admin/intro_introduced", {"request": rid}, ADMIN)[0], 200)
        self.assertEqual(app.handle_tools("/tools/intro_status", {"case_id": self.cid}, self.exp)[1]["request"]["status"], "introduced")
        self.assertNotIn(rid, {r["id"] for r in app.handle_tools("/tools/intro_list", {}, lb)[1]["requests"]})

    def test_withdraw_hides_it_from_tems(self):
        self.ask()
        rid = app.con().execute("SELECT id FROM intro_requests WHERE case_id=?", (self.cid,)).fetchone()["id"]
        _, la = firm_lead("Gamma TEM")
        self.assertIn(rid, {r["id"] for r in app.handle_tools("/tools/intro_list", {}, la)[1]["requests"]})
        other = u("other")
        self.assertEqual(app.handle_tools("/tools/intro_withdraw", {"case_id": self.cid}, other)[0], 404)  # not their project
        self.assertEqual(app.handle_tools("/tools/intro_withdraw", {"case_id": self.cid}, self.exp)[0], 200)
        self.assertNotIn(rid, {r["id"] for r in app.handle_tools("/tools/intro_list", {}, la)[1]["requests"]})
        self.assertIsNone(app.handle_tools("/tools/intro_status", {"case_id": self.cid}, self.exp)[1]["request"])

    def test_tour_texts(self):
        q = [x for x in tools.TOUR[-1]["questions"] if x["ask"] == "tem_intro"][0]
        self.assertIn("company name, product and destination to TEMs", q["consent"]["en"])
        self.assertIn("ragione sociale, prodotto e destinazione ai TEM", q["consent"]["it"])
        self.assertIn("intros", [s["id"] for s in tools.TEM_TOUR])


if __name__ == "__main__":
    unittest.main()
