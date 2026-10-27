import os
import unittest
from types import SimpleNamespace as NS

os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, personas


class Fake:
    messages = NS(create=lambda **kw: NS(content=[NS(type="text", text="ok", model_dump=lambda: {"type": "text", "text": "ok"})]))


class PersonasTest(unittest.TestCase):
    def test_roster_is_balanced_and_complete(self):
        self.assertEqual(len(personas.ROSTER), 8)
        self.assertEqual(sum(p["gender"] == "f" for p in personas.ROSTER), 4)
        for p in personas.ROSTER:
            self.assertTrue(p["tone"] and p["styles"])

    def test_pick_respects_style_and_path_and_is_stable(self):
        a = personas.pick("u1", "numbers", 3)
        self.assertIn("numbers", a["styles"])
        self.assertEqual(a["fits"], "expanding")
        self.assertEqual(a, personas.pick("u1", "numbers", 3))
        self.assertEqual(personas.pick("u2", "steps", 1)["fits"], "first")

    def test_exclude(self):
        a = personas.pick("u1", "brief", 1)
        self.assertNotEqual(a["id"], personas.pick("u1", "brief", 1, exclude=(a["id"],))["id"])

    def test_prompt_says_ai_and_no_human_history(self):
        t = personas.system_prompt("giulia")
        self.assertIn("AI export manager", t)
        self.assertIn("never claim a human", t)

    def test_chat_assigns_and_keeps_persona_then_switch(self):
        w = {"user": "pp1", "org": None, "roles": []}
        accounts.record_consent(app.con(), "pp1", app.TERMS_VERSION, "it", True)
        app.handle_profile({"style": "steps"}, w)
        _, out = app.handle_chat({"message": "hi", "path_type": 1}, llm=Fake(), who=w)
        first = out["persona"]["id"]
        _, out2 = app.handle_chat({"message": "again"}, llm=Fake(), who=w)
        self.assertEqual(out2["persona"]["id"], first)
        _, prof = app.handle_profile({"switch": True}, w)
        self.assertNotEqual(prof["persona"]["id"], first)


if __name__ == "__main__":
    unittest.main()
