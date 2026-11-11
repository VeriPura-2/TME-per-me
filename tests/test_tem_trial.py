import os
import unittest

os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, db, landing_chat, tem_interest, tems


def user(name):
    accounts.record_consent(app.con(), name, app.TERMS_VERSION, "en", True)
    return {"user": name, "roles": []}


class TrialFirm(unittest.TestCase):
    def setUp(self):
        c = app.con()
        for t in ("tem_interest", "tem_members", "tem_clients", "tem_firms", "memberships", "companies", "engagement_links"):
            c.execute(f"DELETE FROM {t}")

    def test_creates_firm_with_trial_limits_and_a_lead_record(self):
        who = user("tem-1")
        code, out = tems.create_trial_firm(app.con(), who, "Studio Verdi", "v@verdi.it", '{"clients": ["8"]}')
        self.assertEqual(code, 200)
        f = tems.firm_of(app.con(), "tem-1")
        self.assertEqual((f["role"], f["name"]), ("lead", "Studio Verdi"))
        self.assertEqual(tems.project_cap(app.con(), out["firm"]), 5)
        self.assertEqual(tems.client_cap(app.con(), out["firm"]), 2)
        self.assertEqual(app.con().execute("SELECT seats, trial FROM tem_firms WHERE id=?", (out["firm"],)).fetchone()["seats"], 1)
        lead = tem_interest.listing(app.con())["requests"][0]
        self.assertEqual((lead["source"], lead["email"], lead["firm_name"]), ("trial", "v@verdi.it", "Studio Verdi"))
        self.assertEqual(tems.invite_member(app.con(), who), (400, {"error": "no_free_seat"}))

    def test_one_firm_per_person_and_a_name_is_needed(self):
        who = user("tem-2")
        self.assertEqual(tems.create_trial_firm(app.con(), who, "")[0], 400)
        self.assertEqual(tems.create_trial_firm(app.con(), who, "A")[0], 200)
        self.assertEqual(tems.create_trial_firm(app.con(), who, "B"), (409, {"error": "already_in_firm"}))

    def test_staff_and_company_members_cannot_open_a_trial(self):
        staff = {"user": "s1", "roles": ["veripura_support"]}
        self.assertEqual(tems.create_trial_firm(app.con(), staff, "X")[0], 403)
        owner = user("exp-1")
        c = app.con()
        c.execute("INSERT INTO companies(id, vat, legal_name, plan, created_at) VALUES (?,?,?,?,?)", ("co1", "01765920051", "Pasta Srl", None, db.now()))
        c.execute("INSERT INTO memberships(company_id, user_sub, role, status, label, created_at) VALUES (?,?,?,?,?,?)",
                  ("co1", "exp-1", "owner", "active", None, db.now()))
        self.assertEqual(tems.create_trial_firm(c, owner, "Y"), (409, {"error": "has_company"}))

    def test_trial_firm_client_limit_blocks_the_third_engagement_link(self):
        who = user("tem-3")
        _, out = tems.create_trial_firm(app.con(), who, "Studio")
        c = app.con()
        for i in range(2):
            c.execute("INSERT INTO companies(id, vat, legal_name, plan, created_at) VALUES (?,?,?,?,?)", (f"c{i}", f"0000000000{i}", "C", None, db.now()))
            c.execute("INSERT INTO tem_clients(firm_id, company_id, status, engaged_at, engaged_by, signatory, scope) VALUES (?,?,?,?,?,?,?)", (out["firm"], f"c{i}", "active", db.now(), "x", "{}", "[]"))
        self.assertEqual(tems.engage_link(c, who), (409, {"error": "tem_client_limit", "limit": 2}))

    def test_firms_made_by_staff_have_no_client_limit(self):
        code, out = tems.create_firm(app.con(), {"user": "root", "roles": ["veripura_superadmin"]}, "Big Studio")
        self.assertEqual(code, 200)
        self.assertIsNone(tems.client_cap(app.con(), out["firm"]))

    def test_trial_note_carries_the_landing_answers(self):
        v = "c" * 32
        c = app.con()
        c.execute("DELETE FROM anon_chats")
        c.execute("INSERT INTO anon_chats(visitor_id, ip_hash, role, history, answers, messages, created_at, updated_at, user_sub) VALUES (?,?,?,?,?,?,?,?,?)",
                  (v, "h", "tem", "[]", '{"firm": ["Studio Verdi"], "contact": ["v@verdi.it"], "clients": ["8"]}', 3, db.now(), db.now(), "tem-4"))
        got = landing_chat.claim(c, "tem-4", v)
        self.assertEqual((got["role"], got["firm"], got["contact"]), ("tem", "Studio Verdi", "v@verdi.it"))


if __name__ == "__main__":
    unittest.main()
