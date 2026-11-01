import json
import os
import tempfile
import unittest

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
from vialibera import core_checks as cc, db, docs
from vialibera.adapters.base import AdapterError
from vialibera.adapters.core import VeriPuraCore, outcome

STAFF = {"user": "staff1", "org": None, "roles": ["veripura_superadmin"]}
SUPPORT = {"user": "sup1", "org": None, "roles": ["veripura_support"]}
CLIENT = {"user": "c1", "org": None, "roles": []}
PDF = b"%PDF-1.4 test invoice"


def live_core(responses, calls):
    """A live-mode adapter whose HTTP layer returns canned responses and records calls."""
    def http(method, url, key, body=None, timeout=60):
        calls.append((method, url, key, body))
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    os.environ["CORE_API_URL"], os.environ["CORE_API_KEY"] = "https://core.example/partnerApi", "k-test"
    try:
        return VeriPuraCore(http=http)
    finally:
        del os.environ["CORE_API_URL"], os.environ["CORE_API_KEY"]


class CoreChecks(unittest.TestCase):
    def setUp(self):
        self.con = db.connect()
        self.case = db.create_case(self.con, 1, owner_sub="c1")
        db.case_write(self.con, self.case, "product", {"category": "pasta", "name_brand": "Pasta X"})
        db.case_write(self.con, self.case, "market", {"country": "UK"})
        db.case_write(self.con, self.case, "company", {"legal_name": "Pastificio Test srl"})
        self.con.commit()
        _, out = docs.upload(self.con, CLIENT, "fattura_123.pdf", PDF, case_id=self.case)
        self.doc = out["id"]

    def test_outcome_mapping(self):
        self.assertEqual(outcome("Validated", "GREEN", False), "matched")
        self.assertEqual(outcome("Pending Review", "YELLOW", True), "flagged")
        self.assertEqual(outcome("Validated", "GREEN", True), "flagged")
        self.assertEqual(outcome("Rejected", "RED", False), "flagged_critical")
        self.assertEqual(outcome("Pending", None, False), "not_checked")

    def test_test_mode_without_key_is_simulated(self):
        self.assertEqual(cc.adapter().mode, "stub")
        code, out = cc.send(self.con, STAFF, self.case, self.doc)
        self.assertEqual(code, 200)
        self.assertTrue(out["simulated"])
        s = cc.summary(self.con, self.case)
        self.assertTrue(s["documents"][0]["check"]["simulated"])

    def test_only_superadmin_sends(self):
        self.assertEqual(cc.send(self.con, CLIENT, self.case, self.doc)[0], 403)
        self.assertEqual(cc.send(self.con, SUPPORT, self.case, self.doc)[0], 403)

    def test_live_first_send_creates_consignment_with_shipment(self):
        calls = []
        resp = {"consignmentId": "abc", "docType": "Commercial Invoice", "status": "Validated", "validationLevel": "GREEN",
                "requiresHumanReview": False, "alerts": []}
        core = live_core([(200, json.dumps(resp))], calls)
        code, out = cc.send(self.con, STAFF, self.case, self.doc, core=core)
        self.assertEqual((code, out["outcome"], out["simulated"]), (200, "matched", False))
        method, url, key, body = calls[0]
        self.assertEqual((method, url, key), ("POST", "https://core.example/partnerApi/v1/documents", "k-test"))
        self.assertEqual(body["shipment"], {"exportFrom": "Italy", "importTo": "United Kingdom", "product": "Pasta X",
                                            "hsCode": "1902", "sellerName": "Pastificio Test srl"})
        self.assertEqual(body["docType"], "Commercial Invoice")
        # second document joins the same consignment
        _, o2 = docs.upload(self.con, CLIENT, "packing_list.pdf", PDF + b"2", case_id=self.case)
        core2 = live_core([(200, json.dumps({**resp, "docType": "Packing List"}))], calls)
        cc.send(self.con, STAFF, self.case, o2["id"], core=core2)
        self.assertEqual(calls[1][3]["consignmentId"], "abc")
        self.assertNotIn("shipment", calls[1][3])

    def test_raw_response_never_contains_the_file(self):
        calls = []
        resp = {"consignmentId": "abc", "docType": "X", "status": "Pending", "requiresHumanReview": False, "alerts": []}
        cc.send(self.con, STAFF, self.case, self.doc, core=live_core([(200, json.dumps(resp))], calls))
        for r in self.con.execute("SELECT body FROM raw_responses").fetchall():
            self.assertNotIn("fileBase64", r["body"])

    def test_timeout_is_unknown_and_blocks_resend_until_status(self):
        calls = []
        core = live_core([AdapterError("unavailable", "TimeoutError")], calls)
        code, out = cc.send(self.con, STAFF, self.case, self.doc, core=core)
        self.assertEqual((code, out["error"]), (502, "unknown"))
        self.assertEqual(cc.send(self.con, STAFF, self.case, self.doc, core=core)[0], 409)
        self.assertEqual(len(calls), 1)  # never retried

    def test_http_error_is_error_not_unknown(self):
        core = live_core([(400, json.dumps({"error": {"code": "INVALID_REQUEST", "message": "bad"}}))], [])
        code, out = cc.send(self.con, STAFF, self.case, self.doc, core=core)
        self.assertEqual(out["error"], "error")

    def test_lane_must_be_wave1(self):
        db.case_write(self.con, self.case, "market", {"country": "Japan"})
        self.con.commit()
        self.assertEqual(cc.send(self.con, STAFF, self.case, self.doc)[0], 400)

    def test_document_must_be_in_project(self):
        other = db.create_case(self.con, 1, owner_sub="c1")
        self.assertEqual(cc.send(self.con, STAFF, other, self.doc)[0], 404)

    def test_auto_switch_superadmin_only_and_paid_projects_only(self):
        self.assertEqual(cc.set_auto(self.con, SUPPORT, True)[0], 403)
        self.assertIsNone(cc.on_upload(self.con, self.case, self.doc))  # off by default
        cc.set_auto(self.con, STAFF, True)
        self.assertIsNone(cc.on_upload(self.con, self.case, self.doc))  # project not paid
        self.con.execute("UPDATE cases SET status='paid' WHERE id=?", (self.case,))
        code, out = cc.on_upload(self.con, self.case, self.doc)
        self.assertEqual(code, 200)
        last = self.con.execute("SELECT via FROM core_checks").fetchone()
        self.assertEqual(last["via"], "auto")

    def test_refresh_stores_roadmap_for_staff_only(self):
        cc.send(self.con, STAFF, self.case, self.doc)
        self.assertEqual(cc.refresh(self.con, CLIENT, self.case)[0], 403)
        self.assertEqual(cc.refresh(self.con, SUPPORT, self.case)[0], 200)
        staff_view = cc.summary(self.con, self.case, staff=True)
        self.assertIn("roadmap", staff_view["core_status"])
        client_view = cc.summary(self.con, self.case)
        self.assertNotIn("core_status", client_view)
        self.assertNotIn("core_status", client_view["documents"][0]["check"])

    def test_test_consignment_is_replaced_when_live(self):
        cc.send(self.con, STAFF, self.case, self.doc)  # stub creates SIM- consignment
        calls = []
        resp = {"consignmentId": "real1", "docType": "X", "status": "Pending", "requiresHumanReview": False, "alerts": []}
        _, o2 = docs.upload(self.con, CLIENT, "packing_list.pdf", PDF + b"3", case_id=self.case)
        cc.send(self.con, STAFF, self.case, o2["id"], core=live_core([(200, json.dumps(resp))], calls))
        self.assertIn("shipment", calls[0][3])
        self.assertEqual(self.con.execute("SELECT consignment_id FROM core_consignments").fetchone()[0], "real1")
