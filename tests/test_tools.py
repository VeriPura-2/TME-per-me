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
        ship = lambda p, c: {x["id"]: x for x in tools.for_case(p, c)}["shipping"]["today"]
        pasta, cheese = ship("pasta", "UK"), ship("cheese", "France")
        self.assertIn("sendcloud", pasta["links"][0]["url"])
        self.assertIn("shippypro", cheese["links"][0]["url"])
        self.assertNotIn("note", pasta)
        self.assertIn("samples", cheese["note"]["en"])

    def test_cards_are_copies(self):
        tools.for_case("cheese", "France")[0]["today"]["text"] = "x"
        self.assertNotEqual(tools.for_case("cheese", "France")[0]["today"]["text"], "x")

    def test_us_wine_certificate_preview_only_for_wine_to_the_us(self):
        ids = lambda p, c: {x["id"] for x in tools.for_case(p, c)}
        self.assertIn("ttb_agent", ids("wine", "USA"))
        self.assertNotIn("ttb_agent", ids("wine", "UK"))
        self.assertNotIn("ttb_agent", ids("pasta", "USA"))

    def test_certification_card_is_narrow_and_in_the_public_list(self):
        card = {x["id"]: x for x in tools.for_case("cheese", "France")}["cert_evidence"]
        for lg in ("en", "it"):
            text = card["today"]["text"][lg] + card["coming"]["text"][lg]
            self.assertNotIn(EM_DASH, text)
            for word in ("verified", "automatic", "traceability", "AI-powered"):
                self.assertNotIn(word, text)
        self.assertIn("claimed", card["today"]["text"]["en"])
        self.assertIn("cert_evidence", {x["id"] for x in tools.public_catalog()})
        self.assertIn("Certification evidence", tools.ai_guide())

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
        self.assertIn("additives banned in the European Union", cards["doc_checks"]["coming"]["text"]["en"])
        self.assertEqual(cards["doc_checks"]["name"]["en"], "VeriPura Document Checker")  # named on 8 Nov by Thomas; Core itself is still not named
        self.assertNotIn("Core", cards["doc_checks"]["name"]["en"] + cards["doc_checks"]["coming"]["text"]["en"])
        self.assertEqual(cards["doc_checks"]["coming"]["status"], "preview")
        self.assertNotIn("tracking", cards)  # folded into the Shipping card's coming-soon line
        self.assertIn("freight forwarder", cards["shipping"]["coming"]["text"]["en"])
        self.assertEqual(cards["shipping"]["coming"]["status"], "soon")
        self.assertFalse({"pallets", "containers", "label_check_inside", "doc_checks_more"} & set(cards))


