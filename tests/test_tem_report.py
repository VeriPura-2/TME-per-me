import os
import tempfile
import unittest

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, tems
from test_tems import ADMIN, LEAD, CLIENT_A, OUTSIDER, VAT_A, accept_body


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.c = app.con()
        for t in ("importer_contacts", "doc_requests", "tem_fees", "tem_time", "tem_requests", "tool_visibility", "tem_clients", "tem_members", "tem_firms", "tem_assignments", "engagement_links"):
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

    def report(self, user=LEAD, lang="en"):
        return app.handle_tem("/tem/report", {"case_id": self.case, "lang": lang}, user)

    def test_report_has_the_firm_route_sections_and_footer(self):
        app.handle_tem("/tem/contact_save", {"case_id": self.case, "importer": "Alpine <Foods>", "channel": "email", "outcome": "replied"}, LEAD)
        code, out = self.report()
        self.assertEqual(code, 200)
        h = out["html"]
        self.assertIn("Export Partners Srl: export documents status for", h)
        for s in ("Route", "Documents received", "Documents outstanding", "Checks done", "Importers contacted", "Notes"):
            self.assertIn("<h2>" + s + "</h2>", h)
        self.assertIn("Prepared by Export Partners Srl with MioTEM, powered by VeriPura Core.", h)
        self.assertIn("Alpine &lt;Foods&gt;", h)  # escaped
        self.assertNotIn("\u2014", h)

    def test_no_firm_only_data_and_italian(self):
        app.handle_tem("/tem/fee", {"case_id": self.case, "kind": "fixed", "amount": "4321"}, LEAD)
        tems.add_note(self.c, LEAD, self.case, "internal secret", "internal")
        h = self.report(lang="it")[1]["html"]
        self.assertNotIn("4321", h)
        self.assertNotIn("internal secret", h)
        self.assertIn("stato dei documenti export per", h)
        self.assertIn("Documenti mancanti", h)

    def test_only_the_tem_gets_it(self):
        self.assertEqual(self.report(CLIENT_A)[0], 404)
        self.assertEqual(self.report(OUTSIDER)[0], 404)
