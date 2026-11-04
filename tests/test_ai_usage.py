import json
import os
import unittest
from types import SimpleNamespace as NS
from unittest import mock

os.environ["DB_PATH"] = ":memory:"
from vialibera import ai_usage, app, db, permissions


def usage(i=1000, o=100, cw=0, cr=0):
    return NS(input_tokens=i, output_tokens=o, cache_creation_input_tokens=cw, cache_read_input_tokens=cr)


class TwoCallAI:
    """First call saves a field with a tool, second call replies: like a real turn."""
    def __init__(self):
        self.messages, self.n = self, 0

    def create(self, **kw):
        self.n += 1
        if self.n % 2 == 1:
            tu = NS(type="tool_use", id="t%d" % self.n, name="case_write", input={"section": "product", "fields": {"category": "pasta"}},
                    model_dump=lambda: {"type": "tool_use", "id": "t1", "name": "case_write", "input": {}})
            return NS(content=[tu], usage=usage(2000, 50))
        return NS(content=[NS(type="text", text="Ciao", model_dump=lambda: {"type": "text", "text": "Ciao"})],
                  usage=usage(2100, 120, cr=1500))


def events(cid):
    return [json.loads(r["data"]) for r in app.con().execute(
        "SELECT data FROM events WHERE case_id=? AND kind='ai_usage' ORDER BY id", (cid,)).fetchall()]


class Usage(unittest.TestCase):
    def test_add_and_cost(self):
        acc = {}
        ai_usage.add(acc, usage(1_000_000, 0))
        ai_usage.add(acc, usage(0, 1_000_000, cw=1_000_000, cr=1_000_000))
        self.assertEqual(acc["calls"], 2)
        p = {"input": 2.0, "output": 10.0, "cache_write": 2.5, "cache_read": 0.1}
        self.assertAlmostEqual(ai_usage.cost(acc, p), 14.6)

    def test_stand_in_without_usage_counts_the_call_only(self):
        acc = ai_usage.add({}, None)
        self.assertEqual(acc, {"calls": 1})
        self.assertEqual(ai_usage.cost(acc), 0)

    def test_prices_can_be_overridden_and_bad_values_ignored(self):
        with mock.patch.dict(os.environ, {"AI_PRICES": '{"input": 3, "nonsense": 9}'}):
            self.assertEqual(ai_usage.prices()["input"], 3.0)
            self.assertNotIn("nonsense", ai_usage.prices())
        with mock.patch.dict(os.environ, {"AI_PRICES": "not json"}):
            self.assertEqual(ai_usage.prices(), ai_usage.DEFAULT_PRICES)

    def test_one_event_per_message_with_all_calls_summed(self):
        code, out = app.handle_chat({"message": "pasta"}, llm=TwoCallAI())
        self.assertEqual(code, 200)
        ev = events(out["case_id"])
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["calls"], 2)
        self.assertEqual(ev[0]["input"], 4100)
        self.assertEqual(ev[0]["output"], 170)
        self.assertEqual(ev[0]["cache_read"], 1500)
        self.assertGreater(ev[0]["cost_usd"], 0)
        self.assertFalse(ev[0]["load_test"])

    def test_failed_ai_call_still_records_what_was_spent(self):
        import anthropic
        class FailSecond(TwoCallAI):
            def create(self, **kw):
                if self.n == 1:
                    raise anthropic.APIConnectionError(request=mock.Mock())
                return super().create(**kw)
        with mock.patch.object(app.jobs, "ai_unavailable"):
            code, out = app.handle_chat({"message": "pasta"}, llm=FailSecond())
        self.assertEqual(code, 503)
        ev = events(out["case_id"])
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["calls"], 1)

    def test_load_tests_are_recorded_at_zero_cost_and_left_out_of_the_summary(self):
        sup = {"user": "staff-usage", "roles": [permissions.STAFF_CLAIM]}
        from vialibera import accounts
        accounts.record_consent(app.con(), sup["user"], app.TERMS_VERSION, "en", True)
        with mock.patch.object(app, "client", side_effect=AssertionError("no real AI")):
            code, out = app.handle_chat({"message": "x", "load_test": True, "delay": 0}, who=sup)
        self.assertEqual(code, 200)
        ev = events(out["case_id"])
        self.assertTrue(ev[0]["load_test"])
        self.assertEqual(ev[0]["cost_usd"], 0.0)
        s = ai_usage.summary(app.con())
        self.assertNotIn(out["case_id"], [c["case_id"] for c in s["top_cases"]])

    def test_summary_groups_by_day_and_conversation(self):
        _, out = app.handle_chat({"message": "pasta"}, llm=TwoCallAI())
        app.handle_chat({"message": "France", "case_id": out["case_id"]}, llm=TwoCallAI())
        s = ai_usage.summary(app.con())
        top = {c["case_id"]: c for c in s["top_cases"]}
        self.assertEqual(top[out["case_id"]]["messages"], 2)
        self.assertEqual(top[out["case_id"]]["calls"], 4)
        self.assertTrue(s["per_day"])
        self.assertGreaterEqual(s["total"]["messages"], 2)

    def test_admin_route_is_staff_only_and_tolerates_bad_days(self):
        sup = {"user": "staff-usage2", "roles": [permissions.STAFF_CLAIM]}
        self.assertEqual(app.handle_admin("/admin/ai_usage", {}, {"user": "c", "roles": []})[0], 403)
        code, out = app.handle_admin("/admin/ai_usage", {"days": "nonsense"}, sup)
        self.assertEqual(code, 200)
        self.assertEqual(out["days"], 14)
        self.assertEqual(app.handle_admin("/admin/ai_usage", {"days": 999}, sup)[1]["days"], 90)


if __name__ == "__main__":
    unittest.main()
