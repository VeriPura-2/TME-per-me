import os
import re
import unittest
from unittest import mock

os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, tools, vat_check


def user(name):
    accounts.record_consent(app.con(), name, app.TERMS_VERSION, "en", True)
    return {"user": name, "roles": []}


EM_DASH = "—"


class ToolCards(unittest.TestCase):
    def test_parcel_order_depends_on_chilled_products(self):
        pasta = tools.for_case("pasta", "UK")[0]["today"]
        cheese = tools.for_case("cheese", "France")[0]["today"]
        self.assertIn("sendcloud", pasta["links"][0]["url"])
        self.assertIn("shippypro", cheese["links"][0]["url"])
        self.assertNotIn("note", pasta)
        self.assertIn("samples", cheese["note"]["en"])

    def test_cards_are_copies(self):
        tools.for_case("cheese", "France")[0]["today"]["note"] = "x"
        self.assertNotIn("note", tools.for_case("pasta", "UK")[0]["today"])

    def test_us_wine_certificate_preview_only_for_wine_to_the_us(self):
        ids = lambda p, c: {x["id"] for x in tools.for_case(p, c)}
        self.assertIn("ttb_agent", ids("wine", "USA"))
        self.assertNotIn("ttb_agent", ids("wine", "UK"))
        self.assertNotIn("ttb_agent", ids("pasta", "USA"))

    def test_every_card_states_today_or_coming_in_both_languages(self):
        for c in tools.for_case("wine", "USA"):
            self.assertTrue(c["name"]["en"] and c["name"]["it"], c["id"])
            self.assertTrue(c.get("today") or c.get("coming"), c["id"])
            for part in ("today", "coming"):
                if c.get(part):
                    self.assertTrue(c[part]["text"]["en"] and c[part]["text"]["it"], c["id"])
                    for l in c[part].get("links", []):
                        self.assertTrue(l["url"].startswith("https://"))
            if c.get("coming"):
                self.assertIn(c["coming"]["status"], ("preview", "soon"))
            blob = repr(c)
            self.assertNotIn(EM_DASH, blob, c["id"])
            self.assertNotIn("AI-powered", blob)

    def test_one_card_per_tool_with_current_and_expected_state(self):
        cards = {x["id"]: x for x in tools.for_case("cheese", "France")}
        self.assertEqual(cards["label_check"]["today"]["links"][0]["url"], "https://label.veripura.com/")
        self.assertEqual(cards["label_check"]["coming"]["status"], "preview")
        self.assertIn("specification sheet", cards["doc_checks"]["today"]["text"]["en"])
        self.assertEqual(cards["shipping"]["coming"]["status"], "soon")
        self.assertFalse({"pallets", "containers", "label_check_inside", "doc_checks_more"} & set(cards))


class Interest(unittest.TestCase):
    def setUp(self):
        v = mock.patch.object(vat_check, "vies", return_value={"state": "unavailable", "name": None, "address": None, "checked_at": "2026-11-06T12:00:00+00:00"})
        v.start(); self.addCleanup(v.stop)

    def test_interest_is_recorded_once_and_listed(self):
        who = user("tools-a")
        code, out = app.handle_start({"category": "wine", "country": "USA"}, who)
        cid = out["case_id"]
        code, j = app.handle_journey({"case_id": cid}, who)
        self.assertEqual(code, 200)
        self.assertIn("importers", {x["id"] for x in j["tools"]["cards"]})
        for _ in range(2):
            self.assertEqual(app.handle_tools("/tools/interest", {"case_id": cid, "tool": "importers"}, who)[0], 200)
        n = app.con().execute("SELECT COUNT(*) AS n FROM tool_interest WHERE case_id=? AND tool='importers'", (cid,)).fetchone()["n"]
        self.assertEqual(n, 1)
        listing = tools.interest_listing(app.con())
        self.assertGreaterEqual({x["tool"]: x["n"] for x in listing["by_tool"]}["importers"], 1)

    def test_unknown_tool_and_foreign_case_are_refused(self):
        a, b = user("tools-b"), user("tools-c")
        _, out = app.handle_start({"category": "pasta", "country": "France"}, a)
        self.assertEqual(app.handle_tools("/tools/interest", {"case_id": out["case_id"], "tool": "nope"}, a)[0], 400)
        self.assertEqual(app.handle_tools("/tools/interest", {"case_id": out["case_id"], "tool": "alerts"}, b)[0], 404)
        self.assertEqual(app.handle_tools("/tools/interest", {"tool": "alerts"}, None)[0], 400)


