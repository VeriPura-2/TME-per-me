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
            self.assertEqual(say(Script(), "hi", v="f" * 32)[0], 503)
            self.assertEqual(say(Script([text("ok")]), "hi", v="e" * 32, ip="2.2.2.2")[0], 200)
        finally:
            landing_chat.IP_DAILY_CAP = old

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