class FundingCard(unittest.TestCase):
    def card(self):
        return {x["id"]: x for x in tools.for_case("wine", "USA")}["funding"]

    def test_every_call_has_a_status_and_closed_calls_stay_listed(self):
        links = self.card()["today"]["links"]
        self.assertTrue(all(l["status"] in ("open", "closed", "check", "no_window") for l in links))
        closed = [l for l in links if l["status"] == "closed"]
        self.assertGreaterEqual(len(closed), 4)
        self.assertTrue(all(l.get("note") for l in closed))
        self.assertFalse(any("modena" in l["url"] and l["status"] == "open" for l in links))

    def test_last_checked_date_and_notify_button(self):
        today = self.card()["today"]
        self.assertRegex(today["checked"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(today["notify"], "funding_calls")
        self.assertIn("funding_calls", tools.INTEREST_ONLY)
        self.assertNotIn("funding_calls", tools.TOOL_IDS)

    def test_notify_interest_is_recorded_once(self):
        who = user("fund-a")
        con = app.con()
        for _ in range(2):
            self.assertEqual(tools.record_interest(con, None, "fund-a", "funding_calls")[0], 200)
        n = con.execute("SELECT COUNT(*) AS n FROM tool_interest WHERE tool='funding_calls' AND user_sub='fund-a'").fetchone()["n"]
        self.assertEqual(n, 1)

    def test_wording_changes(self):
        cards = {x["id"]: x for x in tools.for_case("wine", "USA")}
        self.assertNotIn("updated weekly", cards["duties"]["today"]["text"]["en"])
        self.assertIn("where we have one", cards["checklist"]["today"]["text"]["en"])
        self.assertIn("draft", cards["eori"]["today"]["text"]["en"])
        self.assertNotIn("free tools", cards["label_design"]["today"]["text"]["en"])
        self.assertNotIn("United States", cards["label_design"]["today"]["text"]["en"])
        self.assertIn("Example, not a real shipment", cards["buyer_verification"]["coming"]["example"][0]["en"])


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
        self.assertIn('jToolsBoxes(j.tools, cid, t)', html)  # Phase 4a: step tools inside the steps, the rest grouped under More tools
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


class CoreAndGuide(unittest.TestCase):
    def test_miotem_tools_first_and_labelled(self):
        cards = tools.for_case("pasta", "UK")
        core = {c["id"] for c in tools.CORE} - {"consultants"}  # 22 Nov 2026: the page tools first, then compliance (VeriPura checks), TEM card near the end
        self.assertEqual({c["id"] for c in cards[:len(core)]}, core)
        by = {c["id"]: c["by"] for c in cards}
        self.assertEqual(by["checklist"]["kind"], "miotem")
        self.assertEqual(by["doc_checks"], {"kind": "partner", "name": "VeriPura"})
        self.assertEqual(by["label_check"]["name"], "VeriPura")
        self.assertIn("Sendcloud", by["shipping"]["name"])

    def test_core_tools_always_shown_and_not_switchable(self):
        c = app.con()
        cid = __import__("vialibera.db", fromlist=["x"]).create_case(c, 1)
        row = c.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
        client = {x["id"] for x in tools.for_viewer(c, row, "pasta", "UK", "client")["cards"]}
        for core in ("ai_manager", "checklist", "duties", "library", "eori", "consultants"):
            self.assertIn(core, client)
        self.assertEqual(tools.set_visibility(c, {"user": "nobody"}, cid, "checklist", False)[0], 404)

    def test_ai_guide_lists_every_tool_and_goto_keys(self):
        g = tools.ai_guide()
        for c in tools.CORE + tools.CARDS:
            self.assertIn(c["name"]["en"], g)
        for key in ("chat", "req", "duties", "docs", "eori", "tools"):
            self.assertIn(key, g)
        self.assertIn("GOTO:", g)
        self.assertNotIn(EM_DASH, g)
        from vialibera import agent
        self.assertIn("MioTEM TOOLS", agent.GUIDE)

    def test_catalog_for_a_signed_in_user(self):
        code, out = app.handle_tools("/tools/catalog", {}, user("tools-cat"))
        self.assertEqual(code, 200)
        self.assertEqual(out["viewer"], "exporter")
        self.assertIn("importers", {x["id"] for x in out["cards"]})
        self.assertNotIn("ttb_agent", {x["id"] for x in out["cards"]})

    def test_frontend_has_goto_and_tour(self):
        html = open(os.path.join(os.path.dirname(app.__file__), "static", "index.html"), encoding="utf-8").read()
        self.assertIn('last.startsWith("GOTO:")', html)
        self.assertIn('id="w-tools"', html)  # 11 Nov: a first sign-in sees every tool and what it does; later visits do not (welcomeTools)
        self.assertIn("if (me.latest_case) return;", html)
        self.assertIn("Spend your time winning buyers, not chasing documents.", html)
        self.assertIn("Più tempo per gli acquirenti, meno per i documenti.", html)


class ChatBold(unittest.TestCase):
    def test_bot_messages_render_bold_safely(self):
        html = open(os.path.join(os.path.dirname(app.__file__), "static", "index.html"), encoding="utf-8").read()
        self.assertIn('if (cls === "bot") richText(d, t); else d.textContent = t;', html)
        self.assertIn('b.textContent = part.slice(2, -2)', html)  # bold text is set as text, never as HTML
        self.assertIn("d.appendChild(document.createTextNode(part))", html)


class StepTags(unittest.TestCase):
    def test_step_tools_for_wine_to_usa(self):
        from vialibera import tools
        steps = {c["id"]: c.get("step") for c in tools.for_case("wine", "USA")}
        self.assertEqual((steps["label_check"], steps["label_design"], steps["ttb_agent"], steps["shipping"]), (2, 2, 3, 4))
        self.assertIsNone(steps["funding"])

    def test_ttb_agent_only_for_wine_usa(self):
        from vialibera import tools
        self.assertNotIn("ttb_agent", {c["id"] for c in tools.for_case("pasta", "UK")})


class Mode2Card(unittest.TestCase):
    def test_help_with_a_project_is_merged_into_the_tem_card(self):  # 20 Nov 2026: same thing as finding a TEM
        cards = {c["id"]: c for c in tools.for_case("wine", "USA")}
        self.assertNotIn("mode2", cards)
        self.assertIn("single project", cards["consultants"]["coming"]["text"]["en"])
        self.assertIn("solo progetto", cards["consultants"]["coming"]["text"]["it"])
        self.assertEqual(tools.record_interest(app.con(), None, "m2-tem", "mode2")[0], 200)  # TEM workspace button still records

class PublicCatalog(unittest.TestCase):
    def test_public_catalog_has_every_tool_and_no_partner_names(self):
        cat = tools.public_catalog()
        self.assertEqual({c["id"] for c in cat}, tools.TOOL_IDS - {"refcheck"})
        blob = str(cat)
        for bad in ("Sendcloud", "ShippyPro", "GoVisually", "Food Label Maker", "OUTREACH", "VeriPura Core"):
            self.assertNotIn(bad, blob)
        self.assertEqual([c["status"] for c in cat], sorted([c["status"] for c in cat], key=lambda s: {"live": 0, "preview": 1, "soon": 2}[s]))

    def test_public_endpoint_is_registered(self):
        src = open(os.path.join(os.path.dirname(app.__file__), "app.py"), encoding="utf-8").read()
        self.assertIn('"/tools/public.json"', src)


class VeroItalianoWalkthrough(unittest.TestCase):
    """20 Nov 2026: Vero Italiano shown as an In development card with a scripted example (no AI call, nothing stored)."""
    def test_card_is_a_preview_with_six_bilingual_screens(self):
        cards = {c["id"]: c for c in tools.for_case("cheese", "USA")}
        vi = cards["vero_italiano"]
        self.assertNotIn("today", vi)
        self.assertEqual(vi["coming"]["status"], "preview")
        walk = vi["coming"]["walk"]
        self.assertEqual(len(walk), 6)
        texts = [vi["name"], vi["coming"]["text"]] + [s["t"] for s in walk] + [x for s in walk for x in s["lines"]]
        for x in texts:
            for lg in ("en", "it"):
                self.assertTrue(x[lg])
                self.assertNotIn(EM_DASH, x[lg])
                for banned in ("SaaS", "traceability", "AI-powered"):
                    self.assertNotIn(banned.lower(), x[lg].lower())
        self.assertIn("vero_italiano", tools.TOOL_IDS)

    def test_frontend_renders_the_walkthrough(self):
        html = open(os.path.join(os.path.dirname(app.__file__), "static", "index.html"), encoding="utf-8").read()
        self.assertIn("if (n.walk) walkthrough(card, n.walk, t);", html)
        self.assertIn('wk_open: "See an example"', html)
        self.assertIn('wk_open: "Vedi un esempio"', html)


class GuidedTour(unittest.TestCase):
    """20 Nov 2026: exporter tour with 'Interested?' at tool stops and two consent questions at the end (no AI call)."""
    def test_stops_are_bilingual_and_point_at_real_tools(self):
        self.assertEqual(len(tools.TOUR), 14)
        texts = []
        for st in tools.TOUR:
            texts += [st["t"], st["text"]]
            if st.get("tool"):
                self.assertIn(st["tool"], tools.TOOL_IDS)
            if st.get("ask"):
                self.assertIn(st["ask"], tools.TOOL_IDS)
            for q in st.get("questions", []):
                self.assertIn(q["ask"], tools.CONSENT_NEEDED)
                texts += [q["q"], q["note"], q["consent"]]
        for x in texts:
            for lg in ("en", "it"):
                self.assertTrue(x[lg])
                self.assertNotIn(EM_DASH, x[lg])
                for banned in ("saas", "traceability", "ai-powered"):
                    self.assertNotIn(banned, x[lg].lower())
        self.assertEqual({q["ask"] for q in tools.TOUR[-1]["questions"]}, {"tem_intro", "bank_financing"})

    def test_tour_endpoint(self):
        code, out = app.handle_tools("/tools/tour", {}, user("tour-a"))
        self.assertEqual(code, 200)
        self.assertEqual(len(out["stops"]), 14)
        self.assertEqual(app.handle_tools("/tools/tour", {}, None)[0], 400)

    def test_closing_questions_need_consent(self):
        c = app.con()
        self.assertEqual(tools.record_interest(c, None, "tour-b", "bank_financing")[0], 400)
        self.assertEqual(tools.record_interest(c, None, "tour-b", "tem_intro", consent="yes")[0], 400)
        self.assertEqual(tools.record_interest(c, None, "tour-b", "tem_intro", consent=True, email="b@example.com")[0], 200)
        self.assertEqual(tools.record_interest(c, None, "tour-b", "funding")[0], 200)  # ordinary interest needs no consent
        out = tools.contact_requests(c)
        self.assertTrue(any(r["tool"] == "tem_intro" and r["email"] == "b@example.com" for r in out["requests"]))
        self.assertFalse(any(r["tool"] == "funding" for r in out["requests"]))
        ev = c.execute("SELECT data FROM events WHERE actor='tour-b' AND kind='tool_interest'").fetchall()
        self.assertTrue(any("consent" in e["data"] for e in ev))

    def test_contact_requests_staff_only(self):
        self.assertEqual(app.handle_admin("/admin/contact_requests", {}, user("tour-c"))[0], 403)

    def test_frontend_has_the_tour(self):
        html = open(os.path.join(os.path.dirname(app.__file__), "static", "index.html"), encoding="utf-8").read()
        self.assertIn('<div id="j-tour"></div>', html)
        self.assertIn("tourButton(cid);", html)
        self.assertIn('call("/tools/tour", kind === "tem" ? {kind: "tem"} : {})', html)
        self.assertIn('tour_take: "Take the tour"', html)
        self.assertIn('tour_take: "Faccia il tour"', html)
        self.assertIn('call("/admin/contact_requests", {})', html)


class TemTour(unittest.TestCase):
    """20 Nov 2026: TEM tour, workspace then the first client project, closing with five consent questions."""
    def test_stops_bilingual_and_valid(self):
        self.assertEqual(len(tools.TEM_TOUR), 19)
        texts = []
        for st in tools.TEM_TOUR:
            texts += [st["t"], st["text"]]
            if st.get("tool"):
                self.assertIn(st["tool"], tools.TOOL_IDS)
                self.assertEqual(st["area"], "proj")
            if st.get("ask"):
                self.assertIn(st["ask"], tools.TOOL_IDS)
            if st["id"] != "close":
                self.assertIn(st["area"], ("ws", "proj"))
                self.assertTrue(st.get("el") or st.get("tool"))
            for q in st.get("questions", []):
                self.assertIn(q["ask"], tools.CONSENT_NEEDED)
                texts += [q["q"], q["note"], q["consent"]]
        for x in texts:
            for lg in ("en", "it"):
                self.assertTrue(x[lg])
                self.assertNotIn(EM_DASH, x[lg])
                for banned in ("saas", "traceability", "ai-powered"):
                    self.assertNotIn(banned, x[lg].lower())
        self.assertEqual({q["ask"] for q in tools.TEM_TOUR[-1]["questions"]},
                         {"tem_single_projects", "tem_funding", "tem_bank_clients", "tem_sace", "tem_setup_call"})
        sace = [q for q in tools.TEM_TOUR[-1]["questions"] if q["ask"] == "tem_sace"][0]
        self.assertNotIn("partner", sace["q"]["en"].lower())  # no partnership agreed with SACE yet

    def test_endpoint_by_kind(self):
        self.assertEqual(len(app.handle_tools("/tools/tour", {"kind": "tem"}, user("tt-a"))[1]["stops"]), 19)
        self.assertEqual(len(app.handle_tools("/tools/tour", {}, user("tt-a"))[1]["stops"]), 14)

    def test_tem_questions_need_consent(self):
        c = app.con()
        for tool in ("tem_single_projects", "tem_funding", "tem_bank_clients", "tem_sace", "tem_setup_call"):
            self.assertEqual(tools.record_interest(c, None, "tt-b", tool)[0], 400)
            self.assertEqual(tools.record_interest(c, None, "tt-b", tool, consent=True, email="t@example.com")[0], 200)

    def test_outreach_card_is_coming_soon_and_off_for_clients(self):
        cards = {c["id"]: c for c in tools.for_case("cheese", "USA")}
        self.assertEqual(cards["outreach"]["coming"]["status"], "soon")
        self.assertNotIn("today", cards["outreach"])
        self.assertIn("outreach", tools.CLIENT_OFF)

    def test_frontend_anchors(self):
        html = open(os.path.join(os.path.dirname(app.__file__), "static", "index.html"), encoding="utf-8").read()
        for el in ("tw-firm", "tw-team", "tw-engage", "tw-client", "tw-newp", "tw-case", "tw-req", "tw-duties", "tw-tools", "tw-docs", "tw-tour"):
            self.assertIn('"' + el + '"', html)
        self.assertIn('startTour(temFirst, "tem")', html)
        self.assertIn('if (q0.get("tour") === "new") { localStorage.removeItem("vl_tour_done"); localStorage.removeItem("vl_tem_tour_done");', html)


class Order22Nov(unittest.TestCase):
    """22 Nov 2026 research: compliance tools first, lowest rated last, importers up for first-time exporters."""

    def ids(self, first_time=False):
        return [c["id"] for c in tools.for_case("wine", "USA", first_time)]

    def test_compliance_first_and_lowest_rated_last(self):
        ids = self.ids()
        self.assertEqual(ids[:5], ["ai_manager", "checklist", "duties", "library", "eori"])
        self.assertLess(ids.index("doc_checks"), ids.index("shipping"))
        self.assertLess(ids.index("label_check"), ids.index("importers"))
        self.assertEqual(ids[-2:], ["consultants", "outreach"])
        self.assertLess(ids.index("funding"), ids.index("importers"))  # importers rank low for exporters already shipping

    def test_first_time_exporters_see_importers_right_after_compliance(self):
        ids = self.ids(True)
        self.assertEqual(ids[ids.index("alerts") + 1], "importers")
        self.assertEqual(sorted(ids), sorted(self.ids()))

    def test_every_card_has_a_place(self):
        every = {c["id"] for c in tools.CORE + tools.CARDS}
        self.assertEqual(every, set(tools.ORDER))

    def test_no_booking_or_application_drafting_promised(self):
        cards = {c["id"]: c for c in tools.for_case("wine", "USA")}
        self.assertNotIn("booking", cards["shipping"]["coming"]["text"]["en"])
        self.assertNotIn("application", cards["funding"]["coming"]["text"]["en"])


class NewMarket22Nov(unittest.TestCase):
    """R1: researched importers move up for any project whose destination is a new market (no importer there yet)."""

    def order(self, importer):
        from test_start_form import user
        from vialibera import app
        who = user("nm-" + str(importer))
        body = {"category": "cheese", "country": "USA"}
        if importer:
            body["importer"] = importer
        code, out = app.handle_start(body, who)
        self.assertEqual(code, 200)
        ids = [c["id"] for c in app.handle_journey({"case_id": out["case_id"]}, who)[1]["tools"]["cards"]]
        return ids, out["case_id"]

    def test_new_market_puts_importers_right_after_compliance(self):
        ids, cid = self.order("no")
        self.assertEqual(ids[ids.index("alerts") + 1], "importers")
        from vialibera import app, db
        self.assertEqual(db.case_read(app.con(), cid)["market"]["importer_status"], "looking")

    def test_an_importer_already_there_keeps_importers_low(self):
        ids, cid = self.order("yes")
        self.assertLess(ids.index("funding"), ids.index("importers"))
        from vialibera import app, db
        self.assertEqual(db.case_read(app.con(), cid)["market"]["importer_status"], "have one")

    def test_unanswered_keeps_the_old_order(self):
        ids, _ = self.order(None)
        self.assertLess(ids.index("funding"), ids.index("importers"))
