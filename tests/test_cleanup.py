"""Staff action: remove the caller's own load-test conversations (3 Nov 2026)."""
import unittest

from vialibera import accounts, admin, app, db, permissions

SUPER = {"user": "staff-clean", "roles": [permissions.STAFF_CLAIM]}


class Fake:
    def __init__(self):
        self.messages = self

    def create(self, **kw):
        from types import SimpleNamespace as NS
        return NS(content=[NS(type="text", text="ok", model_dump=lambda: {"type": "text", "text": "ok"})])


class LoadTestCleanup(unittest.TestCase):
    def setUp(self):
        self.con = db.connect()
        accounts.record_consent(self.con, SUPER["user"], app.TERMS_VERSION, "en", True)

    def chat(self, text, who=SUPER):
        cid = db.create_case(self.con, 1, owner_sub=who["user"])
        from vialibera import agent
        from vialibera.menu import MENU
        h = []
        agent.turn(Fake(), self.con, cid, MENU, h, text, lang="en")
        db.save_history(self.con, cid, h)
        return cid

    def count(self, table, cid, col="case_id"):
        return self.con.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {col}=?", (cid,)).fetchone()["n"]

    def test_preview_then_delete_only_load_tests(self):
        t1, t2 = self.chat("Load test 1: pasta"), self.chat("Load test B2: pasta")
        real = self.chat("I export pasta to the UK")
        later = self.chat("Hello")
        db.log_event(self.con, later, "client", "message", {"text": "Load test inside a real chat"})  # not the first message
        other = self.chat("Load test 3", who={"user": "someone-else", "roles": []})
        self.assertEqual(admin.load_test_cleanup(self.con, SUPER), (200, {"count": 2}))
        self.assertEqual(admin.load_test_cleanup(self.con, SUPER, True, 2), (200, {"removed": 2}))
        for cid in (t1, t2):
            self.assertEqual(self.count("cases", cid, "id"), 0)
            self.assertEqual(self.count("histories", cid), 0)
            self.assertEqual(self.count("events", cid), 0)
        for cid in (real, later, other):
            self.assertEqual(self.count("cases", cid, "id"), 1)
        self.assertIn("load_test_cleanup", str([e["data"] for e in admin.audit(self.con, SUPER)[1]["events"]]))

    def test_count_must_match_the_preview(self):
        self.chat("Load test 1")
        code, out = admin.load_test_cleanup(self.con, SUPER, True, 5)
        self.assertEqual((code, out["count"]), (409, 1))
        self.assertEqual(admin.load_test_cleanup(self.con, SUPER), (200, {"count": 1}))  # nothing removed

    def test_conversations_with_documents_are_kept(self):
        cid = self.chat("Load test with a file")
        self.con.execute("INSERT INTO project_docs(case_id, document_id, created_at) VALUES (?,?,?)", (cid, "d1", db.now()))
        self.assertEqual(admin.load_test_cleanup(self.con, SUPER), (200, {"count": 0}))

    def test_superadmin_only(self):
        self.assertEqual(admin.load_test_cleanup(self.con, {"user": "x", "roles": []})[0], 403)
