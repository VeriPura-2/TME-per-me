import os
import tempfile
import unittest

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, tems
from test_journey import who
from test_tems import ADMIN, LEAD, MEMBER, CLIENT_A, OUTSIDER, VAT_A, accept_body


class AskMyTemTest(unittest.TestCase):
    def setUp(self):
        self.c = app.con()
        for t in ("tem_requests", "tool_visibility", "tem_clients", "tem_members", "tem_firms", "tem_assignments", "engagement_links"):
            self.c.execute(f"DELETE FROM {t}")
        for r in self.c.execute("SELECT id FROM companies WHERE vat=?", (VAT_A,)).fetchall():  # other test files may have used this VAT
            for t in ("memberships", "tem_clients"):
                self.c.execute(f"DELETE FROM {t} WHERE company_id=?", (r["id"],))
            self.c.execute("DELETE FROM companies WHERE id=?", (r["id"],))
        for u in ("ca", "lead", "x", "rev"):
            self.c.execute("DELETE FROM memberships WHERE user_sub=?", (u,))
        self.c.commit()
        _, f = tems.create_firm(self.c, ADMIN, "Export Partners Srl")
        tems.join(self.c, LEAD, f["lead_token"])
        _, la = tems.engage_link(self.c, LEAD)
        _, oa = tems.engage_accept(self.c, CLIENT_A, la["token"], accept_body(VAT_A, "Alfa Srl"), app.TERMS_VERSION)
        self.co = oa["company"]
        accounts.record_consent(self.c, "ca", app.TERMS_VERSION, "en", True)
        accounts.record_consent(self.c, "lead", app.TERMS_VERSION, "en", True)
        accounts.record_consent(self.c, "x", app.TERMS_VERSION, "en", True)
        _, p = tems.new_project(self.c, LEAD, self.co, "wine", "USA", "Barolo")
        self.case = p["case_id"]

    def ask(self, tool=None, note=None, user=CLIENT_A):
        return app.handle_tem("/tem/ask", {"case_id": self.case, "tool": tool, "note": note}, user)

    def test_client_sees_the_ask_flag_only_when_a_tem_works_for_them(self):
        out = app.handle_journey({"case_id": self.case}, CLIENT_A)[1]
        self.assertTrue(out["tools"]["tem"])
        self.assertEqual(out["tools"]["open_requests"], [])

    def test_client_asks_about_a_visible_tool_and_tem_sees_it(self):
        code, out = self.ask("tariff_lookup" if "tariff_lookup" in __import__("vialibera.tools", fromlist=["x"]).TOOL_IDS else "duties", "Can you check this?")
        self.assertEqual(code, 200, out)
        reqs = tems.overview(self.c, LEAD)[1]["clients"][0]["requests"]
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]["note"], "Can you check this?")
        self.assertIn("Barolo", reqs[0]["project"])

    def test_general_line_has_no_tool(self):
        self.assertEqual(self.ask(None, "Other tools please")[0], 200)
        self.assertIsNone(tems.overview(self.c, LEAD)[1]["clients"][0]["requests"][0]["tool"])

    def test_second_open_request_for_the_same_tool_is_refused(self):
        self.assertEqual(self.ask(None)[0], 200)
        self.assertEqual(self.ask(None)[0], 409)

    def test_hidden_tool_cannot_be_asked_about(self):
        from vialibera import tools
        code, out = self.ask("label_check")  # hidden from the client by default
        self.assertEqual(code, 400)
        tools.set_visibility(self.c, LEAD, self.case, "label_check", True)
        self.assertEqual(self.ask("label_check")[0], 200)

    def test_unknown_tool_refused(self):
        self.assertEqual(self.ask("nonsense")[0], 400)

    def test_note_is_capped(self):
        self.ask(None, "x" * 900)
        self.assertEqual(len(tems.overview(self.c, LEAD)[1]["clients"][0]["requests"][0]["note"]), tems.NOTE_MAX)

    def test_reviewer_cannot_ask(self):
        self.c.execute("INSERT INTO memberships(company_id, user_sub, role, status, created_at) VALUES (?,?,?,?,?)",
                       (self.co, "rev", "reviewer", "active", "2026-11-08"))
        accounts.record_consent(self.c, "rev", app.TERMS_VERSION, "en", True)
        self.c.commit()
        self.assertEqual(self.ask(None, user=who("rev"))[0], 403)

    def test_outsider_and_tem_staff_cannot_ask(self):
        self.assertEqual(self.ask(None, user=OUTSIDER)[0], 404)
        self.assertIn(self.ask(None, user=LEAD)[0], (403, 404))

    def test_company_without_tem_is_refused(self):
        from test_journey import make_case
        accounts.record_consent(self.c, "solo", app.TERMS_VERSION, "en", True)
        cid = make_case("solo")
        code, _ = app.handle_tem("/tem/ask", {"case_id": cid, "tool": None}, who("solo"))
        self.assertEqual(code, 404)

    def test_tem_marks_done_and_it_disappears(self):
        self.ask(None, "hi")
        rid = tems.overview(self.c, LEAD)[1]["clients"][0]["requests"][0]["id"]
        self.assertEqual(app.handle_tem("/tem/request_done", {"id": rid}, LEAD)[0], 200)
        self.assertEqual(tems.overview(self.c, LEAD)[1]["clients"][0]["requests"], [])
        self.assertEqual(self.ask(None)[0], 200)  # a new request is allowed once the old one is done

    def test_other_firm_or_outsider_cannot_mark_done(self):
        self.ask(None)
        rid = tems.overview(self.c, LEAD)[1]["clients"][0]["requests"][0]["id"]
        self.assertEqual(app.handle_tem("/tem/request_done", {"id": rid}, OUTSIDER)[0], 404)
        self.assertEqual(app.handle_tem("/tem/request_done", {"id": rid}, CLIENT_A)[0], 404)

    def test_overview_gives_documents_progress(self):
        p = tems.overview(self.c, LEAD)[1]["clients"][0]["projects"][0]
        self.assertEqual(p["docs"]["total"], p["docs"]["have"] + p["missing"])
        self.assertGreater(p["docs"]["total"], 0)

    def test_firm_project_cap_defaults_to_the_tem_plan_and_is_enforced(self):
        f = tems.overview(self.c, LEAD)[1]["firm"]
        self.assertEqual(f["projects"], {"used": 1, "cap": 50})
        self.assertEqual(tems.set_project_limit(self.c, LEAD, f["id"], 2)[0], 403)  # staff only
        self.assertEqual(tems.set_project_limit(self.c, ADMIN, f["id"], 2)[0], 200)
        self.assertEqual(tems.new_project(self.c, LEAD, self.co, "wine", "UK", "Second")[0], 200)
        code, out = tems.new_project(self.c, LEAD, self.co, "wine", "UK", "Third")
        self.assertEqual((code, out["error"], out["limit"]), (409, "tem_project_limit", 2))
        self.assertEqual(tems.set_project_limit(self.c, ADMIN, f["id"], 3)[0], 200)
        self.assertEqual(tems.new_project(self.c, LEAD, self.co, "wine", "UK", "Third")[0], 200)

    def test_bad_limit_is_refused_and_empty_resets_to_default(self):
        f = tems.overview(self.c, LEAD)[1]["firm"]
        self.assertEqual(tems.set_project_limit(self.c, ADMIN, f["id"], "abc")[0], 400)
        self.assertEqual(tems.set_project_limit(self.c, ADMIN, f["id"], 7)[1]["limit"], 7)
        self.assertEqual(tems.set_project_limit(self.c, ADMIN, f["id"], "")[1]["limit"], 50)


if __name__ == "__main__":
    unittest.main()
