import json
import os
import tempfile
import unittest

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
from vialibera import accounts, db, jobs, requirements, tems, vat_check
from vialibera.adapters.tariff import UKTradeTariff, USITCHts

FX = os.path.join(os.path.dirname(__file__), "fixtures")
VALID = json.dumps({"isValid": True, "userError": "VALID", "name": "ALFA S.R.L.", "address": "VIA ROMA 1 \n12051 ALBA CN\n"})
NOT_IN = json.dumps({"isValid": False, "userError": "INVALID", "name": "---", "address": "---"})
DOWN = json.dumps({"isValid": False, "userError": "MS_UNAVAILABLE"})


def load(name):
    with open(os.path.join(FX, name)) as f:
        return f.read()


class Vat(unittest.TestCase):
    def setUp(self):
        self.con = db.connect()

    def test_italian_only(self):
        self.assertEqual(vat_check.italian("01765920051"), ("IT01765920051", None))
        self.assertIsNotNone(vat_check.italian("DE123456789")[1])
        self.assertIsNotNone(vat_check.italian("IT01765920052")[1])  # check digit

    def test_vies_states(self):
        v = vat_check.vies("IT01765920051", http=lambda u: VALID)
        self.assertEqual((v["state"], v["name"], v["address"]), ("valid", "ALFA S.R.L.", "VIA ROMA 1 12051 ALBA CN"))
        self.assertEqual(vat_check.vies("IT01765920051", http=lambda u: NOT_IN)["state"], "not_in_vies")
        self.assertEqual(vat_check.vies("IT01765920051", http=lambda u: DOWN)["state"], "unavailable")
        self.assertEqual(vat_check.vies("IT01765920051")["state"], "unavailable")  # network off in tests

    def test_valid_marks_company_verified_not_in_vies_does_not_block(self):
        self.con.execute("INSERT INTO companies(id, vat, legal_name, created_at) VALUES ('c1','IT01765920051','A',?)", (db.now(),))
        vat_check.check_company(self.con, "c1", http=lambda u: NOT_IN)
        r = self.con.execute("SELECT status, vies_state FROM companies WHERE id='c1'").fetchone()
        self.assertEqual((r["status"], r["vies_state"]), ("unverified", "not_in_vies"))
        vat_check.check_company(self.con, "c1", http=lambda u: VALID)
        r = self.con.execute("SELECT status, vies_name FROM companies WHERE id='c1'").fetchone()
        self.assertEqual((r["status"], r["vies_name"]), ("verified", "ALFA S.R.L."))

    def test_chat_refuses_foreign_vat(self):
        cid = db.create_case(self.con, 1, owner_sub="u1")
        db.case_write(self.con, cid, "company", {"vat_number": "DE123456789", "legal_name": "X"})
        out = accounts.attach_company(self.con, cid, {"user": "u1", "org": None, "roles": []})
        self.assertEqual(out["status"], "invalid_vat")

    def test_germany_lane_lists_vies_and_ticks_it_when_confirmed(self):
        self.con.execute("INSERT INTO companies(id, vat, legal_name, created_at, vies_state) VALUES ('c2','IT01765920051','A',?,'valid')", (db.now(),))
        req = requirements.required("pasta", "Germany", set())
        self.assertIn("vies", [i["id"] for i in req["data"]["items"]])
        vat_check.apply_to_checklist(self.con, "c2", req)
        self.assertTrue([i for i in req["data"]["items"] if i["id"] == "vies"][0]["on_file"])
        self.assertNotIn("vies", [i["id"] for i in requirements.required("pasta", "UK", set())["data"]["items"]])


