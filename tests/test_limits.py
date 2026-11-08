import os
import unittest
from unittest import mock

os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, db, limits, vat_check


def user(name):
    accounts.record_consent(app.con(), name, app.TERMS_VERSION, "en", True)
    return {"user": name, "roles": []}


class Limits(unittest.TestCase):
    def setUp(self):
        v = mock.patch.object(vat_check, "vies", return_value={"state": "unavailable", "name": None, "address": None,
                                                                "checked_at": "2026-11-09T12:00:00+00:00"})
        v.start(); self.addCleanup(v.stop)
        p = mock.patch.object(limits, "LIMITS_START", "2000-01-01"); p.start(); self.addCleanup(p.stop)  # nobody grandfathered

    def start(self, who, cat, country):
        return app.handle_start({"category": cat, "country": country}, who)

    def test_explore_one_covered_project_and_deleting_does_not_free_it(self):
        who = user("lim-a")
        code, out = self.start(who, "pasta", "France")
        self.assertEqual(code, 200)
        code, err = self.start(who, "wine", "Germany")
        self.assertEqual((code, err["error"], err["limit"]), (403, "plan_limit", "covered"))
        app.con().execute("DELETE FROM cases WHERE id=?", (out["case_id"],)); app.con().commit()
        self.assertEqual(self.start(who, "wine", "Germany")[0], 403)

    def test_explore_two_uncovered_and_they_do_not_use_the_covered_slot(self):
        who = user("lim-b")
        self.assertEqual(self.start(who, "bakery", "France")[0], 200)
        self.assertEqual(self.start(who, "bakery", "USA")[0], 200)
        code, err = self.start(who, "bakery", "Spain")
        self.assertEqual((code, err["limit"]), (403, "uncovered"))
        self.assertEqual(self.start(who, "pasta", "France")[0], 200)

    def test_deleted_uncovered_project_frees_its_place(self):
        who = user("lim-c")
        a = self.start(who, "bakery", "France")[1]["case_id"]
        self.start(who, "bakery", "USA")
        app.con().execute("DELETE FROM cases WHERE id=?", (a,)); app.con().commit()
        self.assertEqual(self.start(who, "bakery", "Spain")[0], 200)

    def test_paid_plan_caps(self):
        who = user("lim-d")
        accounts.set_plan(app.con(), "lim-d", "parti")
        for _ in range(5):
            self.assertEqual(self.start(who, "pasta", "France")[0], 200)
        self.assertEqual(self.start(who, "pasta", "France")[0], 403)
        for _ in range(10):
            self.assertEqual(self.start(who, "bakery", "USA")[0], 200)
        self.assertEqual(self.start(who, "bakery", "USA")[0], 403)

    def test_grow_has_no_covered_cap_and_50_uncovered(self):
        who = user("lim-e")
        accounts.set_plan(app.con(), "lim-e", "cresci")
        for _ in range(7):
            self.assertEqual(self.start(who, "pasta", "France")[0], 200)
        for _ in range(50):
            self.assertEqual(self.start(who, "bakery", "USA")[0], 200)
        self.assertEqual(self.start(who, "bakery", "USA")[0], 403)

    def test_account_with_a_project_before_the_start_date_is_grandfathered(self):
        who = user("lim-f")
        c = app.con()
        db.create_case(c, 1, owner_sub="lim-f")
        c.execute("UPDATE cases SET created_at='2026-11-01T00:00:00+00:00' WHERE owner_sub='lim-f'"); c.commit()
        with mock.patch.object(limits, "LIMITS_START", "2026-11-09"):
            for _ in range(3):
                self.assertEqual(self.start(who, "pasta", "France")[0], 200)

    def test_free_check_once_on_a_covered_project_only(self):
        who = user("lim-g")
        unc = self.start(who, "bakery", "France")[1]["case_id"]
        cov = self.start(who, "pasta", "France")[1]["case_id"]
        c = app.con()
        self.assertFalse(limits.take_free_check(c, who, unc))
        self.assertTrue(limits.take_free_check(c, who, cov))
        self.assertFalse(limits.take_free_check(c, who, cov))

    def test_paid_plan_checks_are_not_limited(self):
        who = user("lim-h")
        accounts.set_plan(app.con(), "lim-h", "parti")
        cov = self.start(who, "pasta", "France")[1]["case_id"]
        self.assertTrue(limits.take_free_check(app.con(), who, cov))
        self.assertTrue(limits.take_free_check(app.con(), who, cov))


if __name__ == "__main__":
    unittest.main()


class UsageTest(unittest.TestCase):
    def test_usage_for_a_new_account(self):
        u = limits.usage(app.con(), "usage-new")
        self.assertEqual(u["plan"], "esplora")
        self.assertEqual(u["covered"], {"used": 0, "cap": 1})
        self.assertEqual(u["uncovered"], {"used": 0, "cap": 2})
        self.assertEqual(u["free_check"], {"allowed": 1, "used": 0})

    def test_handle_account_needs_sign_in(self):
        self.assertEqual(app.handle_account({}, None)[0], 400)
        code, out = app.handle_account({}, {"user": "usage-b", "roles": []})
        self.assertEqual((code, out["plan"]), (200, "esplora"))
