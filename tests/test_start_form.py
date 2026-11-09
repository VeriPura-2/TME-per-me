import os
import unittest
from unittest import mock

os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, db, vat_check


def user(name):
    who = {"user": name, "roles": []}
    accounts.record_consent(app.con(), name, app.TERMS_VERSION, "en", True)
    return who


class StartForm(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(app, "client", side_effect=AssertionError("the start form must not call the AI"))
        p.start(); self.addCleanup(p.stop)
        v = mock.patch.object(vat_check, "vies", return_value={"state": "unavailable", "name": None, "address": None, "checked_at": "2026-11-04T12:00:00+00:00"})
        v.start(); self.addCleanup(v.stop)

    def test_product_and_country_give_the_real_checklist_without_ai(self):
        who = user("start-a")
        code, out = app.handle_start({"category": "pasta", "country": "France"}, who)
        self.assertEqual(code, 200)
        self.assertTrue(out["covered"])
        self.assertEqual(out["path_type"], 4)
        code, j = app.handle_journey({"case_id": out["case_id"]}, who)
        self.assertEqual(code, 200)
        self.assertFalse(j["required_docs"]["simulated"])
        case = db.case_read(app.con(), out["case_id"])
        self.assertEqual((case["product"]["category"], case["market"]["country"]), ("pasta", "France"))

    def test_lane_outside_wave1_is_marked_not_covered(self):
        code, out = app.handle_start({"category": "bakery", "country": "France"}, user("start-b"))
        self.assertEqual(code, 200)
        self.assertFalse(out["covered"])

    def test_description_is_saved_with_the_product(self):
        who = user("start-desc")
        code, out = app.handle_start({"category": "wine", "country": "France", "description": "  Barbera d'Asti DOCG, 750 ml  "}, who)
        self.assertEqual(code, 200)
        case = db.case_read(app.con(), out["case_id"])
        self.assertEqual(case["product"]["name_brand"], "Barbera d'Asti DOCG, 750 ml")

    def test_other_eu_country_creates_a_project_that_is_not_covered(self):
        who = user("start-eu")
        code, out = app.handle_start({"category": "wine", "country": "other", "other_country": "EU: Sweden"}, who)
        self.assertEqual(code, 200)
        self.assertFalse(out["covered"])
        self.assertEqual(out["requested"]["country"], "EU: Sweden")

    def test_any_eu_country_by_name_gets_the_checklist(self):
        for i, c in enumerate(("Sweden", "Poland", "Greece", "Ireland")):
            code, out = app.handle_start({"category": "wine", "country": c}, user("start-eu%d" % i))
            self.assertEqual(code, 200)
            self.assertTrue(out["covered"], c)

    def test_covered_eu_state_gets_the_checklist(self):
        code, out = app.handle_start({"category": "wine", "country": "Germany"}, user("start-de"))
        self.assertEqual(code, 200)
        self.assertTrue(out["covered"])

    def test_switzerland_is_covered(self):
        code, out = app.handle_start({"category": "wine", "country": "Switzerland"}, user("start-ch"))
        self.assertEqual(code, 200)
        self.assertTrue(out["covered"])

    def test_unknown_values_are_ignored_and_empty_form_refused(self):
        who = user("start-c")
        self.assertEqual(app.handle_start({"category": "caviar", "country": "Japan"}, who)[0], 400)
        self.assertEqual(app.handle_start({}, who)[0], 400)

    def test_valid_vat_creates_the_company(self):
        who = user("start-d")
        code, out = app.handle_start({"category": "wine", "vat": "01765920051", "legal_name": "A&O"}, who)
        self.assertEqual(code, 200)
        self.assertEqual(out["account"]["status"], "created")
        row = app.con().execute("SELECT company_id FROM cases WHERE id=?", (out["case_id"],)).fetchone()
        self.assertTrue(row["company_id"])

    def test_bad_vat_still_starts_and_reports_the_error(self):
        code, out = app.handle_start({"category": "wine", "vat": "12345"}, user("start-e"))
        self.assertEqual(code, 200)
        self.assertIn("vat_error", out)
        self.assertNotIn("account", out)

    def test_member_of_a_company_gets_the_case_in_that_company(self):
        who = user("start-f")
        _, first = app.handle_start({"category": "wine", "vat": "00743110157"}, who)
        cid = app.con().execute("SELECT company_id FROM cases WHERE id=?", (first["case_id"],)).fetchone()["company_id"]
        _, out = app.handle_start({"category": "pasta", "country": "UK"}, who)
        row = app.con().execute("SELECT company_id FROM cases WHERE id=?", (out["case_id"],)).fetchone()
        self.assertEqual(row["company_id"], cid)

    def test_sign_in_and_consent_required(self):
        self.assertEqual(app.handle_start({"category": "pasta"}, None)[0], 400)
        self.assertEqual(app.handle_start({"category": "pasta"}, {"user": "no-consent", "roles": []})[0], 403)

    def test_japan_is_no_longer_offered(self):
        from vialibera import fields
        self.assertNotIn("Japan", app.START_COUNTRIES)
        self.assertNotIn("Japan", str(fields.REQUIRED))


if __name__ == "__main__":
    unittest.main()
