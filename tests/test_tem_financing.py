import os
import tempfile
import unittest
from datetime import date

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, tem_financing, tems
from test_tems import ADMIN, LEAD, MEMBER, CLIENT_A, OUTSIDER, VAT_A, accept_body


class TemFinancingTest(unittest.TestCase):
    def setUp(self):
        self.c = app.con()
        for t in ("tem_financing", "tem_requests", "tool_visibility", "tem_clients", "tem_members", "tem_firms", "tem_assignments", "engagement_links"):
            self.c.execute(f"DELETE FROM {t}")
        for r in self.c.execute("SELECT id FROM companies WHERE vat=?", (VAT_A,)).fetchall():  # other test files may have used this VAT
            for t in ("memberships", "tem_clients"):
                self.c.execute(f"DELETE FROM {t} WHERE company_id=?", (r["id"],))
            self.c.execute("DELETE FROM companies WHERE id=?", (r["id"],))
        for u in ("ca", "lead", "x", "rev"):
            self.c.execute("DELETE FROM memberships WHERE user_sub=?", (u,))
        self.c.commit()
        _, f = tems.create_firm(self.c, ADMIN, "Export Partners Srl")
        tems.join(self.c, LEAD, f["lead_token"])
        _, la = tems.engage_link(self.c, LEAD)
        _, oa = tems.engage_accept(self.c, CLIENT_A, la["token"], accept_body(VAT_A, "Alfa Srl"), app.TERMS_VERSION)
        self.co = oa["company"]
        accounts.record_consent(self.c, "ca", app.TERMS_VERSION, "en", True)
        accounts.record_consent(self.c, "lead", app.TERMS_VERSION, "en", True)
        accounts.record_consent(self.c, "x", app.TERMS_VERSION, "en", True)
        _, p = tems.new_project(self.c, LEAD, self.co, "wine", "USA", "Barolo")
        self.case = p["case_id"]

    def save(self, user=LEAD, **kw):
        return app.handle_tem("/tem/financing_save", {"case_id": self.case, **kw}, user)

    def lines(self, user=LEAD):
        return app.handle_tem("/tem/project", {"case_id": self.case}, user)[1]["financing"]["lines"]

    def test_sourced_deadline_wins_and_typed_one_is_labelled(self):
        self.assertEqual(self.save(scheme_id="to_intl_2026", status="preparing", deadline="2027-01-01", missing="Visura camerale")[0], 200)
        self.assertEqual(self.save(scheme_id="simest_tm", status="not_started", deadline="2027-03-31")[0], 200)
        by = {l["scheme_id"]: l for l in self.lines()}
        self.assertEqual((by["to_intl_2026"]["deadline"], by["to_intl_2026"]["deadline_by_firm"]), ("2026-12-18", False))
        self.assertEqual((by["simest_tm"]["deadline"], by["simest_tm"]["deadline_by_firm"]), ("2027-03-31", True))
        self.assertEqual(by["to_intl_2026"]["missing"], "Visura camerale")

    def test_client_sees_only_lines_switched_on(self):
        self.save(scheme_id="to_intl_2026", status="preparing", missing="Visura", client_visible=True)
        self.save(scheme_id="simest_tm", status="preparing", missing="Private note")
        seen = app.handle_journey({"case_id": self.case}, CLIENT_A)[1]["tem_financing"]
        self.assertEqual([l["scheme_id"] for l in seen], ["to_intl_2026"])
        self.assertEqual(seen[0]["firm"], "Export Partners Srl")
        self.assertNotIn("Private note", str(seen))

    def test_workspace_shows_the_next_unfinished_deadline(self):
        self.save(scheme_id="simest_tm", status="preparing", deadline="2027-02-01")
        self.save(scheme_id="to_intl_2026", status="approved")
        nxt = tem_financing.next_deadline(self.c, tems.firm_of(self.c, LEAD["user"])["firm_id"], self.co, today=date(2026, 11, 22))
        self.assertEqual(nxt["date"], "2027-02-01")
        ov = tems.overview(self.c, LEAD)[1]
        self.assertEqual(ov["clients"][0]["next_financing"]["date"], "2027-02-01")

    def test_bad_input_and_outsiders(self):
        self.assertEqual(self.save(scheme_id="nope", status="preparing")[0], 400)
        self.assertEqual(self.save(scheme_id="simest_tm", status="won")[0], 400)
        self.assertEqual(self.save(scheme_id="simest_tm", status="preparing", deadline="soon")[0], 400)
        self.assertEqual(self.save(OUTSIDER, scheme_id="simest_tm", status="preparing")[0], 404)
        self.assertEqual(self.save(CLIENT_A, scheme_id="simest_tm", status="preparing")[0], 404)
        lid = self.save(scheme_id="simest_tm", status="preparing")[1]["id"]
        self.assertEqual(app.handle_tem("/tem/financing_delete", {"case_id": self.case, "id": lid}, OUTSIDER)[0], 404)
        self.assertEqual(app.handle_tem("/tem/financing_delete", {"case_id": self.case, "id": lid}, LEAD)[0], 200)
        self.assertEqual(self.lines(), [])
