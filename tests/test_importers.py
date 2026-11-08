import json
import os
import unittest
from unittest import mock

os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, importers, tools, vat_check

EM_DASH = "—"
PERSONAL = ("email", "phone", "decision", "contact", "linkedin")


def user(name, roles=None):
    accounts.record_consent(app.con(), name, app.TERMS_VERSION, "en", True)
    return {"user": name, "roles": roles or []}


class ImporterData(unittest.TestCase):
    def test_company_level_only_and_in_lane_countries(self):
        data = json.load(open(importers._PATH, encoding="utf-8"))
        self.assertEqual(data["updated"], "2026-10-11")
        self.assertEqual({i["country"] for i in data["importers"]}, {"US", "UK", "CA", "DE", "CH"})
        for i in data["importers"]:
            self.assertEqual(set(i), {"company", "country", "city", "segment", "focus", "website"})
            self.assertIn(i["segment"], ("wine", "food", "both"))
            self.assertNotIn("@", " ".join(i.values()))

    def test_no_personal_fields_in_the_file(self):
        raw = open(importers._PATH, encoding="utf-8").read().lower()
        for w in PERSONAL:
            self.assertNotIn('"' + w, raw)

    def test_product_filter(self):
        wine = importers.for_project("wine", "USA", "esplora")
        self.assertTrue(wine["count"] > 0)
        self.assertTrue(all(i["segment"] in ("wine", "both") for i in wine["importers"]))
        oil = importers.for_project("olive oil", "United States", "esplora")
        self.assertTrue(all(i["segment"] in ("food", "both") for i in oil["importers"]))

    def test_country_without_a_list(self):
        out = importers.for_project("wine", "France", "parti")
        self.assertEqual((out["count"], out["listed"], out["country"]), (0, False, "FR"))


class ImporterEndpoint(unittest.TestCase):
    def setUp(self):
        v = mock.patch.object(vat_check, "vies", return_value={"state": "unavailable", "name": None, "address": None, "checked_at": "2026-11-06T12:00:00+00:00"})
        v.start(); self.addCleanup(v.stop)

    def listing(self, name, country="USA", plan=None, roles=None):
        who = user(name, roles)
        if plan:
            accounts.set_plan(app.con(), name, plan)
        cid = app.handle_start({"category": "wine", "country": country}, who)[1]["case_id"]
        return app.handle_tools("/tools/importers", {"case_id": cid}, who)

    def test_explore_sees_the_list_without_websites(self):
        code, out = self.listing("imp-free")
        self.assertEqual(code, 200)
        self.assertGreater(out["count"], 0)
        self.assertFalse(out["websites"])
        self.assertTrue(all("website" not in i for i in out["importers"]))

    def test_paid_plan_sees_websites(self):
        code, out = self.listing("imp-paid", plan="parti")
        self.assertTrue(out["websites"])
        self.assertTrue(any(i.get("website") for i in out["importers"]))

    def test_superadmin_sees_websites(self):
        code, out = self.listing("imp-super", roles=["veripura_superadmin"])
        self.assertTrue(out["websites"])

    def test_stranger_cannot_read_another_projects_list(self):
        who = user("imp-owner")
        cid = app.handle_start({"category": "wine", "country": "USA"}, who)[1]["case_id"]
        self.assertEqual(app.handle_tools("/tools/importers", {"case_id": cid}, user("imp-other"))[0], 404)

    def test_card_text_is_researched_not_verified_and_has_no_em_dash(self):
        card = {c["id"]: c for c in tools.for_case("wine", "USA")}["importers"]
        blob = json.dumps(card, ensure_ascii=False) + json.dumps(tools.public_catalog(), ensure_ascii=False)
        self.assertNotIn("verified foreign", blob)
        self.assertNotIn(EM_DASH, json.dumps(card, ensure_ascii=False))
        self.assertEqual(card["name"]["en"], "Researched importers")
        self.assertTrue(card["no_tell"])


if __name__ == "__main__":
    unittest.main()
