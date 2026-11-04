import os
import unittest
from unittest import mock

os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, admin, app, core_checks, db, permissions, team, tems, vat_check

SUPER = {"user": "staff-own", "roles": [permissions.STAFF_CLAIM]}
VIES = {"state": "valid", "name": "PASTIFICIO", "address": "VIA ROMA", "checked_at": "2026-11-04T12:00:00+00:00"}


def piva(n):
    """A valid Italian VAT number (Luhn-style check digit) from a 10-digit base."""
    base = f"{n:010d}"
    tot = 0
    for i, ch in enumerate(base):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            d = d - 9 if d > 9 else d
        tot += d
    return base + str((10 - tot % 10) % 10)


def user(name):
    accounts.record_consent(app.con(), name, app.TERMS_VERSION, "en", True)
    return {"user": name, "roles": []}


class Ownership(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(vat_check, "vies", return_value=VIES); p.start(); self.addCleanup(p.stop)

    def _start(self, who, vat):
        code, out = app.handle_start({"category": "pasta", "country": "UK", "vat": vat}, who)
        return app.con().execute("SELECT company_id FROM cases WHERE id=?", (out["case_id"],)).fetchone()["company_id"]

    def test_first_claimant_is_provisional_even_when_vies_is_valid(self):
        cid = self._start(user("own-a"), piva(180000001))
        self.assertFalse(permissions.owner_confirmed(app.con(), cid))
        self.assertEqual(team.invite(app.con(), {"user": "own-a", "roles": []}, "member")[1]["error"], "owner_not_confirmed")

    def test_staff_confirm_unlocks_invites(self):
        cid = self._start(user("own-b"), piva(190000001))
        self.assertEqual(admin.confirm_owner(app.con(), {"user": "x", "roles": []}, cid)[0], 403)
        self.assertEqual(admin.confirm_owner(app.con(), SUPER, cid)[0], 200)
        self.assertEqual(team.invite(app.con(), {"user": "own-b", "roles": []}, "member")[0], 200)

    def test_staff_can_hand_ownership_to_the_real_owner(self):
        c = app.con()
        cid = self._start(user("squat"), piva(110000001))
        real = user("real-owner")
        c.execute("INSERT INTO memberships(company_id, user_sub, role, status, created_at) VALUES (?,?,?,?,?)",
                  (cid, "real-owner", "member", "pending", db.now()))
        self.assertEqual(admin.set_owner(c, SUPER, cid, "nobody")[0], 400)
        self.assertEqual(admin.set_owner(c, SUPER, cid, "real-owner")[0], 200)
        self.assertEqual(permissions.role_in(c, cid, "real-owner"), "owner")
        self.assertEqual(permissions.role_in(c, cid, "squat"), "member")
        self.assertTrue(permissions.owner_confirmed(c, cid))

    def test_staff_created_company_is_confirmed(self):
        code, out = admin.add_company(app.con(), SUPER, piva(160000001), "Staff Co")
        self.assertEqual(code, 200)
        cid = app.con().execute("SELECT id FROM companies WHERE legal_name='Staff Co'").fetchone()["id"]
        self.assertTrue(permissions.owner_confirmed(app.con(), cid))

    def test_work_queue_lists_owners_to_confirm(self):
        cid = self._start(user("own-q"), piva(120000001))
        code, out = admin.queue(app.con(), SUPER)
        self.assertIn(cid, [o["id"] for o in out["owners_to_confirm"]])

    def test_auto_validation_held_for_provisional_owner(self):
        c = app.con()
        cid = self._start(user("own-c"), piva(130000001))
        case = c.execute("SELECT id FROM cases WHERE company_id=?", (cid,)).fetchone()["id"]
        c.execute("UPDATE cases SET status='paid' WHERE id=?", (case,))
        with mock.patch.object(core_checks, "auto_enabled", return_value=True), \
             mock.patch.object(core_checks, "send", side_effect=AssertionError("must not send")):
            self.assertIsNone(core_checks.on_upload(c, case, "doc-x"))
        held = c.execute("SELECT 1 FROM events WHERE case_id=? AND kind='core_auto_held'", (case,)).fetchone()
        self.assertIsNotNone(held)

    def test_team_overview_shows_the_flag(self):
        self._start(user("own-d"), piva(140000001))
        code, out = team.overview(app.con(), {"user": "own-d", "roles": []})
        self.assertFalse(out["company"]["owner_confirmed"])


class EngagementAuthority(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(vat_check, "vies", return_value=VIES); p.start(); self.addCleanup(p.stop)

    def test_authority_is_required_and_records_the_company_acceptance(self):
        c = app.con()
        code, out = tems.create_firm(c, SUPER, "Firm Auth")
        firm = out.get("firm") or out.get("id")
        lead = {"user": "lead-auth", "roles": []}
        tems.join(c, lead, out["lead_token"])
        token = tems.engage_link(c, lead)[1]["token"]
        client = user("client-auth")
        body = {"vat": piva(150000001), "legal_name": "Client Co", "signatory_name": "A", "signatory_role": "B",
                "accept_scope": True, "accept_core": True, "accept_terms": True}
        self.assertEqual(tems.engage_accept(c, client, token, body, app.TERMS_VERSION)[0], 400)
        body["authorised"] = True
        code, res = tems.engage_accept(c, client, token, body, app.TERMS_VERSION)
        self.assertEqual(code, 200)
        cc = c.execute("SELECT 1 FROM company_consents WHERE company_id=? AND terms_version=?", (res["company"], app.TERMS_VERSION)).fetchone()
        self.assertIsNotNone(cc)


if __name__ == "__main__":
    unittest.main()