class References(unittest.TestCase):
    def test_mrn_format(self):
        ok = tools.check_reference("mrn", "26it 000000000012 34")  # spaces removed, upper-cased: 18 characters
        self.assertEqual(len(ok["value"]), 18)
        self.assertTrue(ok["format_ok"])
        self.assertTrue(ok["lookup"].startswith("https://taxation-customs.ec.europa.eu/"))
        self.assertFalse(tools.check_reference("mrn", "IT26000000000012345")["format_ok"])
        self.assertFalse(tools.check_reference("mrn", "26IT123")["format_ok"])

    def test_arc_format(self):
        self.assertTrue(tools.check_reference("arc", "15GB0123456789ABCDEF0")["format_ok"])  # example from Reg. 2018/574
        self.assertFalse(tools.check_reference("arc", "15GB0123456789ABCDEF")["format_ok"])
        self.assertIsNone(tools.check_reference("arc", "15GB0123456789ABCDEF0")["lookup"])

    def test_endpoint(self):
        who = user("tools-d")
        code, out = app.handle_tools("/tools/refcheck", {"kind": "mrn", "value": "26IT00000000001234"}, who)
        self.assertEqual(code, 200)
        self.assertTrue(out["format_ok"])
        self.assertEqual(app.handle_tools("/tools/refcheck", {"kind": "x", "value": "1"}, who)[0], 400)


class Frontend(unittest.TestCase):
    def test_tool_cards_are_rendered_in_services(self):
        html = open(os.path.join(os.path.dirname(app.__file__), "static", "index.html"), encoding="utf-8").read()
        self.assertIn('id="j-tools"', html)
        self.assertIn('toolsBox($("j-tools"), j.tools, cid)', html)
        self.assertIn("/tools/interest", html)
        self.assertRegex(html, re.compile(r"In development"))


class Visibility(unittest.TestCase):
    """Independent exporter sees all; TEM sees all with switches; the TEM's client sees the switched-on set."""
    def setUp(self):
        from vialibera import db as vdb, tems
        from test_tems import ADMIN, LEAD, CLIENT_A, OUTSIDER, VAT_A, accept_body
        self.tems, self.LEAD, self.CLIENT, self.OUT = tems, LEAD, CLIENT_A, OUTSIDER
        self.con = vdb.connect()
        _, f = tems.create_firm(self.con, ADMIN, "Export Partners Srl")
        tems.join(self.con, LEAD, f["lead_token"])
        _, la = tems.engage_link(self.con, LEAD)
        _, oa = tems.engage_accept(self.con, CLIENT_A, la["token"], accept_body(VAT_A, "Alfa Srl"), "v1")
        self.co = oa["company"]
        _, p = tems.new_project(self.con, LEAD, self.co, "wine", "USA")
        self.cid = p["case_id"]
        self.row = self.con.execute("SELECT * FROM cases WHERE id=?", (self.cid,)).fetchone()

    def ids(self, viewer):
        return {c["id"] for c in tools.for_viewer(self.con, self.row, "wine", "USA", viewer)["cards"]}

    def test_defaults(self):
        everything = self.ids("exporter")
        self.assertEqual(self.ids("tem"), everything)
        client = self.ids("client")
        for hidden in ("shipping", "label_check", "importers"):
            self.assertIn(hidden, everything)
            self.assertNotIn(hidden, client)
        for shown in ("label_design", "ttb_agent", "buyer_verification", "alerts", "doc_checks"):
            self.assertIn(shown, client)
        tem = tools.for_viewer(self.con, self.row, "wine", "USA", "tem")
        self.assertEqual(tem["client_count"]["total"], len(tem["cards"]) + 1)
        self.assertFalse({c["id"]: c for c in tem["cards"]}["importers"]["client_visible"])

    def test_tem_switches_a_card_and_it_is_logged(self):
        self.assertEqual(tools.set_visibility(self.con, self.LEAD, self.cid, "importers", True)[0], 200)
        self.assertIn("importers", self.ids("client"))
        self.assertEqual(tools.set_visibility(self.con, self.LEAD, self.cid, "alerts", False)[0], 200)
        self.assertNotIn("alerts", self.ids("client"))
        ev = self.con.execute("SELECT data FROM events WHERE case_id=? AND kind='tem_access'", (self.cid,)).fetchall()
        self.assertTrue(any("show_tool:importers" in e["data"] for e in ev))

    def test_only_the_tem_can_switch(self):
        self.assertEqual(tools.set_visibility(self.con, self.CLIENT, self.cid, "importers", True)[0], 404)
        self.assertEqual(tools.set_visibility(self.con, self.OUT, self.cid, "importers", True)[0], 404)
        self.assertEqual(tools.set_visibility(self.con, self.LEAD, self.cid, "nope", True)[0], 400)

    def test_tem_project_carries_switches_and_user_type_is_recorded(self):
        code, p = self.tems.project(self.con, self.LEAD, self.cid)
        self.assertEqual(code, 200)
        self.assertIn("client_visible", p["tools"]["cards"][0])
        self.assertEqual(tools.user_type(self.con, self.co, "lead"), "tem")
        self.assertEqual(tools.user_type(self.con, self.co, "ca"), "client")
        self.assertEqual(tools.user_type(self.con, None, "someone"), "exporter")
