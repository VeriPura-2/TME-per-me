import os
import tempfile
import unittest

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, doc_requests, tems
from test_tems import ADMIN, LEAD, CLIENT_A, OUTSIDER, VAT_A, accept_body


class DocRequestTest(unittest.TestCase):
    def setUp(self):
        self.c = app.con()
        for t in ("doc_requests", "tem_requests", "tool_visibility", "tem_clients", "tem_members", "tem_firms", "tem_assignments", "engagement_links"):
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

    def items(self):
        out = app.handle_tem("/tem/project", {"case_id": self.case}, LEAD)[1]
        return [i["id"] for i in out["required_docs"]["data"]["items"] if not i["importer_side"]]

    def request(self, items, days=3, user=LEAD):
        return app.handle_tem("/tem/doc_request", {"case_id": self.case, "items": items, "remind_days": days}, user)

    def upload(self, rid, user=CLIENT_A):
        return app.handle_upload({"X-Filename": "label.pdf", "X-Case": self.case, "X-Request": rid}, b"%PDF-1.4 test " + rid.encode(), user)

    def test_tem_requests_and_client_sees_them(self):
        its = self.items()[:2]
        code, out = self.request(its)
        self.assertEqual((code, out["created"]), (200, 2))
        self.assertEqual(self.request(its)[1]["created"], 0)  # not asked twice while open
        reqs = app.handle_journey({"case_id": self.case}, CLIENT_A)[1]["doc_requests"]
        self.assertEqual([q["status"] for q in reqs], ["requested", "requested"])
        self.assertEqual(reqs[0]["firm"], "Export Partners Srl")
        ov = tems.overview(self.c, LEAD)[1]
        self.assertEqual(ov["clients"][0]["docs_waiting"], 2)

    def test_unknown_items_and_outsiders_are_refused(self):
        self.assertEqual(self.request(["nope"])[0], 400)
        self.assertEqual(self.request(self.items()[:1], user=OUTSIDER)[0], 404)
        self.assertEqual(self.request(self.items()[:1], user=CLIENT_A)[0], 404)

    def test_upload_accept_and_needs_change(self):
        self.request(self.items()[:1])
        rid = doc_requests.for_case(self.c, self.case)[0]["id"]
        code, out = self.upload(rid)
        self.assertEqual(code, 200)
        self.assertTrue(out["request_filled"])
        q = doc_requests.for_case(self.c, self.case)[0]
        self.assertEqual((q["status"], q["document_id"]), ("uploaded", out["id"]))
        self.assertEqual(app.handle_tem("/tem/doc_request_status", {"case_id": self.case, "id": rid, "status": "needs_change"}, LEAD)[0], 400)
        app.handle_tem("/tem/doc_request_status", {"case_id": self.case, "id": rid, "status": "needs_change", "note": "Add the lot number"}, LEAD)
        q = doc_requests.for_case(self.c, self.case)[0]
        self.assertEqual((q["status"], q["note"]), ("needs_change", "Add the lot number"))
        self.upload(rid)
        app.handle_tem("/tem/doc_request_status", {"case_id": self.case, "id": rid, "status": "accepted"}, LEAD)
        self.assertEqual(doc_requests.for_case(self.c, self.case)[0]["status"], "accepted")
        self.assertEqual(app.handle_tem("/tem/doc_request_status", {"case_id": self.case, "id": rid, "status": "accepted"}, OUTSIDER)[0], 404)

    def test_reminders_after_the_set_days_once_per_period(self):
        self.request(self.items()[:2], days=3)
        self.c.execute("UPDATE memberships SET label='owner@alfa.example' WHERE company_id=? AND role='owner'", (self.co,))
        sent = []
        send = lambda to, subj, body: sent.append((to, subj, body)) or True
        self.assertEqual(doc_requests.send_reminders(self.c, "https://app.example", send)["projects_reminded"], 0)
        self.c.execute("UPDATE doc_requests SET requested_at='2026-01-01T00:00:00+00:00', updated_at='2026-01-01T00:00:00+00:00'")
        self.assertEqual(doc_requests.send_reminders(self.c, "https://app.example", send, lang="en")["projects_reminded"], 1)
        to, subj, body = sent[0]
        self.assertEqual((to, subj), ("owner@alfa.example", "Export Partners Srl is waiting for 2 documents"))
        self.assertIn("https://app.example/", body)
        self.assertNotIn("\u2014", body)
        self.assertEqual(doc_requests.send_reminders(self.c, "https://app.example", send)["projects_reminded"], 0)  # not again today
        app.handle_tem("/tem/doc_request_reminders", {"case_id": self.case, "days": 0}, LEAD)
        self.c.execute("UPDATE doc_requests SET last_reminded_at='2026-01-01T00:00:00+00:00'")
        self.assertEqual(doc_requests.send_reminders(self.c, "https://app.example", send)["projects_reminded"], 0)  # turned off
