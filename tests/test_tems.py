import os
import tempfile
import unittest

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
from vialibera import accounts, core_checks, db, docs, permissions, tems

ADMIN = {"user": "admin", "org": None, "roles": ["veripura_superadmin"]}
LEAD = {"user": "lead", "org": None, "roles": []}
MEMBER = {"user": "mem", "org": None, "roles": []}
CLIENT_A = {"user": "ca", "org": None, "roles": []}
CLIENT_B = {"user": "cb", "org": None, "roles": []}
OUTSIDER = {"user": "x", "org": None, "roles": []}
VAT_A, VAT_B = "IT00743110157", "IT01765920051"


def accept_body(vat, name):
    return {"vat": vat, "legal_name": name, "signatory_name": "Mario Rossi", "signatory_role": "Legale rappresentante",
            "email": "m@example.it", "accept_scope": True, "accept_core": True, "accept_terms": True}


class Tems(unittest.TestCase):
    def setUp(self):
        self.con = db.connect()
        _, f = tems.create_firm(self.con, ADMIN, "Export Partners Srl")
        self.firm = f["firm"]
        tems.join(self.con, LEAD, f["lead_token"])
        _, inv = tems.invite_member(self.con, LEAD)
        tems.join(self.con, MEMBER, inv["token"])
        _, la = tems.engage_link(self.con, LEAD)
        _, oa = tems.engage_accept(self.con, CLIENT_A, la["token"], accept_body(VAT_A, "Alfa Srl"), "v1")
        self.co_a = oa["company"]
        _, lb = tems.engage_link(self.con, LEAD)
        _, ob = tems.engage_accept(self.con, CLIENT_B, lb["token"], accept_body(VAT_B, "Beta Srl"), "v1")
        self.co_b = ob["company"]

    def test_only_superadmin_creates_firms(self):
        self.assertEqual(tems.create_firm(self.con, LEAD, "X")[0], 403)

    def test_engagement_creates_company_owner_and_record(self):
        self.assertEqual(permissions.role_in(self.con, self.co_a, "ca"), "owner")
        rec = self.con.execute("SELECT * FROM tem_clients WHERE company_id=?", (self.co_a,)).fetchone()
        self.assertEqual(rec["status"], "active")
        doc = self.con.execute("SELECT doc_type, company_id FROM documents WHERE id=?", (rec["engagement_doc"],)).fetchone()
        self.assertEqual((doc["doc_type"], doc["company_id"]), ("contract", self.co_a))
        self.assertTrue(accounts.has_consent(self.con, "ca", "v1"))

    def test_link_is_single_use_and_needs_all_acceptances(self):
        _, l = tems.engage_link(self.con, LEAD)
        bad = accept_body("IT02812600134", "Gamma"); bad["accept_core"] = False
        self.assertEqual(tems.engage_accept(self.con, OUTSIDER, l["token"], bad, "v1")[0], 400)
        self.assertEqual(tems.engage_accept(self.con, OUTSIDER, l["token"], accept_body("IT02812600134", "Gamma"), "v1")[0], 200)
        self.assertEqual(tems.engage_accept(self.con, OUTSIDER, l["token"], accept_body("IT02812600134", "Gamma"), "v1")[0], 400)

    def test_existing_company_needs_its_owner(self):
        _, l = tems.engage_link(self.con, LEAD)
        self.assertEqual(tems.engage_accept(self.con, OUTSIDER, l["token"], accept_body(VAT_A, "Alfa"), "v1")[0], 403)

    def test_lead_sees_all_member_sees_assigned_only(self):
        self.assertTrue(tems.has_access(self.con, LEAD, self.co_a))
        self.assertFalse(tems.has_access(self.con, MEMBER, self.co_a))
        tems.assign(self.con, LEAD, self.co_a, "mem")
        self.assertTrue(tems.has_access(self.con, MEMBER, self.co_a))
        self.assertFalse(tems.has_access(self.con, MEMBER, self.co_b))
        self.assertEqual([c["name"] for c in tems.overview(self.con, MEMBER)[1]["clients"]], ["Alfa Srl"])
        self.assertEqual(tems.assign(self.con, MEMBER, self.co_b, "mem")[0], 403)

    def test_revoke_cuts_access(self):
        self.assertEqual(tems.revoke(self.con, OUTSIDER, self.firm)[0], 403)
        tems.revoke(self.con, CLIENT_A, self.firm)
        self.assertFalse(tems.has_access(self.con, LEAD, self.co_a))
        self.assertTrue(tems.has_access(self.con, LEAD, self.co_b))

    def test_tem_role_can_write_not_order(self):
        _, p = tems.new_project(self.con, LEAD, self.co_a, "pasta", "UK", "Pasta X")
        row = self.con.execute("SELECT * FROM cases WHERE id=?", (p["case_id"],)).fetchone()
        role = permissions.case_role(self.con, row, LEAD)
        self.assertEqual(role, "tem")
        self.assertTrue(permissions.allowed(role, "write"))
        self.assertFalse(permissions.allowed(role, "order"))
        self.assertFalse(permissions.allowed(role, "plan"))

    def test_documents_stay_with_their_company(self):
        _, pa = tems.new_project(self.con, LEAD, self.co_a, "pasta", "UK")
        _, pb = tems.new_project(self.con, LEAD, self.co_b, "pasta", "UK")
        _, da = docs.upload(self.con, LEAD, "invoice.pdf", b"%PDF-1.4 A", case_id=pa["case_id"])
        self.assertEqual(self.con.execute("SELECT company_id FROM documents WHERE id=?", (da["id"],)).fetchone()[0], self.co_a)
        # cannot attach client A's document to client B's project
        self.assertFalse(docs.link(self.con, LEAD, pb["case_id"], da["id"]))
        # same file uploaded for client B is a new document of client B, not a duplicate of A's
        _, db_ = docs.upload(self.con, LEAD, "invoice.pdf", b"%PDF-1.4 A", case_id=pb["case_id"])
        self.assertNotEqual(db_["id"], da["id"])
        self.assertEqual(self.con.execute("SELECT company_id FROM documents WHERE id=?", (db_["id"],)).fetchone()[0], self.co_b)
        # CORE refuses a cross-company document even if a link row were forced
        self.con.execute("INSERT INTO project_docs(case_id, document_id, created_at) VALUES (?,?,?)", (pb["case_id"], da["id"], db.now()))
        self.assertEqual(core_checks.send(self.con, ADMIN, pb["case_id"], da["id"])[0], 403)

    def test_one_core_consignment_per_project_per_client(self):
        _, pa = tems.new_project(self.con, LEAD, self.co_a, "pasta", "UK")
        _, pb = tems.new_project(self.con, LEAD, self.co_b, "pasta", "UK")
        _, da = docs.upload(self.con, LEAD, "invoice.pdf", b"%PDF-1.4 A1", case_id=pa["case_id"])
        _, dbb = docs.upload(self.con, LEAD, "invoice.pdf", b"%PDF-1.4 B1", case_id=pb["case_id"])
        core_checks.send(self.con, ADMIN, pa["case_id"], da["id"])
        core_checks.send(self.con, ADMIN, pb["case_id"], dbb["id"])
        rows = self.con.execute("SELECT case_id, consignment_id FROM core_consignments").fetchall()
        self.assertEqual(len({r["consignment_id"] for r in rows}), 2)

    def test_project_view_logs_access_visible_to_client(self):
        _, p = tems.new_project(self.con, LEAD, self.co_a, "pasta", "UK")
        self.assertEqual(tems.project(self.con, OUTSIDER, p["case_id"])[0], 404)
        self.assertEqual(tems.project(self.con, MEMBER, p["case_id"])[0], 404)  # not assigned
        code, out = tems.project(self.con, LEAD, p["case_id"])
        self.assertEqual(code, 200)
        self.assertTrue(out["required_docs"]["data"]["items"])
        log = tems.client_view(self.con, CLIENT_A)[1]["log"]
        self.assertEqual(log[0]["action"], "open_project")

    def test_confirmations_and_notes(self):
        _, p = tems.new_project(self.con, LEAD, self.co_a, "pasta", "UK")
        tems.confirm_item(self.con, LEAD, p["case_id"], "rex", "Client has REX IT...")
        _, out = tems.project(self.con, LEAD, p["case_id"])
        rex = [i for i in out["required_docs"]["data"]["items"] if i["id"] == "rex"][0]
        self.assertTrue(rex["verified"])
        tems.add_note(self.con, LEAD, p["case_id"], "internal only", "internal")
        tems.add_note(self.con, LEAD, p["case_id"], "for the client", "client")
        self.assertEqual([n["text"] for n in tems.notes(self.con, p["case_id"])], ["for the client"])
        self.assertEqual(len(tems.notes(self.con, p["case_id"], internal=True)), 2)
        self.assertEqual(tems.add_note(self.con, MEMBER, p["case_id"], "x")[0], 404)

    def test_seats_limit(self):
        self.con.execute("UPDATE tem_firms SET seats=2 WHERE id=?", (self.firm,))
        self.assertEqual(tems.invite_member(self.con, LEAD)[1].get("error"), "no_free_seat")
        self.assertEqual(tems.invite_member(self.con, MEMBER)[0], 403)

    def test_staff_and_tems_cannot_accept_engagement(self):
        _, l = tems.engage_link(self.con, LEAD)
        self.assertEqual(tems.engage_accept(self.con, MEMBER, l["token"], accept_body("IT02812600134", "G"), "v1")[0], 403)
        self.assertEqual(tems.engage_accept(self.con, ADMIN, l["token"], accept_body("IT02812600134", "G"), "v1")[0], 403)
