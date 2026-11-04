import json
import os
import unittest
from types import SimpleNamespace as NS

os.environ["DB_PATH"] = ":memory:"
from vialibera import agent, app, db


def tool(name, inp, i="t1"):
    return NS(type="tool_use", id=i, name=name, input=inp,
              model_dump=lambda: {"type": "tool_use", "id": i, "name": name, "input": inp})


def text(t):
    return NS(type="text", text=t, model_dump=lambda: {"type": "text", "text": t})


class Script:
    """Answers with the scripted responses in order, recording each request."""
    def __init__(self, *responses):
        self.messages, self.responses, self.calls = self, list(responses), []

    def create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=str)))
        return NS(content=self.responses.pop(0))


def case(cid):
    return db.case_read(app.con(), cid)


class OneCall(unittest.TestCase):
    def test_save_and_reply_in_one_response_needs_one_call(self):
        ai = Script([text("Saved. Which country?"), tool("case_write", {"section": "product", "fields": {"category": "pasta"}})])
        code, out = app.handle_chat({"message": "dried pasta"}, llm=ai)
        self.assertEqual(code, 200)
        self.assertEqual(len(ai.calls), 1)
        self.assertEqual(out["reply"], "Saved. Which country?")
        self.assertEqual(case(out["case_id"])["product"]["category"], "pasta")

    def test_next_message_joins_the_pending_tool_results(self):
        ai = Script([text("Which country?"), tool("case_write", {"section": "product", "fields": {"category": "pasta"}})],
                    [text("France noted.")])
        _, out = app.handle_chat({"message": "dried pasta"}, llm=ai)
        app.handle_chat({"message": "France", "case_id": out["case_id"]}, llm=ai)
        msgs = ai.calls[1]["messages"]
        roles = [m["role"] for m in msgs]
        self.assertEqual(roles, ["user", "assistant", "user"])  # strictly alternating
        last = msgs[-1]["content"]
        self.assertEqual(last[0]["type"], "tool_result")
        self.assertEqual(last[-1]["text"], "France")
        h = db.load_history(app.con(), out["case_id"])
        self.assertEqual([m["role"] for m in h], ["user", "assistant", "user", "assistant"])

    def test_save_without_text_still_makes_the_second_call(self):
        ai = Script([tool("case_write", {"section": "product", "fields": {"category": "pasta"}})], [text("Which country?")])
        _, out = app.handle_chat({"message": "dried pasta"}, llm=ai)
        self.assertEqual(len(ai.calls), 2)
        self.assertEqual(out["reply"], "Which country?")

    def test_failed_save_goes_back_to_the_ai(self):
        ai = Script([text("Saved."), tool("case_write", {"section": "nonsense", "fields": {"x": 1}})], [text("Let me fix that.")])
        _, out = app.handle_chat({"message": "x"}, llm=ai)
        self.assertEqual(len(ai.calls), 2)
        self.assertEqual(out["reply"], "Let me fix that.")

    def test_other_tools_still_get_a_follow_up_call(self):
        ai = Script([text("Proposing."), tool("propose_item", {"code": "NOPE"})], [text("Done.")])
        _, out = app.handle_chat({"message": "x"}, llm=ai)
        self.assertEqual(len(ai.calls), 2)

    def test_instructions_ask_for_the_reply_with_the_save(self):
        self.assertIn("SAME", agent.SYSTEM)
        self.assertIn("case_write", agent.QUIET_TOOLS)
        self.assertNotIn("case_read", agent.QUIET_TOOLS)


if __name__ == "__main__":
    unittest.main()
