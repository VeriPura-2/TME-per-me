import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, db, permissions, team
from test_journey import who


def company(name, members):
    """members: {user: (role, status)}. Returns (company_id, case_id)."""
    c = app.con()
    if name in ("A", "T"):  # fresh start for each test of the two main fixtures
        for t in ("memberships", "companies", "team_invites"):
            c.execute(f"DELETE FROM {t}")
    cid = "co-" + name
    c.execute("INSERT INTO companies(id, vat, legal_name, created_at) VALUES (?,?,?,?)", (cid, "IT" + name, name, db.now()))
    for u, (role, status) in members.items():
        c.execute("INSERT INTO memberships(company_id, user_sub, role, status, created_at) VALUES (?,?,?,?,?)", (cid, u, role, status, db.now()))
        accounts.record_consent(c, u, app.TERMS_VERSION, "en", True)
    case = db.create_case(c, 1, owner_sub=next(iter(members)))
    c.execute("UPDATE cases SET company_id=? WHERE id=?", (cid, case))
    db.case_write(c, case, "product", {"category": "wine"})
    c.commit()
    return cid, case


class RolesTest(unittest.TestCase):
    def setUp(self):
        self.cid, self.case = company("A", {"own": ("owner", "active"), "man": ("manager", "active"),
                                            "mem": ("member", "active"), "rev": ("reviewer", "active"),
                                            "pen": ("member", "pending")})

    def test_everyone_active_can_read(self):
        for u in ("own", "man", "mem", "rev"):
            self.assertEqual(app.handle_journey({"case_id": self.case}, who(u))[0], 200, u)

    def test_pending_and_strangers_see_nothing(self):
        for u in ("pen", "stranger"):
            self.assertEqual(app.handle_journey({"case_id": self.case}, who(u))[0], 404, u)

    def test_reviewer_cannot_write(self):
        self.assertEqual(app.handle_chat({"message": "hi", "case_id": self.case}, who=who("rev"))[0], 403)
        self.assertEqual(app.handle_eori_pdf({"case_id": self.case, "values": {}}, who("rev"))[0], 403)
        self.assertEqual(app.handle_doc_update("x", {"doc_type": "label"}, who("rev"))[0], 403)

    def test_only_owner_and_manager_can_order(self):
        sel = {"case_id": self.case, "selected": ["tariff_lookup"]}
        self.assertEqual(app.handle_simpay(dict(sel), who("mem"))[0], 403)
        self.assertEqual(app.handle_simpay(dict(sel), who("rev"))[0], 403)
        self.assertEqual(app.handle_simpay(dict(sel), who("man"))[0], 200)
        self.assertEqual(app.handle_simpay(dict(sel), who("own"))[0], 200)

    def test_only_owner_chooses_the_company_plan(self):
        self.assertEqual(app.handle_plan({"plan": "cresci"}, who("man"))[0], 403)
        self.assertEqual(app.handle_plan({"plan": "cresci"}, who("own"))[0], 200)
        # the company pays: everyone sees the same plan
        self.assertEqual(app.handle_plan({}, who("rev"))[1]["plan"], "cresci")
        self.assertEqual(app.handle_journey({"case_id": self.case}, who("mem"))[1]["plan"], "cresci")

    def test_other_company_is_closed(self):
        c = app.con(); c.execute("DELETE FROM companies WHERE id='co-B'"); c.execute("DELETE FROM memberships WHERE company_id='co-B'")
        _, other = company("B", {"bob": ("owner", "active")})
        self.assertEqual(app.handle_journey({"case_id": other}, who("own"))[0], 404)
        self.assertEqual(app.handle_chat({"message": "hi", "case_id": other}, who=who("own"))[0], 404)

    def test_removed_person_loses_access_even_to_a_case_they_started(self):
        self.assertEqual(team.remove(app.con(), who("own"), "own")[0], 400)  # last owner
        self.assertEqual(team.remove(app.con(), who("own"), "mem")[0], 200)
        self.assertEqual(app.handle_journey({"case_id": self.case}, who("mem"))[0], 404)


