import os
import unittest

os.environ["DB_PATH"] = ":memory:"
from vialibera import app, tem_interest

EM_DASH = "—"


class TemInterest(unittest.TestCase):
    def setUp(self):
        app.con().execute("DELETE FROM tem_interest")

    def test_records_and_lists(self):
        code, out = tem_interest.record(app.con(), {"firm_name": "Studio Rossi", "email": "A@Rossi.it", "clients": "12", "lang": "it"})
        self.assertEqual((code, out), (200, {"ok": True}))
        got = tem_interest.listing(app.con())
        self.assertEqual(got["total"], 1)
        self.assertEqual(got["requests"][0]["email"], "a@rossi.it")

    def test_needs_firm_and_a_valid_email(self):
        for d in ({"firm_name": "", "email": "a@b.it"}, {"firm_name": "X", "email": "nope"}, {"firm_name": "X"}):
            self.assertEqual(tem_interest.record(app.con(), d)[0], 400)
        self.assertEqual(tem_interest.listing(app.con())["total"], 0)

    def test_trap_field_looks_like_success_and_saves_nothing(self):
        code, out = tem_interest.record(app.con(), {"firm_name": "Bot", "email": "bot@x.com", "website": "http://spam"})
        self.assertEqual((code, out), (200, {"ok": True}))
        self.assertEqual(tem_interest.listing(app.con())["total"], 0)

    def test_same_email_once_a_day(self):
        d = {"firm_name": "Studio", "email": "a@b.it"}
        tem_interest.record(app.con(), d)
        tem_interest.record(app.con(), d)
        self.assertEqual(tem_interest.listing(app.con())["total"], 1)

    def test_hourly_cap(self):
        for i in range(tem_interest.HOURLY_CAP):
            tem_interest.record(app.con(), {"firm_name": "S", "email": f"u{i}@b.it"})
        self.assertEqual(tem_interest.record(app.con(), {"firm_name": "S", "email": "late@b.it"})[0], 429)

    def test_landing_texts_have_no_em_dash(self):
        html = open(os.path.join(os.path.dirname(app.__file__), "static", "index.html"), encoding="utf-8").read()
        self.assertNotIn(EM_DASH, html)


if __name__ == "__main__":
    unittest.main()
