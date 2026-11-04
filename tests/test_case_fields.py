import json
import os
import unittest
from types import SimpleNamespace as NS

os.environ["DB_PATH"] = ":memory:"
from vialibera import agent, app, db, fields


def tool(name, inp, i):
    return NS(type="tool_use", id=i, name=name, input=inp,
              model_dump=lambda: {"type": "tool_use", "id": i, "name": name, "input": inp})


def text(t):
    return NS(type="text", text=t, model_dump=lambda: {"type": "text", "text": t})


class Script:
    def __init__(self, *responses):
        self.messages, self.responses, self.calls = self, list(responses), []

    def create(self, **kw):
        self.calls.append(kw)
        return NS(content=self.responses.pop(0))


class CaseFields(unittest.TestCase):
    def test_wrong_section_is_named_and_good_fields_still_saved(self):
        ok, err = fields.check_write("product", {"category": "pasta", "country": "UK"})
        self.assertEqual(ok, {"category": "pasta"})
        self.assertIn("country belongs in section market", err)

    def test_unknown_key_and_unknown_section(self):
        self.assertIn("destination is not a field", fields.check_write("market", {"destination": "UK"})[1])
        self.assertEqual(fields.check_write("shipping", {"x": 1})[0], {})
        self.assertIsNone(fields.check_write("market", {"country": "UK", "notes": "x", "importer_name": "Y"})[1])

    def test_guide_lists_every_field_and_sits_in_the_cached_block(self):
        g = fields.field_guide()
        for sec, key, *_ in fields.REQUIRED:
            self.assertIn(f"{sec}.{key}", g)
        cap = Script([text("Hi")])
        app.handle_chat({"message": "hi"}, llm=cap)
        self.assertIn("market.country", cap.calls[0]["system"][0]["text"])

    def test_both_facts_saved_in_one_call(self):
        ai = Script([text("Noted pasta to the UK. Brand name?"),
                     tool("case_write", {"section": "product", "fields": {"category": "pasta"}}, "a"),
                     tool("case_write", {"section": "market", "fields": {"country": "UK"}}, "b")])
        code, out = app.handle_chat({"message": "dried pasta to the UK"}, llm=ai)
        self.assertEqual(len(ai.calls), 1)
        c = db.case_read(app.con(), out["case_id"])
        self.assertEqual((c["product"]["category"], c["market"]["country"]), ("pasta", "UK"))
        from vialibera import requirements
        self.assertTrue(requirements.covers(c["product"]["category"], c["market"]["country"]))

    def test_wrong_key_goes_back_to_the_ai_which_fixes_it(self):
        ai = Script([text("Noted."), tool("case_write", {"section": "product", "fields": {"category": "pasta", "country": "UK"}}, "a")],
                    [text("Fixed. Brand name?"), tool("case_write", {"section": "market", "fields": {"country": "UK"}}, "b")])
        code, out = app.handle_chat({"message": "dried pasta to the UK"}, llm=ai)
        self.assertEqual(len(ai.calls), 2)
        result = json.loads(ai.calls[1]["messages"][-1]["content"][0]["content"])
        self.assertIn("belongs in section market", result["error"])
        self.assertEqual(db.case_read(app.con(), out["case_id"])["market"]["country"], "UK")

    def test_instructions_ask_for_all_saves_together(self):
        self.assertIn("market.country = UK", agent.SYSTEM)


if __name__ == "__main__":
    unittest.main()
