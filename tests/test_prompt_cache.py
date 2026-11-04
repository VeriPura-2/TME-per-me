import json
import os
import unittest
from types import SimpleNamespace as NS

os.environ["DB_PATH"] = ":memory:"
from vialibera import agent, app, db


class Capture:
    """Records every request; first call writes a field with a tool, second call replies."""
    def __init__(self):
        self.messages, self.calls = self, []

    def create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=str)))
        if len(self.calls) % 2 == 1:
            return NS(content=[NS(type="tool_use", id="t1", name="case_write",
                                  input={"section": "product", "fields": {"category": "pasta"}},
                                  model_dump=lambda: {"type": "tool_use", "id": "t1", "name": "case_write",
                                                      "input": {"section": "product", "fields": {"category": "pasta"}}})])
        return NS(content=[NS(type="text", text="Ciao", model_dump=lambda: {"type": "text", "text": "Ciao"})])


def marks(obj):
    return json.dumps(obj).count('"cache_control"')


class PromptCache(unittest.TestCase):
    def test_fixed_instructions_are_cached_and_case_note_is_not(self):
        cap = Capture()
        app.handle_chat({"message": "pasta"}, llm=cap)
        sysb = cap.calls[0]["system"]
        self.assertEqual(len(sysb), 2)
        self.assertIn("cache_control", sysb[0])
        self.assertIn("Trade Export Manager", sysb[0]["text"])
        self.assertNotIn("cache_control", sysb[1])

    def test_fixed_part_is_identical_across_calls_so_the_cache_can_hit(self):
        cap = Capture()
        _, out = app.handle_chat({"message": "pasta"}, llm=cap)
        app.handle_chat({"message": "France", "case_id": out["case_id"]}, llm=cap)
        fixed = {c["system"][0]["text"] for c in cap.calls}
        self.assertEqual(len(fixed), 1)

    def test_last_message_is_marked_and_never_more_than_four_marks(self):
        cap = Capture()
        _, out = app.handle_chat({"message": "one"}, llm=cap)
        for m in ("two", "three", "four", "five"):
            app.handle_chat({"message": m, "case_id": out["case_id"]}, llm=cap)
        for c in cap.calls:
            self.assertIn("cache_control", json.dumps(c["messages"][-1]))
            self.assertLessEqual(marks(c["system"]) + marks(c["messages"]), 4)

    def test_saved_history_has_no_cache_marks(self):
        cap = Capture()
        _, out = app.handle_chat({"message": "pasta"}, llm=cap)
        app.handle_chat({"message": "France", "case_id": out["case_id"]}, llm=cap)
        self.assertEqual(marks(db.load_history(app.con(), out["case_id"])), 0)

    def test_cached_messages_handles_text_and_block_content_and_empty(self):
        self.assertEqual(agent.cached_messages([]), [])
        h = [{"role": "user", "content": "hi"}]
        out = agent.cached_messages(h)
        self.assertEqual(out[0]["content"], [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}])
        self.assertEqual(h, [{"role": "user", "content": "hi"}])
        h2 = [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "{}"}]}]
        self.assertIn("cache_control", agent.cached_messages(h2)[0]["content"][0])
        self.assertNotIn("cache_control", h2[0]["content"][0])


if __name__ == "__main__":
    unittest.main()