class TeamTest(unittest.TestCase):
    def setUp(self):
        self.cid, self.case = company("T", {"own": ("owner", "active"), "mem": ("member", "active"), "pen": ("member", "pending")})
        self.c = app.con()

    def test_only_owner_sees_pending_and_manages(self):
        o = team.overview(self.c, who("own"))[1]
        self.assertTrue(o["can_manage"])
        self.assertIn("pen", [m["user"] for m in o["members"]])
        m = team.overview(self.c, who("mem"))[1]
        self.assertFalse(m["can_manage"])
        self.assertNotIn("pen", [x["user"] for x in m["members"]])
        self.assertEqual(team.decide(self.c, who("mem"), "pen", True)[0], 403)
        self.assertEqual(team.invite(self.c, who("mem"), "member")[0], 403)

    def test_owner_approves_then_person_gets_access(self):
        self.assertEqual(app.handle_journey({"case_id": self.case}, who("pen"))[0], 404)
        self.assertEqual(team.decide(self.c, who("own"), "pen", True)[0], 200)
        self.assertEqual(app.handle_journey({"case_id": self.case}, who("pen"))[0], 200)
        self.assertEqual(permissions.role_in(self.c, self.cid, "pen"), "member")

    def test_owner_refuses(self):
        self.assertEqual(team.decide(self.c, who("own"), "pen", False)[0], 200)
        self.assertIsNone(self.c.execute("SELECT 1 FROM memberships WHERE user_sub='pen'").fetchone())

    def test_role_change_keeps_one_owner(self):
        self.assertEqual(team.set_role(self.c, who("own"), "own", "member")[0], 400)
        self.assertEqual(team.set_role(self.c, who("own"), "mem", "owner")[0], 200)
        self.assertEqual(team.set_role(self.c, who("own"), "mem", "king")[0], 400)
        self.assertEqual(team.set_role(self.c, who("own"), "own", "manager")[0], 200)

    def test_invite_link_joins_once_and_expires(self):
        tok = team.invite(self.c, who("own"), "reviewer")[1]["token"]
        self.assertEqual(team.accept(self.c, who("new"), tok)[1]["role"], "reviewer")
        self.assertEqual(permissions.role_in(self.c, self.cid, "new"), "reviewer")
        self.assertEqual(team.accept(self.c, who("other"), tok)[0], 400)  # used
        old = team.invite(self.c, who("own"), "member")[1]["token"]
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        self.c.execute("UPDATE team_invites SET expires_at=? WHERE token=?", (past, old)); self.c.commit()
        self.assertEqual(team.accept(self.c, who("late"), old)[0], 400)

    def test_person_without_company_keeps_full_rights_on_own_work(self):
        self.assertEqual(permissions.my_role(self.c, who("solo")), "owner")
        self.assertEqual(app.handle_plan({"plan": "parti"}, who("solo"))[0], 200)


class CompanyCreditAndConsentTest(unittest.TestCase):
    def setUp(self):
        from test_team import company as mk
        self.cid, self.case = mk("T", {"own": ("owner", "active"), "man": ("manager", "active"), "mem": ("member", "active")})
        self.c = app.con()

    def test_invite_credit_belongs_to_the_company(self):
        from vialibera import invites
        code = invites.get_or_create(self.c, "mem")  # a member invites, the company is credited
        invites.accept(self.c, "newb", code)
        accounts.record_consent(self.c, "newb", app.TERMS_VERSION, "en", True)
        self.assertEqual(app.handle_plan({"plan": "parti"}, who("newb"))[1]["invite_credit"], "granted")
        self.assertEqual(invites.balance(self.c, "own"), 2000)
        self.assertEqual(invites.balance(self.c, "mem"), 2000)
        self.assertEqual(invites.balance(self.c, "newb"), 2000)  # the newcomer had no company: held personally
        # a manager pays: the company credit is used, everyone in the company sees the lower balance
        out = app.handle_simpay({"case_id": self.case, "selected": ["label_check"]}, who("man"))[1]["payment"]["data"]
        self.assertGreater(out["credit_used_cents"], 0)
        self.assertEqual(invites.balance(self.c, "own"), 2000 - out["credit_used_cents"])
        self.assertEqual(invites.balance(self.c, "newb"), 2000)  # not touched

    def test_personal_credit_follows_the_person_into_a_company(self):
        from vialibera import invites
        self.c.execute("INSERT INTO credit_ledger(user_sub, delta_cents, kind, code, at, expires_at, simulated, note) VALUES (?,?,?,?,?,?,?,?)",
                       ("mem", 500, "grant", "x", db.now(), "2999-01-01T00:00:00Z", 0, "invite"))
        self.c.commit()
        self.assertEqual(invites.balance(self.c, "mem"), 500)
        self.assertEqual(invites.apply(self.c, "mem", 800), 500)

    def test_owner_accepts_terms_for_the_company(self):
        c = self.c
        c.execute("DELETE FROM consents")
        c.commit()
        self.assertFalse(app.consent_ok(who("mem")))
        body = {"accept_terms": True, "accept_onerous": True, "authorised": True}
        self.assertEqual(app.handle_company_consent(body, who("mem"))[0], 403)  # not an owner
        self.assertEqual(app.handle_company_consent({"accept_terms": True}, who("own"))[0], 400)  # needs all three
        self.assertEqual(app.handle_company_consent(body, who("own"))[0], 200)
        self.assertTrue(app.consent_ok(who("mem")))
        self.assertTrue(app.consent_ok(who("man")))
        self.assertFalse(app.consent_ok(who("stranger")))
        self.assertFalse(accounts.has_consent(c, "mem", "2099-new-version"))  # new version: owner must accept again
        self.assertIsNotNone(team.overview(c, who("mem"))[1]["company"]["terms_accepted_at"])

    def test_removed_member_is_no_longer_covered(self):
        self.c.execute("DELETE FROM consents"); self.c.commit()
        app.handle_company_consent({"accept_terms": True, "accept_onerous": True, "authorised": True}, who("own"))
        team.remove(self.c, who("own"), "mem")
        self.assertFalse(app.consent_ok(who("mem")))
