import os
import unittest
from types import SimpleNamespace as NS

os.environ["DB_PATH"] = ":memory:"
from vialibera import app


class Fake:
    def __init__(self):
        self.messages = self

    def create(self, **kw):
        return NS(content=[NS(type="text", text="Ciao", model_dump=lambda: {"type": "text", "text": "Ciao"})])


class AppTest(unittest.TestCase):
    def test_chat_creates_case_and_replies(self):
        code, out = app.handle_chat({"message": "hello"}, llm=Fake())
        self.assertEqual(code, 200)
        self.assertEqual(out["reply"], "Ciao")
        code2, out2 = app.handle_chat({"message": "again", "case_id": out["case_id"]}, llm=Fake())
        self.assertEqual(out2["case_id"], out["case_id"])

    def test_history_persists_between_turns(self):
        _, out = app.handle_chat({"message": "first"}, llm=Fake())
        app.handle_chat({"message": "second", "case_id": out["case_id"]}, llm=Fake())
        from vialibera import db
        h = db.load_history(app.con(), out["case_id"])
        self.assertEqual([m["role"] for m in h], ["user", "assistant", "user", "assistant"])

    def test_empty_message_rejected(self):
        self.assertEqual(app.handle_chat({"message": " "}, llm=Fake())[0], 400)


class Broke:
    """The AI service refuses the call, as on 3 Nov 2026 (credit balance too low)."""
    def __init__(self):
        self.messages = self

    def create(self, **kw):
        import anthropic
        from unittest import mock
        resp = mock.Mock(status_code=400, request=mock.Mock(), headers={})
        raise anthropic.BadRequestError("Your credit balance is too low to access the Anthropic API.",
                                        response=resp, body=None)


class AIUnavailable(unittest.TestCase):
    def setUp(self):
        app.con().execute("DELETE FROM data_changes WHERE kind='ai_unavailable'")

    def test_client_gets_a_clear_answer_and_the_message_is_not_saved(self):
        from vialibera import db
        _, ok = app.handle_chat({"message": "first"}, llm=Fake())
        code, out = app.handle_chat({"message": "second", "case_id": ok["case_id"]}, llm=Broke())
        self.assertEqual((code, out["error"]), (503, "ai_unavailable"))
        h = db.load_history(app.con(), ok["case_id"])
        self.assertEqual([m["role"] for m in h], ["user", "assistant"])  # "second" not stored: resending starts clean

    def test_staff_alert_once_an_hour_with_the_providers_reason(self):
        from vialibera import jobs
        app.handle_chat({"message": "a"}, llm=Broke())
        app.handle_chat({"message": "b"}, llm=Broke())
        alerts = [c for c in jobs.changes(app.con()) if c["kind"] == "ai_unavailable"]
        self.assertEqual(len(alerts), 1)
        self.assertIn("credit balance is too low", alerts[0]["summary"])
        self.assertEqual(alerts[0]["detail"]["status"], 400)


class LoadTestStandIn(unittest.TestCase):
    """Load tests use a stand-in for the AI (superadmin only): no credit spent."""
    def setUp(self):
        from vialibera import permissions
        self.SUPER = {"user": "staff1", "roles": [permissions.STAFF_CLAIM]}
        from unittest import mock
        p = mock.patch.object(app, "client", side_effect=AssertionError("the real AI must not be called"))
        p.start()
        self.addCleanup(p.stop)

    def _consent(self, who):
        from vialibera import accounts
        accounts.record_consent(app.con(), who["user"], app.TERMS_VERSION, "en", True)

    def test_superadmin_load_test_uses_the_stand_in_and_marks_the_message(self):
        from vialibera import db
        self._consent(self.SUPER)
        code, out = app.handle_chat({"message": "hello", "load_test": True, "delay": 0}, who=self.SUPER)
        self.assertEqual(code, 200)
        self.assertIn("stand-in", out["reply"])
        h = db.load_history(app.con(), out["case_id"])
        self.assertTrue(h[0]["content"].startswith("Load test"))

    def test_anyone_else_is_refused_not_given_the_real_ai(self):
        client = {"user": "client1", "roles": []}
        self._consent(client)
        self.assertEqual(app.handle_chat({"message": "hi", "load_test": True}, who=client)[0], 403)
        self.assertEqual(app.handle_chat({"message": "hi", "load_test": True})[0], 403)

    def test_delay_is_capped_and_bad_values_use_the_default(self):
        from unittest import mock
        self._consent(self.SUPER)
        slept = []
        with mock.patch.object(app.time, "sleep", slept.append):
            app.handle_chat({"message": "x", "load_test": True, "delay": 99}, who=self.SUPER)
            app.handle_chat({"message": "y", "load_test": True, "delay": "nonsense"}, who=self.SUPER)
        self.assertEqual(slept, [30.0, 7.0])


if __name__ == "__main__":
    unittest.main()
