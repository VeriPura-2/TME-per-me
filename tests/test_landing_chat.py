import json
import os
import unittest
from types import SimpleNamespace as NS

os.environ["DB_PATH"] = ":memory:"
from vialibera import app, landing_chat

EM_DASH = "—"
V1, V2 = "a" * 32, "b" * 32


def tool(name, inp, i="t1"):
    return NS(type="tool_use", id=i, name=name, input=inp,
              model_dump=lambda: {"type": "tool_use", "id": i, "name": name, "input": inp})


def text(t):
    return NS(type="text", text=t, model_dump=lambda: {"type": "text", "text": t})


class Script:
    def __init__(self, *responses):
        self.messages, self.responses, self.calls = self, list(responses), []

    def create(self, **kw):
        self.calls.append(kw)
        return NS(content=self.responses.pop(0), usage=None)


def say(c, msg, v=V1, ip="1.1.1.1"):
    return landing_chat.message(app.con(), {"visitor": v, "message": msg, "lang": "en"}, ip, c)


class LandingChat(unittest.TestCase):
    def setUp(self):
        app.con().execute("DELETE FROM anon_chats")

    def test_role_is_saved_with_the_answer(self):
        c = Script([tool("set_role", {"role": "tem"}), tool("save_answer", {"topic": "clients", "text": "12 exporters"}, "t2"),
                    text("How many countries do you handle?")])
        code, out = say(c, "I am a TEM")
        self.assertEqual(code, 200)
        self.assertEqual(out["role"], "tem")
        self.assertEqual(out["left"], landing_chat.MESSAGE_CAP - 1)
        row = app.con().execute("SELECT role, answers FROM anon_chats WHERE visitor_id=?", (V1,)).fetchone()
        self.assertEqual(row["role"], "tem")
        self.assertEqual(json.loads(row["answers"])["clients"], ["12 exporters"])

    def test_empty_reply_gets_one_more_call_and_never_the_opening_line(self):
        loud = [tool("yearly_estimate", {"hours_per_shipment": 1, "shipments_per_year": 3}, f"t{i}") for i in range(4)]
        c = Script(*[[x] for x in loud], [text("Thanks. What would that cost you in margin?")])
        code, out = say(c, "Under 100 euros")
        self.assertEqual(code, 200)
        self.assertEqual(out["reply"], "Thanks. What would that cost you in margin?")
        self.assertEqual(c.calls[-1]["tool_choice"], {"type": "none"})
        self.assertNotIn(landing_chat.OPENER["en"], out["reply"])

    def test_if_the_extra_call_also_says_nothing_the_reply_is_a_neutral_line(self):
        c = Script([], [])
        code, out = say(c, "hello")
        self.assertEqual(out["reply"], landing_chat.FALLBACK["en"])
        roles = [m["role"] for m in json.loads(app.con().execute("SELECT history FROM anon_chats WHERE visitor_id=?", (V1,)).fetchone()["history"])]
        self.assertTrue(all(a != b for a, b in zip(roles, roles[1:])), roles)

    def test_history_alternates_after_tool_results(self):
        say(Script([tool("set_role", {"role": "exporter"}), text("What do you export?")]), "I export")
        c = Script([text("And to which country?")])
        say(c, "Pasta")
        roles = [m["role"] for m in c.calls[0]["messages"]]
        self.assertTrue(all(a != b for a, b in zip(roles, roles[1:])), roles)

    def test_cap_per_visitor_then_signin(self):
        for i in range(landing_chat.MESSAGE_CAP):
            code, out = say(Script([text("ok")]), f"m{i}")
            self.assertEqual(code, 200)
        self.assertTrue(out["signin"])
        calls = Script()
        code, out = say(calls, "one more")
        self.assertEqual((code, out["error"], out["signin"]), (429, "cap", True))
        self.assertEqual(calls.calls, [])

    def test_last_message_asks_the_ai_to_close(self):
        for i in range(landing_chat.MESSAGE_CAP - 1):
            say(Script([text("ok")]), f"m{i}")
        c = Script([text("Please sign in.")])
        say(c, "last")
        self.assertIn("LAST message", c.calls[0]["system"][1]["text"])

    def test_per_ip_daily_cap(self):
        landing_chat.IP_DAILY_CAP, old = 3, landing_chat.IP_DAILY_CAP
        try:
            for i in range(3):
                self.assertEqual(say(Script([text("ok")]), "hi", v=f"{i:032x}")[0], 200)
            code, out = say(Script(), "hi", v="f" * 32)
            self.assertEqual((code, out["error"], out["signin"]), (429, "limit", True))  # a clear limit, not "unavailable"
            self.assertEqual(say(Script([text("ok")]), "hi", v="e" * 32, ip="2.2.2.2")[0], 200)
        finally:
            landing_chat.IP_DAILY_CAP = old

    def test_the_per_address_cap_default_and_setting(self):
        self.assertEqual(landing_chat.IP_DAILY_CAP, int(os.environ.get("LANDING_IP_DAILY_CAP", "150")))

    def test_daily_ceiling_falls_back(self):
        landing_chat.DAILY_CEILING, old = 1, landing_chat.DAILY_CEILING
        try:
            self.assertEqual(say(Script([text("ok")]), "hi")[0], 200)
            code, out = say(Script(), "hi", v=V2, ip="3.3.3.3")
            self.assertEqual((code, out["error"]), (503, "busy"))
        finally:
            landing_chat.DAILY_CEILING = old

    def test_ai_failure_is_not_counted(self):
        class Boom:
            messages = None
            def create(self, **kw):
                raise RuntimeError("down")
        b = Boom(); b.messages = b
        code, out = say(b, "hi")
        self.assertEqual((code, out["error"]), (503, "ai_unavailable"))
        self.assertIsNone(app.con().execute("SELECT 1 FROM anon_chats WHERE visitor_id=?", (V1,)).fetchone())

    def test_bad_input(self):
        self.assertEqual(say(Script(), "hi", v="nope")[0], 400)
        self.assertEqual(say(Script(), "   ")[0], 400)

    def test_category_and_country_values_are_saved_and_claimed(self):
        c = Script([tool("set_role", {"role": "exporter"}),
                    tool("save_answer", {"topic": "product", "text": "dry pasta", "value": "pasta"}, "t2"),
                    tool("save_answer", {"topic": "destination", "text": "Germany", "value": "Germany"}, "t3"),
                    tool("save_answer", {"topic": "problem", "text": "documents"}, "t4"), text("What happens if they are wrong?")])
        say(c, "I export dry pasta to Germany")
        out = landing_chat.claim(app.con(), "user-1", V1)
        self.assertEqual((out["claimed"], out["role"], out["category"], out["country"]), (True, "exporter", "pasta", "Germany"))
        self.assertEqual(out["product"], "dry pasta")
        self.assertIn("documents", landing_chat.note_for(app.con(), "user-1"))
        self.assertEqual(landing_chat.note_for(app.con(), "someone-else"), "")

    def test_invalid_values_are_ignored(self):
        say(Script([tool("save_answer", {"topic": "product", "text": "x", "value": "rocket fuel"}), text("ok")]), "hi")
        self.assertIsNone(landing_chat.claim(app.con(), "u", V1).get("category"))

    def test_a_conversation_is_claimed_by_one_person(self):
        say(Script([tool("set_role", {"role": "exporter"}), text("ok")]), "hi")
        self.assertTrue(landing_chat.claim(app.con(), "user-1", V1)["claimed"])
        self.assertFalse(landing_chat.claim(app.con(), "user-2", V1)["claimed"])
        self.assertTrue(landing_chat.claim(app.con(), "user-1", V1)["claimed"])
        self.assertFalse(landing_chat.claim(app.con(), "user-1", "zz")["claimed"])

    def test_tem_conversation_adds_no_project_note(self):
        say(Script([tool("set_role", {"role": "tem"}), tool("save_answer", {"topic": "clients", "text": "10"}, "t2"), text("ok")]), "TEM")
        landing_chat.claim(app.con(), "user-1", V1)
        self.assertEqual(landing_chat.note_for(app.con(), "user-1"), "")

    def test_lists_match_the_start_form(self):
        self.assertEqual(landing_chat.CATEGORIES, app.START_CATEGORIES)
        self.assertEqual(set(landing_chat.COUNTRIES), set(app.START_COUNTRIES))

    def test_yearly_estimate_uses_their_own_numbers_and_comes_back_to_the_ai(self):
        c = Script([tool("yearly_estimate", {"hours_per_shipment": 4, "shipments_per_year": 12, "cost_per_shipment_eur": 150})],
                   [text("By your own numbers, that is about 48 hours and 1800 euros a year. What does that do to your margin?")])
        code, out = say(c, "4 hours, 12 shipments, 150 euros")
        self.assertEqual(code, 200)
        self.assertIn("48 hours", out["reply"])
        result = c.calls[1]["messages"][-1]["content"][0]["content"]
        self.assertIn('"hours_per_year": 48.0', result)
        self.assertIn('"cost_per_year_eur": 1800', result)
        row = app.con().execute("SELECT answers FROM anon_chats WHERE visitor_id=?", (V1,)).fetchone()
        self.assertIn("48 h", json.loads(row["answers"])["estimate"][0])
        self.assertIn("their own numbers", json.loads(row["answers"])["estimate"][0])

    def test_ranges_come_back_as_a_range_with_working_weeks(self):
        st = {"answers": {}}
        out = landing_chat.run_tool(st, "yearly_estimate", {"hours_per_shipment": 5, "hours_per_shipment_max": 10,
                                                            "shipments_per_year": 6, "shipments_per_year_max": 12})
        self.assertEqual((out["hours_per_year"], out["hours_per_year_max"]), (30.0, 120.0))
        self.assertEqual((out["work_weeks"], out["work_weeks_max"]), (0.75, 3.0))
        self.assertIn("never as one invented midpoint", out["instruction"])
        self.assertIn("weeks of your (or your team's) time every year", out["instruction"])
        self.assertIn("30 h to 120 h", st["answers"]["estimate"][0])
        exact = landing_chat.run_tool({"answers": {}}, "yearly_estimate", {"hours_per_shipment": 4, "shipments_per_year": 12})
        self.assertNotIn("hours_per_year_max", exact)
        self.assertEqual(exact["work_weeks"], 1.25)

    def test_estimate_rejects_nonsense(self):
        st = {"role": None, "answers": {}}
        self.assertEqual(landing_chat.run_tool(st, "yearly_estimate", {"hours_per_shipment": "x", "shipments_per_year": 3})["error"], "numbers_needed")
        self.assertEqual(landing_chat.run_tool(st, "yearly_estimate", {"hours_per_shipment": 5000, "shipments_per_year": 3})["error"], "out_of_range")
        self.assertNotIn("estimate", st["answers"])

    def test_new_topics_are_saved_and_reach_the_project_note(self):
        c = Script([tool("set_role", {"role": "exporter"}), tool("save_answer", {"topic": "handling", "text": "a freight forwarder"}, "t2"),
                    tool("save_answer", {"topic": "time", "text": "5 to 10 hours per shipment"}, "t3"),
                    tool("save_answer", {"topic": "cost", "text": "300 to 500 euros per shipment"}, "t4"), text("ok")])
        say(c, "forwarder")
        landing_chat.claim(app.con(), "user-9", V1)
        note = landing_chat.note_for(app.con(), "user-9")
        self.assertIn("a freight forwarder", note)
        self.assertIn("5 to 10 hours", note)

    def test_script_asks_about_handling_time_and_money(self):
        p = landing_chat.SYSTEM
        for phrase in ("how they handle the export documents today", "hours the paperwork takes per shipment", "pay per shipment",
                       "as THEIR estimate", "Never present it as a MioTEM figure", "exact number"):
            self.assertIn(phrase, p)

    def test_script_answers_the_cost_of_signing_in(self):
        p = " ".join(landing_chat.SYSTEM.split())
        for phrase in ("Signing in is free", "free Explore plan", "trial workspace is free", "Do not quote the price of any paid"):
            self.assertIn(phrase, p)

    def test_the_ai_can_offer_a_sign_in_button_without_closing_the_chat(self):
        c = Script([tool("show_signin", {}), text("Sign in with the button below.")])
        code, out = say(c, "I want to sign in")
        self.assertEqual(code, 200)
        self.assertTrue(out["offer_signin"])
        self.assertFalse(out["signin"])
        self.assertEqual(len(c.calls), 1)
        code, out = say(Script([text("Sure.")]), "and one more question")
        self.assertEqual(code, 200)
        self.assertFalse(out["offer_signin"])

    def test_button_is_shown_when_the_reply_mentions_it_even_without_the_tool(self):
        code, out = say(Script([text("The sign-up button is below. Our conversation continues there.")]), "ok")
        self.assertTrue(out["offer_signin"])
        code, out = say(Script([text("Pulsante Accedi qui sotto.")]), "ok", v=V2)
        self.assertTrue(out["offer_signin"])
        code, out = say(Script([text("What do you export?")]), "hi", v="e" * 32)
        self.assertFalse(out["offer_signin"])

    def test_script_tells_the_ai_to_show_the_button(self):
        p = " ".join(landing_chat.SYSTEM.split())
        self.assertIn("call show_signin", p)
        self.assertIn("Never describe a link or a page you cannot show", p)
        self.assertIn("Only say the preview is below if you called show_preview", p)

    def _exporter(self, product="pasta", country="Germany"):
        return Script([tool("set_role", {"role": "exporter"}),
                       tool("save_answer", {"topic": "product", "text": product, "value": product}, "t2"),
                       tool("save_answer", {"topic": "destination", "text": country, "value": country}, "t3"), text("ok")])

    def _talk_exporter(self, product="pasta", country="Germany"):
        say(self._exporter(product, country), f"{product} to {country}")
        say(Script([tool("save_answer", {"topic": "handling", "text": "a freight forwarder"}), text("How many hours?")]), "forwarder")
        return self._offer()

    def _offer(self):
        return say(Script([tool("offer_preview", {})], [text("Would you like to see a preview of your route?")]), "ok that is my estimate")[1]

    def test_the_tem_introduction_offer_shows_the_contact_form_and_only_for_exporters(self):
        say(self._exporter("wine", "Germany"), "wine to Germany")
        code, out = say(Script([tool("offer_tem_intro", {})], [text("A short form below lets you leave an email.")]), "yes please")
        self.assertEqual((out["offer_notify"], out["notify_kind"]), (True, "tem_intro"))
        self.assertIn("tem_intro", app.con().execute("SELECT answers FROM anon_chats WHERE visitor_id=?", (V1,)).fetchone()["answers"])

    def test_the_introduction_form_has_its_own_consent_line(self):
        html = open(os.path.join(os.path.dirname(landing_chat.__file__), "static", "index.html"), encoding="utf-8").read()
        self.assertIn("I agree to be contacted about a TEM introduction", html)
        self.assertIn('kind === "tem_intro" ? L.nt_ic : L.nt_consent', html)

    def test_the_prompt_never_mentions_a_preview_before_it_is_offered(self):
        self.assertIn("no \"the preview above\"", landing_chat.SYSTEM)

    def test_the_prompt_asks_tem_users_about_document_time_and_offers_an_introduction(self):
        self.assertIn("gathering and sending documents to their TEM", landing_chat.SYSTEM)
        self.assertIn("offer_tem_intro", landing_chat.SYSTEM)

    def test_exporter_preview_is_the_real_route_data(self):
        self._talk_exporter()
        code, out = say(Script([tool("show_preview", {}), text("Your route is below.")]), "go on")
        self.assertTrue(out["offer_preview"])
        pv = landing_chat.preview(app.con(), V1)
        self.assertEqual((pv["kind"], pv["covered"], pv["category"], pv["country"]), ("route", True, "pasta", "Germany"))
        self.assertGreater(pv["documents"], 0)
        self.assertEqual(pv["documents"], sum(len(l["items"]) for l in pv["layers"]))
        self.assertTrue(pv["duties"]["eu"])

    def test_uncovered_route_gets_the_notify_form_not_a_preview(self):
        out = self._talk_exporter("spirits", "Germany")
        self.assertTrue(out["offer_notify"])
        code, out = say(Script([tool("show_preview", {}), text("below")]), "yes")  # never offered, so refused
        self.assertFalse(out["offer_preview"])
        self.assertEqual(landing_chat.preview(app.con(), V1)["kind"], None)

    def test_covered_route_is_offered_the_preview_not_the_form(self):
        out = self._talk_exporter()
        self.assertFalse(out["offer_notify"])

    def test_the_ai_reads_the_offer_result_before_it_speaks(self):
        # the first message (an offer written before the check) must not reach the visitor when the result says no list
        c = Script([tool("set_role", {"role": "exporter"}), tool("save_answer", {"topic": "product", "text": "apples", "value": "other"}, "t2"),
                    tool("save_answer", {"topic": "destination", "text": "Canada", "value": "Canada"}, "t3"), tool("offer_preview", {}, "t4"),
                    text("Would you like to see a preview?")],
                   [text("There is no checked list for this route yet.")])
        code, out = say(c, "apples to Canada")
        self.assertEqual(out["reply"], "There is no checked list for this route yet.")

    def test_offer_preview_tells_the_ai_when_there_is_no_list(self):
        c = Script([tool("set_role", {"role": "exporter"}), tool("save_answer", {"topic": "product", "text": "apples", "value": "other"}, "t2"),
                    tool("save_answer", {"topic": "destination", "text": "Canada", "value": "Canada"}, "t3"), tool("offer_preview", {}, "t4")],
                   [text("No list yet.")])
        code, out = say(c, "apples to Canada")
        self.assertTrue(out["offer_notify"])
        results = {r["tool_use_id"]: json.loads(r["content"]) for r in c.calls[-1]["messages"][-1]["content"]}
        result = results["t4"]
        self.assertFalse(result["covered"])
        self.assertIn("Do NOT offer a preview", result["instruction"])
        pv = landing_chat.preview(app.con(), V1)
        self.assertEqual(pv["kind"], None)  # no preview_ok: nothing is shown

    def test_preview_is_refused_on_the_first_message(self):
        c = Script([tool("set_role", {"role": "exporter"}), tool("save_answer", {"topic": "product", "text": "pasta", "value": "pasta"}, "t2"),
                    tool("save_answer", {"topic": "destination", "text": "Germany", "value": "Germany"}, "t3"),
                    tool("show_preview", {}, "t4"), text("What do you export?")])
        code, out = say(c, "I export")
        self.assertFalse(out["offer_preview"])
        self.assertEqual(landing_chat.preview(app.con(), V1)["kind"], None)

    def test_preview_needs_a_question_and_a_yes_in_a_later_message(self):
        say(self._exporter(), "pasta to Germany")
        say(Script([tool("save_answer", {"topic": "handling", "text": "myself"}), text("ok")]), "myself")
        code, out = say(Script([tool("show_preview", {}), text("below")]), "go")  # never asked
        self.assertFalse(out["offer_preview"])
        code, out = say(Script([tool("offer_preview", {}), tool("show_preview", {}, "t2")], [text("Want to see it?")]), "ok")  # asked and shown at once
        self.assertFalse(out["offer_preview"])
        code, out = say(Script([tool("show_preview", {}), text("Your route is below.")]), "yes")  # after the yes
        self.assertTrue(out["offer_preview"])

    def test_script_handles_role_buttons_and_uncovered_countries(self):
        p = " ".join(landing_chat.SYSTEM.split())
        self.assertIn("without repeating the opening line", p)
        self.assertIn("note_uncovered", p)
        self.assertIn("Never guess documents or rules for an uncovered country", p)
        self.assertIn("pasta, wine, olive oil, cheese", p)
        self.assertIn("Canada", p)
        self.assertIn("could not load", p)

    def test_script_asks_before_showing_the_preview(self):
        p = " ".join(landing_chat.SYSTEM.split())
        self.assertIn("Call offer_preview", p)
        self.assertIn("Yes, show me | Not now", p)
        self.assertIn("how MioTEM helps", p)

    def test_exporter_preview_needs_the_handling_questions_first(self):
        say(self._exporter(), "pasta to Germany")
        code, out = say(Script([tool("show_preview", {}), text("below")]), "ok")
        self.assertFalse(out["offer_preview"])

    def _talk_tem(self, said="I advise wine exporters selling to the US and pasta producers selling to the UK"):
        say(Script([tool("set_role", {"role": "tem"}), text("How many exporter clients do you serve?")]), "I am a TEM")
        say(Script([tool("save_answer", {"topic": "clients", "text": "about 8 exporters"}),
                    tool("save_answer", {"topic": "situation", "text": said}, "t2"), text("Where does the time go?")]), said)
        self._offer()

    def test_tem_with_no_covered_country_is_asked_before_any_offer(self):
        say(Script([tool("set_role", {"role": "tem"}), text("How many exporter clients do you serve?")]), "I am a TEM")
        say(Script([tool("save_answer", {"topic": "clients", "text": "10 exporters"}),
                    tool("save_answer", {"topic": "situation", "text": "all kinds of food to the UAE"}, "t2"),
                    text("Which products?")]), "all kinds of food to the UAE")
        c = Script([tool("offer_preview", {})], [text("Which typical clients?")])
        code, out = say(c, "ok")
        res = json.loads(c.calls[-1]["messages"][-1]["content"][0]["content"])
        self.assertFalse(res["ready"])
        code, out = say(Script([tool("show_preview", {"examples": [{"category": "wine", "country": "USA"}]}), text("below")]), "yes")
        self.assertFalse(out["offer_preview"])

    def test_vague_tem_with_covered_countries_gets_labelled_example_products(self):
        say(Script([tool("set_role", {"role": "tem"}), text("How many exporter clients do you serve?")]), "I am a TEM")
        say(Script([tool("save_answer", {"topic": "clients", "text": "10 exporters"}),
                    tool("save_answer", {"topic": "situation", "text": "all kinds of food to France, UK, Germany, USA and UAE"}, "t2"),
                    text("Which products?")]), "all kinds of food to France, UK, Germany, USA and UAE")
        code, out = say(Script([tool("offer_preview", {})], [text("Would you like to see a sample workspace?")]), "ok")
        self.assertFalse(out["offer_preview"])
        c = Script([tool("show_preview", {"examples": [{"category": "wine", "country": "USA"}, {"category": "oil", "country": "UAE"}]}), text("It is below.")])
        code, out = say(c, "yes")
        self.assertTrue(out["offer_preview"])
        pv = landing_chat.preview(app.con(), V1)
        self.assertEqual([(x["category"], x["country"], x["assumed"]) for x in pv["clients"]], [("wine", "USA", True)])  # UAE: not named as covered, olive oil: not a default

    def test_a_named_product_is_not_marked_as_assumed(self):
        self._talk_tem()
        say(Script([tool("show_preview", {"examples": [{"category": "wine", "country": "USA"}]}), text("below")]), "yes")
        pv = landing_chat.preview(app.con(), V1)
        self.assertEqual([x["assumed"] for x in pv["clients"]], [False])

    def test_tem_naming_an_uncovered_country_gets_the_notify_form(self):
        say(Script([tool("set_role", {"role": "tem"}), text("How many clients?")]), "I am a TEM")
        c = Script([tool("note_uncovered", {"countries": "UAE"})], [text("No list for UAE yet. Which products?")])
        code, out = say(c, "France, UK and UAE")
        self.assertTrue(out["offer_notify"])
        row = app.con().execute("SELECT answers FROM anon_chats WHERE visitor_id=?", (V1,)).fetchone()
        self.assertEqual(json.loads(row["answers"])["uncovered"], ["UAE"])

    def test_tem_preview_is_a_sample_workspace_with_two_labelled_clients(self):
        self._talk_tem()
        c = Script([tool("show_preview", {"examples": [{"category": "wine", "country": "USA"}, {"category": "pasta", "country": "UK"},
                                                       {"category": "oil", "country": "Mars"}]}), text("Your workspace is below.")])
        code, out = say(c, "mostly paperwork")
        self.assertTrue(out["offer_preview"])
        pv = landing_chat.preview(app.con(), V1)
        self.assertEqual(pv["kind"], "workspace")
        self.assertEqual([x["name"] for x in pv["clients"]], ["Example client A", "Example client B"])
        self.assertEqual([(x["category"], x["country"]) for x in pv["clients"]], [("wine", "USA"), ("pasta", "UK")])

    def test_tem_preview_is_refused_when_nothing_has_been_said(self):
        code, out = say(Script([tool("set_role", {"role": "tem"}),
                                tool("show_preview", {"examples": [{"category": "wine", "country": "USA"}]}, "t2"), text("ok")]), "I am a TEM")
        self.assertFalse(out["offer_preview"])
        self.assertEqual(landing_chat.preview(app.con(), V1)["kind"], None)

    def test_tem_examples_must_come_from_what_the_tem_said(self):
        self._talk_tem("I work with wine producers selling to Germany")
        code, out = say(Script([tool("show_preview", {"examples": [{"category": "wine", "country": "USA"}, {"category": "pasta", "country": "Germany"}]}),
                                text("below")]), "ok")
        self.assertFalse(out["offer_preview"])  # wine to USA: USA never named. pasta: never named.
        code, out = say(Script([tool("show_preview", {"examples": [{"category": "wine", "country": "Germany"}, {"category": "pasta", "country": "USA"}]}),
                                text("below")]), "ok")
        self.assertTrue(out["offer_preview"])
        pv = landing_chat.preview(app.con(), V1)
        self.assertEqual([(x["category"], x["country"]) for x in pv["clients"]], [("wine", "Germany")])

    def test_tem_preview_needs_the_client_count(self):
        say(Script([tool("set_role", {"role": "tem"}), tool("save_answer", {"topic": "situation", "text": "wine to the US"}, "t2"), text("ok")]), "TEM wine US")
        code, out = say(Script([tool("show_preview", {"examples": [{"category": "wine", "country": "USA"}]}), text("below")]), "go")
        self.assertFalse(out["offer_preview"])

    def test_preview_for_an_unknown_visitor_is_empty(self):
        self.assertEqual(landing_chat.preview(app.con(), "d" * 32), {"kind": None})
        self.assertEqual(landing_chat.preview(app.con(), "nope"), {"kind": None})

    def test_script_tells_the_ai_to_call_show_preview(self):
        p = " ".join(landing_chat.SYSTEM.split())
        self.assertIn("call show_preview", p)
        self.assertIn("do not describe its contents", p)
        self.assertIn("what to look for", p)
        self.assertIn("NEVER call show_preview on the first messages", p)
        self.assertIn("never invent example products or countries", p)

    def test_prompt_rules(self):
        p = landing_chat.SYSTEM
        self.assertNotIn(EM_DASH, p)
        for banned in ("SaaS", "traceability", "AI-powered"):
            self.assertIn('"%s"' % banned, p)  # only named as words never to use
        self.assertIn("Do NOT ask about a product or a destination", p)
        self.assertIn("Never state tariffs", p)
        for lg in ("it", "en"):
            self.assertNotIn(EM_DASH, landing_chat.OPENER[lg])


if __name__ == "__main__":
    unittest.main()
