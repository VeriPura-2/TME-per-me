import os
import tempfile
import unittest

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, tems
from test_tems import ADMIN, LEAD, MEMBER, CLIENT_A, OUTSIDER, VAT_A, accept_body


class MarginTest(unittest.TestCase):
    def setUp(self):
        self.c = app.con()
        for t in ("tem_fees", "tem_time", "tem_costs", "tem_requests", "tool_visibility", "tem_clients", "tem_members", "tem_firms", "tem_assignments", "engagement_links"):
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
        _, inv = tems.invite_member(self.c, LEAD)
        tems.join(self.c, MEMBER, inv["token"])
        tems.assign(self.c, LEAD, self.co, "mem")
        accounts.record_consent(self.c, "mem", app.TERMS_VERSION, "en", True)

    def t(self, path, body, user=LEAD):
        return app.handle_tem(path, {"case_id": self.case, **body}, user)

    def margin(self, user=LEAD):
        return app.handle_tem("/tem/project", {"case_id": self.case}, user)[1]["margin"]

    def test_lead_sees_rate_margin_and_target_warning(self):
        self.assertEqual(self.t("/tem/fee", {"kind": "fixed", "amount": "1000", "target_rate": "60"})[0], 200)
        self.t("/tem/time", {"hours": "10", "category": "chasing", "day": "2026-11-20"})
        self.t("/tem/time", {"hours": "6", "category": "checking"}, MEMBER)
        self.t("/tem/cost", {"amount": "100", "what": "Translation"})
        m = self.margin()
        self.assertEqual((m["hours"], m["cost"], m["margin"], m["rate"]), (16, 100, 900, 56.25))
        self.assertTrue(m["below_target"])
        self.assertEqual(m["by_category"]["chasing"], 10)

    def test_member_sees_own_entries_only_and_cannot_set_the_fee(self):
        self.t("/tem/fee", {"kind": "fixed", "amount": "1000"})
        self.t("/tem/time", {"hours": "10", "category": "chasing"})
        self.t("/tem/time", {"hours": "2", "category": "calls"}, MEMBER)
        m = self.margin(MEMBER)
        self.assertEqual(m["hours"], 2)
        self.assertNotIn("margin", m)
        self.assertNotIn("fee", m)
        self.assertEqual(self.t("/tem/fee", {"kind": "fixed", "amount": "1"}, MEMBER)[0], 403)
        lead_entry = [e for e in self.margin()["time"] if e["category"] == "chasing"][0]["id"]
        self.assertEqual(self.t("/tem/entry_delete", {"kind": "time", "id": lead_entry}, MEMBER)[0], 404)
        own = self.margin(MEMBER)["time"][0]["id"]
        self.assertEqual(self.t("/tem/entry_delete", {"kind": "time", "id": own}, MEMBER)[0], 200)

    def test_client_and_outsiders_never_reach_it(self):
        self.t("/tem/fee", {"kind": "fixed", "amount": "1000"})
        for u in (CLIENT_A, OUTSIDER):
            self.assertEqual(self.t("/tem/time", {"hours": "1", "category": "other"}, u)[0], 404)
            self.assertEqual(self.t("/tem/fee", {"kind": "fixed", "amount": "1"}, u)[0], 404)
        out = app.handle_journey({"case_id": self.case}, CLIENT_A)[1]
        self.assertNotIn("margin", out)
        self.assertNotIn("1000", str(out))

    def test_bad_entries_are_refused(self):
        self.assertEqual(self.t("/tem/time", {"hours": "0", "category": "other"})[0], 400)
        self.assertEqual(self.t("/tem/time", {"hours": "25", "category": "other"})[0], 400)
        self.assertEqual(self.t("/tem/time", {"hours": "1", "category": "golf"})[0], 400)
        self.assertEqual(self.t("/tem/cost", {"amount": "10", "what": ""})[0], 400)
        self.assertEqual(self.t("/tem/fee", {"kind": "hourly", "amount": "10"})[0], 400)
