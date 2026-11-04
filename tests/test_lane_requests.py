import json
import os
import unittest
from types import SimpleNamespace as NS
from unittest import mock

os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, agent, app, db, lane_requests, permissions, vat_check


def user(name):
    accounts.record_consent(app.con(), name, app.TERMS_VERSION, "en", True)
    return {"user": name, "roles": []}


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
        return NS(content=self.responses.pop(0))


class LaneRequests(unittest.TestCase):
    def test_record_then_update_the_same_request(self):
        c = app.con()
        cid = db.create_case(c, 1)
        r1 = lane_requests.record(c, cid, "u1", {"product": "wine", "country": "Japan"})
        r2 = lane_requests.record(c, cid, None, {"country": "Japan", "timing": "spring 2027", "volume": "2 pallets"})
        self.assertEqual(r1["request_id"], r2["request_id"])
        row = c.execute("SELECT * FROM lane_requests WHERE id=?", (r1["request_id"],)).fetchone()
        self.assertEqual((row["product"], row["timing"], row["volume"]), ("wine", "spring 2027", "2 pallets"))

    def test_a_different_country_is_a_new_request(self):
        c = app.con()
        cid = db.create_case(c, 1)
        a = lane_requests.record(c, cid, "u1", {"product": "wine", "country": "Japan"})
        b = lane_requests.record(c, cid, "u1", {"product": "wine", "country": "Sweden"})
        self.assertNotEqual(a["request_id"], b["request_id"])

    def test_empty_request_is_refused(self):
        self.assertIn("error", lane_requests.record(app.con(), None, "u", {"timing": "soon"}))

    def test_listing_counts_by_country_and_product(self):
        c = app.con()
        for country in ("japan", "Japan", "Sweden"):
            lane_requests.record(c, db.create_case(c, 1), "u", {"product": "Wine", "country": country})
        out = lane_requests.listing(c)
        top = {x["name"]: x["n"] for x in out["by_country"]}
        self.assertGreaterEqual(top["Japan"], 2)
        self.assertIn("wine", {x["name"] for x in out["by_product"]})

    def test_the_ai_records_a_request_without_a_second_call(self):
        ai = Script([text("MioTEM does not yet have a checked document list for wine to Japan. When do you plan to ship?"),
                     tool("lane_request", {"product": "wine", "country": "Japan"})])
        code, out = app.handle_chat({"message": "wine to Japan"}, llm=ai)
        self.assertEqual(code, 200)
        self.assertEqual(len(ai.calls), 1)
        row = app.con().execute("SELECT * FROM lane_requests WHERE case_id=?", (out["case_id"],)).fetchone()
        self.assertEqual((row["product"], row["country"], row["source"]), ("wine", "Japan", "chat"))

    def test_prompt_lists_coverage_and_bans_internal_words(self):
        self.assertIn("lane_request", agent.QUIET_TOOLS)
        self.assertIn("Austria", agent.SYSTEM)
        self.assertIn('never "wave"', agent.SYSTEM)

    def test_start_form_other_country_records_the_request(self):
        with mock.patch.object(vat_check, "vies", return_value={"state": "unavailable", "name": None, "address": None,
                                                                 "checked_at": "2026-11-04T12:00:00+00:00"}):
            code, out = app.handle_start({"category": "wine", "country": "other", "other_country": "Japan"}, user("lr-a"))
        self.assertEqual(code, 200)
        self.assertFalse(out["covered"])
        self.assertEqual(out["requested"]["country"], "Japan")
        row = app.con().execute("SELECT * FROM lane_requests WHERE case_id=?", (out["case_id"],)).fetchone()
        self.assertEqual((row["product"], row["country"], row["source"]), ("wine", "Japan", "start_form"))

    def test_other_text_is_ignored_unless_other_was_chosen(self):
        code, out = app.handle_start({"category": "pasta", "country": "France", "other_country": "Japan"}, user("lr-b"))
        self.assertNotIn("requested", out)

    def test_staff_route(self):
        self.assertEqual(app.handle_admin("/admin/lane_requests", {}, {"user": "x", "roles": []})[0], 403)
        code, out = app.handle_admin("/admin/lane_requests", {}, {"user": "s", "roles": [permissions.STAFF_CLAIM]})
        self.assertEqual(code, 200)
        self.assertIn("by_country", out)

    def test_removed_with_the_case_in_load_test_cleanup(self):
        from vialibera import admin
        self.assertIn("lane_requests", admin.CASE_TABLES)


if __name__ == "__main__":
    unittest.main()
