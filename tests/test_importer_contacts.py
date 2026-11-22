import os
import tempfile
import unittest

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, tems
from test_tems import ADMIN, LEAD, CLIENT_A, OUTSIDER, VAT_A, accept_body


class ContactsTest(unittest.TestCase):
    def setUp(self):
        self.c = app.con()
        for t in ("importer_contacts", "tem_requests", "tool_visibility", "tem_clients", "tem_members", "tem_firms", "tem_assignments", "engagement_links"):
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
        return app.handle_tem("/tem/contact_save", {"case_id": self.case, **kw}, user)

    def test_tem_records_and_client_always_sees_it(self):
        self.assertEqual(self.save(importer="Alpine Foods Inc", website="https://alpine.example", day="2026-11-20", channel="email", outcome="contacted")[0], 200)
        lid = self.save(importer="Bay Cheese Co", channel="fair", outcome="samples", note="Fancy Food Show")[1]["id"]
        self.save(id=lid, importer="Bay Cheese Co", channel="fair", outcome="meeting", note="Meeting 3 Dec")
        seen = app.handle_journey({"case_id": self.case}, CLIENT_A)[1]["importer_contacts"]
        self.assertEqual({x["importer"]: x["outcome"] for x in seen}, {"Alpine Foods Inc": "contacted", "Bay Cheese Co": "meeting"})
        self.assertEqual(seen[0]["firm"], "Export Partners Srl")
        tem_view = app.handle_tem("/tem/project", {"case_id": self.case}, LEAD)[1]["importer_contacts"]
        self.assertEqual(len(tem_view), 2)

    def test_client_and_outsiders_cannot_write(self):
        for u in (CLIENT_A, OUTSIDER):
            self.assertEqual(self.save(u, importer="X", channel="email", outcome="contacted")[0], 404)
        lid = self.save(importer="X", channel="email", outcome="contacted")[1]["id"]
        self.assertEqual(app.handle_tem("/tem/contact_delete", {"case_id": self.case, "id": lid}, CLIENT_A)[0], 404)
        self.assertEqual(app.handle_tem("/tem/contact_delete", {"case_id": self.case, "id": lid}, LEAD)[0], 200)

    def test_bad_entries(self):
        self.assertEqual(self.save(importer="", channel="email", outcome="contacted")[0], 400)
        self.assertEqual(self.save(importer="X", channel="pigeon", outcome="contacted")[0], 400)
        self.assertEqual(self.save(importer="X", channel="email", outcome="won")[0], 400)
        self.assertEqual(self.save(importer="X", channel="email", outcome="contacted", website="javascript:alert(1)")[0], 400)
        self.assertEqual(self.save(importer="X", channel="email", outcome="contacted", day="tomorrow")[0], 400)
