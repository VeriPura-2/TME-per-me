import os
import unittest

os.environ["DB_PATH"] = ":memory:"
from vialibera import app
from test_journey import who, make_case


def items(cid, u):
    _, out = app.handle_journey({"case_id": cid}, who(u))
    return {i["id"]: i for i in out["required_docs"]["data"]["items"]}


class MarksTest(unittest.TestCase):
    def test_mark_and_unmark(self):
        cid = make_case("m1")
        self.assertNotIn("marked", items(cid, "m1")["eori"])
        code, out = app.handle_mark({"case_id": cid, "item": "eori"}, who("m1"))
        self.assertEqual((code, out["marked"]), (200, True))
        it = items(cid, "m1")["eori"]
        self.assertIn("marked", it)
        self.assertFalse(it["on_file"])  # ticked by hand is not a document on file
        self.assertNotIn("confirmed", it)  # and not a staff confirmation
        code, out = app.handle_mark({"case_id": cid, "item": "eori", "on": False}, who("m1"))
        self.assertEqual((code, out["marked"]), (200, False))
        self.assertNotIn("marked", items(cid, "m1")["eori"])

    def test_unknown_item_is_refused(self):
        cid = make_case("m2")
        self.assertEqual(app.handle_mark({"case_id": cid, "item": "nope"}, who("m2"))[0], 400)

    def test_another_account_gets_404(self):
        cid = make_case("m3")
        self.assertEqual(app.handle_mark({"case_id": cid, "item": "eori"}, who("intruder"))[0], 404)

    def test_reviewer_cannot_mark(self):
        from vialibera import permissions
        self.assertFalse(permissions.allowed("reviewer", "write"))
        self.assertTrue(permissions.allowed("member", "write"))

    def test_marks_are_per_project(self):
        a, b = make_case("m4"), make_case("m4")
        app.handle_mark({"case_id": a, "item": "eori"}, who("m4"))
        self.assertIn("marked", items(a, "m4")["eori"])
        self.assertNotIn("marked", items(b, "m4")["eori"])


if __name__ == "__main__":
    unittest.main()
