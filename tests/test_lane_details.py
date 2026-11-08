import os
import unittest
from unittest import mock

os.environ["DB_PATH"] = ":memory:"
from vialibera import app, vat_check
from test_start_form import user


class LaneDetails(unittest.TestCase):
    def setUp(self):
        v = mock.patch.object(vat_check, "vies", return_value={"state": "unavailable", "name": None, "address": None, "checked_at": "2026-11-04T12:00:00+00:00"})
        v.start(); self.addCleanup(v.stop)

    def start(self, name, cat="bakery", country="France"):
        who = user(name)
        _, out = app.handle_start({"category": cat, "country": country}, who)
        return who, out["case_id"]

    def test_details_are_saved_and_shown_in_the_journey(self):
        who, cid = self.start("ld1")
        _, j = app.handle_journey({"case_id": cid}, who)
        self.assertEqual(j["lane_request"], {"timing": "", "volume": "", "buyer": ""})
        code, out = app.handle_lane_details({"case_id": cid, "timing": "March", "volume": "2 pallets", "buyer": "no"}, who)
        self.assertEqual(code, 200)
        _, j = app.handle_journey({"case_id": cid}, who)
        self.assertEqual(j["lane_request"], {"timing": "March", "volume": "2 pallets", "buyer": "no"})

    def test_skipping_is_allowed_and_covered_routes_have_no_card(self):
        who, cid = self.start("ld2")
        self.assertEqual(app.handle_lane_details({"case_id": cid}, who)[0], 200)
        who2, cid2 = self.start("ld3", "wine", "USA")
        _, j = app.handle_journey({"case_id": cid2}, who2)
        self.assertNotIn("lane_request", j)

    def test_other_account_gets_404(self):
        who, cid = self.start("ld4")
        self.assertEqual(app.handle_lane_details({"case_id": cid, "timing": "x"}, user("intruder2"))[0], 404)


if __name__ == "__main__":
    unittest.main()