class Daily(unittest.TestCase):
    def setUp(self):
        self.con = db.connect()
        self.uk = UKTradeTariff(http=lambda url: load("uk_1902199090.json"))
        self.us = USITCHts(http=lambda url: load("us_" + url.rsplit("=", 1)[1] + ".json"))
        self.pages = {u: "page " + u for u in jobs.source_urls()}

    def run_job(self, vies_http=None):
        return jobs.run_daily(self.con, uk=self.uk, us=self.us, fetch=lambda u: self.pages[u], vies_http=vies_http)

    def test_first_run_is_quiet_and_known_answers_pass(self):
        out = self.run_job()
        self.assertEqual(out["tariffs"]["known_answers"], "pass")
        self.assertEqual(out["sources"]["changed"], 0)
        self.assertEqual(jobs.changes(self.con), [])

    def test_duty_change_is_reported(self):
        self.run_job()
        changed = json.loads(load("us_1509.20.20.json")); changed[0]["general"] = "7¢/kg on contents and container"
        self.us = USITCHts(http=lambda url: json.dumps(changed) if "20.20" in url else load("us_1509.20.90.json"))
        out = self.run_job()
        self.assertEqual(out["tariffs"]["known_answers"], "fail")
        self.assertEqual(out["tariffs"]["duties_changed"], 1)
        kinds = {c["kind"] for c in jobs.changes(self.con)}
        self.assertEqual(kinds, {"known_answer_failed", "duty_changed"})

    def test_source_change_sends_items_back_to_staff_until_reconfirmed(self):
        self.run_job()
        url = requirements.SRC["gac_cheese"]
        self.pages[url] = "the rules changed"
        out = self.run_job()
        self.assertEqual(out["sources"]["changed"], 1)
        req = requirements.required("cheese and dairy", "Canada", set())
        tems.apply_confirmations(self.con, "case1", req)
        jobs.apply_source_flags(self.con, "case1", req)
        item = [i for i in req["data"]["items"] if i["id"] == "gac_permit"][0]
        self.assertFalse(item["verified"])
        self.assertTrue(item["source_changed"])
        # a confirmation after the change clears it
        self.con.execute("INSERT INTO checklist_confirmations(case_id, item_id, confirmed_by, by_label, at) VALUES ('case1','gac_permit','t','TEM','9999')")
        req = requirements.required("cheese and dairy", "Canada", set())
        tems.apply_confirmations(self.con, "case1", req)
        jobs.apply_source_flags(self.con, "case1", req)
        self.assertTrue([i for i in req["data"]["items"] if i["id"] == "gac_permit"][0]["verified"])

    def test_unreachable_source_is_reported(self):
        def boom(u):
            raise OSError("down")
        out = jobs.run_daily(self.con, uk=self.uk, us=self.us, fetch=boom)
        self.assertEqual(out["sources"]["unreachable"], len(jobs.source_urls()))

    def test_vies_recheck_reports_newly_confirmed(self):
        self.con.execute("INSERT INTO companies(id, vat, legal_name, created_at, vies_state) VALUES ('c3','IT01765920051','A',?,'not_in_vies')", (db.now(),))
        self.run_job(vies_http=lambda u: VALID)
        self.assertIn("vies_rechecked", {c["kind"] for c in jobs.changes(self.con)})

    def test_dismiss(self):
        self.run_job()
        jobs._change(self.con, "duty_changed", "x", "test")
        cid = jobs.changes(self.con)[0]["id"]
        jobs.dismiss(self.con, {"user": "admin"}, cid)
        self.assertEqual(jobs.changes(self.con), [])


class Watch(unittest.TestCase):
    def test_blocked_sources_are_watched_elsewhere_and_flag_the_right_items(self):
        urls = jobs.source_urls()
        self.assertNotIn(requirements.SRC["usda_dairy"], urls)
        self.assertNotIn(requirements.SRC["cfia_sfc"], urls)
        self.assertIn(requirements.WATCH["usda_dairy"], urls)
        con = db.connect()
        pages = {u: "v1" for u in urls}
        uk = UKTradeTariff(http=lambda url: load("uk_1902199090.json"))
        us = USITCHts(http=lambda url: load("us_" + url.rsplit("=", 1)[1] + ".json"))
        jobs.run_daily(con, uk=uk, us=us, fetch=lambda u: pages[u])
        pages[requirements.WATCH["cfia_sfc"]] = "v2"
        jobs.run_daily(con, uk=uk, us=us, fetch=lambda u: pages[u])
        req = requirements.required("pasta", "Canada", set())
        jobs.apply_source_flags(con, "c", req)
        sfc = [i for i in req["data"]["items"] if i["id"] == "sfc"][0]
        self.assertTrue(sfc["source_changed"])
        self.assertEqual(sfc["source"], requirements.SRC["cfia_sfc"])  # clients still see the CFIA page
