"""Core document submission: docType is mandatory, the answer is split into "read" and "confirmed by the control body".

The Core answers below are mocks in the documented shape. The alert wording is modelled on VeriPura's release notes
and test plan, not copied from a live answer: it is to be re-checked against a real answer in the live test.
"""
import json
import os
import tempfile
import unittest

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
from vialibera import core_checks as cc, core_results, db, docs
from vialibera.adapters.base import AdapterError
from tests.test_core_checks import CLIENT, PDF, STAFF, live_core


def answer(status, level, review, *alerts, doc_type="X"):
    return (200, json.dumps({"consignmentId": "c1", "docType": doc_type, "status": status, "validationLevel": level,
                             "requiresHumanReview": review,
                             "alerts": [{"severity": sev, "message": msg} for sev, msg in alerts]}))


class Submission(unittest.TestCase):
    def setUp(self):
        self.con = db.connect()
        self.case = db.create_case(self.con, 1, owner_sub="c1")
        db.case_write(self.con, self.case, "product", {"category": "cheese", "name_brand": "Parmigiano Reggiano"})
        db.case_write(self.con, self.case, "market", {"country": "UK"})
        db.case_write(self.con, self.case, "company", {"legal_name": "Test srl"})
        self.con.execute("INSERT INTO companies(id, vat, legal_name, created_at, owner_confirmed) VALUES (?,?,?,?,?)",
                         ("co-s", "IT00157100207", "Test srl", db.now(), "test"))
        self.con.execute("UPDATE cases SET company_id='co-s' WHERE id=?", (self.case,))
        self.con.execute("INSERT INTO memberships(company_id, user_sub, role, status, created_at) VALUES (?,?,?,?,?)",
                         ("co-s", CLIENT["user"], "owner", "active", db.now()))
        self.con.commit()
        self.n = 0

    def doc(self, filename, doc_type=None):
        self.n += 1
        _, out = docs.upload(self.con, CLIENT, filename, PDF + str(self.n).encode(), case_id=self.case)
        if doc_type:
            self.con.execute("UPDATE documents SET doc_type=? WHERE id=?", (doc_type, out["id"]))
            self.con.commit()
        return out["id"]

    def send(self, doc_id, response):
        calls = []
        core = live_core([response], calls)
        code, out = cc.send(self.con, STAFF, self.case, doc_id, core=core)
        return code, out, calls

    def check(self, doc_id):
        return next(d for d in cc.summary(self.con, self.case)["documents"] if d["id"] == doc_id)["check"]

    # docType ----------------------------------------------------------------
    def test_type_with_no_core_docType_is_not_sent(self):
        d = self.doc("foto_stabilimento.pdf", "photo")
        calls = []
        code, out = cc.send(self.con, STAFF, self.case, d, core=live_core([], calls))
        self.assertEqual((code, out["error"]), (400, "doc_type_missing"))
        self.assertEqual(calls, [])  # nothing left the building

    def test_every_send_carries_docType_and_key(self):
        d = self.doc("ifs_food_2025.pdf")
        self.assertEqual(self.con.execute("SELECT doc_type FROM documents WHERE id=?", (d,)).fetchone()[0], "cert_voluntary")
        code, out, calls = self.send(d, answer("Pending Review", "YELLOW", True))
        self.assertEqual(code, 200)
        self.assertEqual(calls[0][3]["docType"], "Voluntary Scheme Certificate")
        self.assertTrue(calls[0][4]["Idempotency-Key"])

    def test_certificate_kinds_are_proposed_from_the_file_name(self):
        for name, want in (("secchi_organic_cert.pdf", "cert_organic"), ("parmigiano_dop.pdf", "cert_dop_igp"),
                           ("vino_docg.pdf", "cert_doc_docg"), ("brc_2025.pdf", "cert_voluntary"),
                           ("certificato.pdf", "certificate")):
            self.assertEqual(docs.propose(name), want, name)

    def test_a_specific_certificate_satisfies_a_checklist_line_for_a_certificate(self):
        self.assertEqual(docs.with_certificate({"cert_organic"}), {"cert_organic", "certificate"})
        self.assertEqual(docs.with_certificate({"invoice"}), {"invoice"})

    # the three cases of the spec ----------------------------------------------
    def test_virgilio_active_company_with_a_suspended_warehouse(self):
        d = self.doc("virgilio_dop.pdf", "cert_dop_igp")
        code, out, _ = self.send(d, answer(
            "Pending Review", "YELLOW", True,
            ("info", "Read from the uploaded certificate and confirmed by the control body (OCQ PR): Consorzio Latterie Virgilio, VAT 00157100207, subject APERTO."),
            ("warning", "Plant M302 (warehouse) is sospeso on the OCQ PR list. Points deducted."), doc_type="DOP/IGP Certificate"))
        self.assertEqual(out["outcome"], "flagged")
        b = self.check(d)["basis"]
        self.assertEqual((b["read"], b["confirmed"]), (True, "yes"))
        self.assertEqual([f["kind"] for f in b["flags"]], ["plant_not_active"])

    def test_agriform_all_closed_although_validity_reads_active(self):
        d = self.doc("agriform_dop.pdf", "cert_dop_igp")
        self.send(d, answer("Rejected", "RED", False,
                            ("critical", "Read from the uploaded certificate; NOT confirmed by the control body: every OCQ PR record for VAT 01315410231 is CHIUSO with an end date, although the validity field reads ATTIVO.")))
        b = self.check(d)["basis"]
        self.assertEqual((b["read"], b["confirmed"]), (True, "no"))  # the cautious fact wins over the word "confirmed" nearby
        self.assertIn("plant_not_active", [f["kind"] for f in b["flags"]])
        self.assertEqual(self.check(d)["result"], "flagged_critical")

    def test_secchi_organic_valid_and_ifs_expired(self):
        org = self.doc("secchi_organic.pdf", "cert_organic")
        self.send(org, answer("Validated", "GREEN", False,
                              ("info", "Certificate IT-BIO-006.380-0027371.2024.001 was read from the QR code. Read from the uploaded certificate and confirmed by the control body: Issued, valid until 2027-07-31.")))
        b = self.check(org)["basis"]
        self.assertEqual((b["read"], b["confirmed"], b["flags"]), (True, "yes", []))
        ifs = self.doc("secchi_ifs.pdf", "cert_voluntary")
        self.send(ifs, answer("Pending Review", "YELLOW", True, ("warning", "The IFS Food certificate is expired.")))
        b = self.check(ifs)["basis"]
        self.assertEqual(b["confirmed"], "none")
        self.assertEqual([f["kind"] for f in b["flags"]], ["expired"])

    # honesty rules --------------------------------------------------------------
    def test_a_green_pass_alone_never_shows_confirmed(self):
        d = self.doc("fattura_1.pdf")
        self.send(d, answer("Validated", "GREEN", False))
        b = self.check(d)["basis"]
        self.assertEqual((b["read"], b["confirmed"]), (False, "none"))

    def test_a_basis_field_wins_over_wording(self):
        b = core_results.basis([{"severity": "info", "message": "anything", "basis": "confirmed"}])
        self.assertEqual(b["confirmed"], "yes")
        b = core_results.basis([{"severity": "info", "message": "confirmed by x", "basis": "not_confirmed"}])
        self.assertEqual(b["confirmed"], "no")

    def test_no_specialist_check_is_flagged(self):
        b = core_results.basis([{"severity": "warning", "message": 'No specialist check ran for this document ("x"). Its result is not a pass.'}])
        self.assertEqual([f["kind"] for f in b["flags"]], ["no_specialist"])

    def test_test_mode_answer_has_no_basis(self):
        d = self.doc("fattura_2.pdf")
        cc.send(self.con, STAFF, self.case, d)  # stub
        self.assertNotIn("basis", self.check(d))

    # errors -----------------------------------------------------------------------
    def fail(self, code, name):
        d = self.doc(f"fattura_{code}{name}.pdf")
        core = live_core([(code, json.dumps({"error": {"code": name, "message": "m"}}))], [])
        return cc.send(self.con, STAFF, self.case, d, core=core)

    def test_rate_limit_and_monthly_quota_are_429_with_a_message(self):
        for name in ("RATE_LIMITED", "QUOTA_EXCEEDED"):
            code, out = self.fail(429, name)
            self.assertEqual((code, out["error"]), (429, "error"))
            self.assertIn("it", out["message"])

    def test_request_in_progress_is_unknown_not_error(self):
        code, out = self.fail(409, "REQUEST_IN_PROGRESS")
        self.assertEqual((code, out["error"]), (502, "unknown"))

    def test_key_reused_is_an_error(self):
        code, out = self.fail(422, "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(out["error"], "error")


if __name__ == "__main__":
    unittest.main()
