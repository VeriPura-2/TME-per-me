import unittest
from types import SimpleNamespace as NS

from vialibera import agent, db

MENU = {"label_review": {"price_cents": 3000}}


class Block(NS):
    def model_dump(self):
        return dict(self.__dict__)


class FakeClient:
    """Scripted replies: write case, propose a bad code, then a real one, then final text."""

    def __init__(self):
        self.messages = self
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        script = [
            [Block(type="tool_use", id="1", name="case_write",
                   input={"section": "product", "fields": {"name": "pasta"}})],
            [Block(type="tool_use", id="2", name="propose_item", input={"code": "invented"}),
             Block(type="tool_use", id="3", name="propose_item", input={"code": "label_review"})],
            [Block(type="text", text="Done.")],
        ]
        return NS(content=script[self.calls - 1])


class AgentTest(unittest.TestCase):
    def test_turn_writes_case_and_gates_items(self):
        con = db.connect()
        cid = db.create_case(con, 1)
        out = agent.turn(FakeClient(), con, cid, MENU, [], "We make pasta")
        self.assertEqual(out, "Done.")
        self.assertEqual(db.case_read(con, cid)["product"], {"name": "pasta"})
        codes = [r["code"] for r in con.execute("SELECT code FROM items")]
        self.assertEqual(codes, ["label_review"])  # invented code rejected by the gate


if __name__ == "__main__":
    unittest.main()
