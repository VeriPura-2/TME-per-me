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
        self.assertIn("Is it food or fashion?", landing_chat.SYSTEM)
        self.assertNotIn("—", landing_chat.SYSTEM)


if __name__ == "__main__":
    unittest.main()


class TemQuestions(unittest.TestCase):
    def test_tem_path_asks_weekly_hours_and_the_revenue_need_payoff(self):
        self.assertIn("hours a week they spend chasing documents", landing_chat.SYSTEM)
        self.assertIn("growing your clients'", landing_chat.SYSTEM)
        self.assertIn("coming soon through VeriPura CORE, but never that it is available now", landing_chat.SYSTEM)
