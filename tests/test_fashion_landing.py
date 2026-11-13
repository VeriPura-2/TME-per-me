"""Fashion on the landing chat: interest only, no checklist, no preview. No AI calls."""
import unittest

from vialibera import landing_chat


def state(role="exporter", **answers):
    return {"role": role, "answers": dict(answers), "messages_so_far": 5, "con": None}


class FashionLanding(unittest.TestCase):
    def test_note_fashion_records_interest_and_shows_the_fashion_form(self):
        s = state()
        r = landing_chat.run_tool(s, "note_fashion", {})
        self.assertTrue(r["ok"])
        self.assertEqual(s["answers"]["fashion"], ["yes"])
        self.assertTrue(s["offer_notify"])
        self.assertEqual(s["notify_kind"], "fashion")

    def test_note_fashion_needs_a_role(self):
        self.assertIn("error", landing_chat.run_tool(state(role=None), "note_fashion", {}))

    def test_no_preview_for_fashion(self):
        s = state(fashion=["yes"], preview_offered=["1"], category="other", country="UK")
        self.assertFalse(landing_chat.run_tool(s, "offer_preview", {}).get("ready", True))
        self.assertIn("error", landing_chat.run_tool(s, "show_preview", {}))
        self.assertNotIn("preview_ok", s["answers"])

    def test_fashion_words_do_not_count_as_a_food_product_for_a_tem(self):
        s = state(role="tem", fashion=["yes"], product=["shoes"])
        self.assertNotIn("yes", landing_chat._said(s))

    def test_the_prompt_names_fashion_without_claiming_coverage(self):
        self.assertIn("Is it food, apparel or something else?", landing_chat.SYSTEM)
        self.assertNotIn("—", landing_chat.SYSTEM)


class TemQuestions(unittest.TestCase):
    def test_tem_path_asks_weekly_hours_and_the_revenue_need_payoff(self):
        self.assertIn("hours a week they spend chasing documents", landing_chat.SYSTEM)
        self.assertIn("growing your clients'", landing_chat.SYSTEM)
        self.assertIn("coming soon through VeriPura CORE, but never that it is available now", landing_chat.SYSTEM)

    def test_a_tem_is_asked_the_weekly_hours_before_the_preview_is_offered(self):
        s = state(role="tem", clients=["8"], product=["wine to the UK"])
        r = landing_chat.run_tool(s, "offer_preview", {})
        self.assertFalse(r.get("ready", True))
        self.assertIn("hours a week", r["instruction"])
        self.assertNotIn("preview_offered", s["answers"])


class SomethingElse(unittest.TestCase):
    def test_note_other_then_the_contact_form(self):
        s = state()
        self.assertIn("error", landing_chat.run_tool(state(), "offer_contact_form", {}))  # not before note_other
        self.assertTrue(landing_chat.run_tool(s, "note_other", {})["ok"])
        self.assertFalse(s.get("offer_notify"))
        self.assertTrue(landing_chat.run_tool(s, "offer_contact_form", {})["ok"])
        self.assertTrue(s["offer_notify"])
        self.assertEqual(s["notify_kind"], "other")

    def test_no_preview_for_something_else(self):
        s = state(other=["yes"])
        self.assertFalse(landing_chat.run_tool(s, "offer_preview", {}).get("ready", True))
        self.assertIn("error", landing_chat.run_tool(s, "show_preview", {}))

    def test_record_keeps_details_and_a_clean_optional_phone(self):
        import json
        from vialibera import db, route_interest
        con = db.connect()
        v = "a" * 32
        ans = {"other": ["yes"], "other_product": ["handmade ceramics"], "transactions": ["about 40"], "avg_value": ["2,000 EUR"],
               "product_types": ["tableware"], "markets": ["USA, Japan"]}
        con.execute("INSERT INTO anon_chats(visitor_id, ip_hash, role, history, answers, messages, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                    (v, "h", "exporter", "[]", json.dumps(ans), 4, db.now(), db.now()))
        code, _ = route_interest.record(con, {"visitor": v, "email": "a@b.it", "consent": True, "phone": "+39 333 123 4567 <script>"})
        self.assertEqual(code, 200)
        row = con.execute("SELECT product, phone, details FROM route_interest").fetchone()
        self.assertEqual(row["product"], "Other: handmade ceramics")
        self.assertEqual(row["phone"], "+39 333 123 4567")
        self.assertIn("transactions a year: about 40", row["details"])
        self.assertIn("target markets: USA, Japan", row["details"])
        code, _ = route_interest.record(con, {"visitor": v, "email": "c@d.it", "consent": True, "phone": "abc"})
        self.assertIsNone(con.execute("SELECT phone FROM route_interest WHERE email='c@d.it'").fetchone()["phone"])

    def test_the_prompt_asks_the_third_option_and_never_collects_contacts_in_chat(self):
        self.assertIn("Food | Apparel | Something else", landing_chat.SYSTEM)
        self.assertIn("Never ask for the email or phone in the chat itself", landing_chat.SYSTEM)


if __name__ == "__main__":
    unittest.main()
