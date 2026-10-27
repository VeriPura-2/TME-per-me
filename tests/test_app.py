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


if __name__ == "__main__":
    unittest.main()
