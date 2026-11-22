"""B2 (22 Nov 2026): certificates and approvals tracker."""
import os
import tempfile
import unittest
from datetime import date

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
os.environ.setdefault("DB_PATH", ":memory:")
from vialibera import app, certificates, tools
from test_start_form import user


class CertTest(unittest.TestCase):
    def setUp(self):
        self.c = app.con()
        self.c.execute("DELETE FROM certificates")
        self.c.commit()
        self.who = user("cert-1")
        self.case = app.handle_start({"category": "cheese", "country": "UK"}, self.who)[1]["case_id"]

    def call(self, path, who=None, **kw):
        return app.handle_tools(path, {"case_id": self.case, **kw}, who or self.who)

    def test_types_come_from_checklist_rows_with_sources_or_masaf(self):
        ts = certificates.types()
        self.assertTrue(ts["uk_ehc"]["source"].startswith("https://www.gov.uk/"))
        self.assertTrue(ts["ttb_cert"]["source"].startswith("https://www.ttb.gov/"))
        self.assertEqual(ts["dop"]["source_label"]["en"], "MASAF control body lists")
        self.assertNotIn("prior_notice", ts)  # no official source in the checklist row, and it is per shipment
        self.assertNotIn("organic", ts)  # no checklist row yet: use Other

    def test_add_list_expire_and_back_to_claimed(self):
        code, out = self.call("/tools/cert_save", type="dop", product="Parmigiano Reggiano", issued_by="OCQ PR", valid_until="2027-01-31")
        self.assertEqual(code, 200)
        cert = out["certificates"][0]
        self.assertEqual((cert["status"], cert["name"]["en"]), ("claimed", "DOP certificate (protected designation of origin)"))
        self.assertEqual(certificates.listing(self.c, self.c.execute("SELECT owner_key FROM certificates").fetchone()["owner_key"],
                                              today=date(2027, 2, 1))[0]["status"], "expired")
        self.c.execute("UPDATE certificates SET status='seen_staff'")
        out = self.call("/tools/cert_save", id=cert["id"], type="dop", product="Parmigiano Reggiano", valid_until="2028-01-31")[1]
        self.assertEqual(out["certificates"][0]["status"], "claimed")  # a new date goes back to claimed

    def test_other_needs_a_name_and_bad_input_is_refused(self):
        self.assertEqual(self.call("/tools/cert_save", type="other")[0], 400)
        self.assertEqual(self.call("/tools/cert_save", type="other", name="Organic (EU)")[0], 200)
        self.assertEqual(self.call("/tools/cert_save", type="halal_magic")[0], 400)
        self.assertEqual(self.call("/tools/cert_save", type="dop", valid_until="soon")[0], 400)
        self.assertEqual(self.call("/tools/cert_save", type="dop", document_id="not-mine")[0], 400)
        self.assertEqual(self.call("/tools/certs", who=user("stranger"))[0], 404)

    def test_only_staff_mark_seen_and_nothing_sets_core(self):
        cid = self.call("/tools/cert_save", type="dop")[1]["certificates"][0]["id"]
        self.assertEqual(self.call("/tools/cert_seen", id=cid)[0], 403)
        import glob
        for f in glob.glob(os.path.join(os.path.dirname(certificates.__file__), "*.py")):
            self.assertNotIn("status='checked_core'", open(f, encoding="utf-8").read(), f)  # no Core check is connected yet

    def test_reminder_30_days_before_once(self):
        self.c.execute("INSERT INTO certificates(id, owner_key, type, product, issued_by, valid_until, status, created_by, created_at, updated_at) "
                       "VALUES ('c1','co-x','dop','Grana','CSQA','2026-12-20','claimed','u','x','x')")
        self.c.execute("DELETE FROM memberships WHERE company_id='co-x'")
        self.c.execute("INSERT INTO memberships(company_id, user_sub, role, status, label, created_at) VALUES ('co-x','ux','owner','active','o@x.example','x')")
        sent = []
        send = lambda to, subj, body: sent.append((to, subj, body)) or True
        certificates.send_reminders(self.c, "https://app.example", send, today=date(2026, 11, 10), lang="en")
        self.assertEqual(sent, [])
        certificates.send_reminders(self.c, "https://app.example", send, today=date(2026, 11, 22), lang="en")
        certificates.send_reminders(self.c, "https://app.example", send, today=date(2026, 11, 23), lang="en")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1], "DOP certificate (protected designation of origin) expires on 20 Dec 2026")
        self.assertIn("(Grana, CSQA)", sent[0][2])

    def test_card_sits_with_the_compliance_tools(self):
        ids = [c["id"] for c in tools.for_case("cheese", "UK")]
        self.assertEqual(ids.index("certificates"), ids.index("cert_evidence") + 1)
