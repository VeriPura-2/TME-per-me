import os
import unittest

os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, db, invites


def who(u):
    return {"user": u, "org": None, "roles": []}


def user(u):
    accounts.record_consent(app.con(), u, app.TERMS_VERSION, "it", True)
    return who(u)


class InviteTest(unittest.TestCase):
    def test_code_is_stable_per_user(self):
        c = app.con()
        self.assertEqual(invites.get_or_create(c, "a1"), invites.get_or_create(c, "a1"))

    def test_accept_rules(self):
        c = app.con(); code = invites.get_or_create(c, "a2")
        self.assertEqual(invites.accept(c, "a2", code), "self")
        self.assertEqual(invites.accept(c, "b2", "nope"), "invalid")
        self.assertEqual(invites.accept(c, "b2", code), "ok")
        self.assertEqual(invites.accept(c, "b2", code), "already")
        other = invites.get_or_create(c, "x2")
        self.assertEqual(invites.accept(c, "b2", other), "already")  # first inviter wins

    def test_no_credit_until_paid_plan_and_both_sides_get_it(self):
        c = app.con(); code = invites.get_or_create(c, "a3"); invites.accept(c, "b3", code)
        user("a3"); user("b3")
        self.assertEqual(app.handle_plan({"plan": "esplora"}, who("b3"))[1].get("invite_credit"), None)
        self.assertEqual(invites.balance(c, "b3"), 0)
        out = app.handle_plan({"plan": "parti"}, who("b3"))[1]
        self.assertEqual(out["invite_credit"], "granted")
        self.assertEqual((invites.balance(c, "a3"), invites.balance(c, "b3")), (2000, 2000))

    def test_credit_is_granted_once(self):
        c = app.con(); code = invites.get_or_create(c, "a4"); invites.accept(c, "b4", code)
        user("b4")
        app.handle_plan({"plan": "parti"}, who("b4"))
        self.assertEqual(app.handle_plan({"plan": "cresci"}, who("b4"))[1]["invite_credit"], "already_granted")
        self.assertEqual(invites.balance(c, "b4"), 2000)

    def test_amount_not_set_means_no_credit(self):
        c = app.con(); code = invites.get_or_create(c, "a5"); invites.accept(c, "b5", code)
        self.assertEqual(invites.on_first_paid_month(c, "b5", None, 90), "no_amount_set")
        self.assertEqual(invites.balance(c, "b5"), 0)

    def test_expired_credit_does_not_count(self):
        c = app.con(); code = invites.get_or_create(c, "a6"); invites.accept(c, "b6", code)
        invites.on_first_paid_month(c, "b6", 1000, 90, simulated=True)
        c.execute("UPDATE credit_ledger SET expires_at='2000-01-01T00:00:00Z' WHERE user_sub='b6'"); c.commit()
        self.assertEqual(invites.balance(c, "b6"), 0)

    def test_same_company_gets_no_credit(self):
        c = app.con(); code = invites.get_or_create(c, "a7"); invites.accept(c, "b7", code)
        orig = invites._company
        invites._company = lambda con, sub: "same"
        try:
            self.assertEqual(invites.on_first_paid_month(c, "b7", 1000, 90), "same_company")
        finally:
            invites._company = orig

    def test_inviter_cap(self):
        c = app.con(); code = invites.get_or_create(c, "a8")
        os.environ["INVITE_MAX_CREDITED"] = "1"
        try:
            for i in ("b8", "c8"):
                invites.accept(c, i, code)
            self.assertEqual(invites.on_first_paid_month(c, "b8", 1000, 90), "granted")
            self.assertEqual(invites.on_first_paid_month(c, "c8", 1000, 90), "inviter_cap")
        finally:
            del os.environ["INVITE_MAX_CREDITED"]

    def test_inviter_sees_status_only(self):
        c = app.con(); code = invites.get_or_create(c, "a9"); invites.accept(c, "b9", code)
        user("a9")
        out = app.handle_invite({}, who("a9"))[1]
        self.assertEqual(out["invitees"], [{"n": 1, "status": "joined"}])
        self.assertNotIn("b9", str(out))

    def test_credit_reduces_checkout(self):
        c = app.con(); code = invites.get_or_create(c, "a10"); invites.accept(c, "b10", code)
        user("b10"); app.handle_plan({"plan": "parti"}, who("b10"))
        cid = db.create_case(c, 1, owner_sub="b10")
        db.case_write(c, cid, "product", {"category": "wine"}); db.case_write(c, cid, "market", {"needs": "label"}); c.commit()
        out = app.handle_simpay({"case_id": cid, "selected": ["label_check"]}, who("b10"))[1]["payment"]["data"]
        self.assertEqual((out["total_cents"], out["credit_used_cents"], out["payable_cents"]), (3900, 2000, 1900))
        self.assertEqual(invites.balance(c, "b10"), 0)

    def test_accept_endpoint(self):
        c = app.con(); code = invites.get_or_create(c, "a11"); user("b11")
        self.assertEqual(app.handle_invite_accept({"code": code}, who("b11"))[1]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
