import json
import os
import unittest
from unittest import mock

os.environ["DB_PATH"] = ":memory:"
from vialibera import app, notify, route_interest

V = "c" * 32


class RouteInterest(unittest.TestCase):
    def setUp(self):
        app.con().execute("DELETE FROM route_interest")
        app.con().execute("DELETE FROM anon_chats")
        app.con().execute("INSERT INTO anon_chats(visitor_id, ip_hash, role, history, answers, messages, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                          (V, "h", "exporter", "[]", json.dumps({"product": ["apples"], "destination": ["Canada"]}), 3, "2026-11-11T10:00:00", "2026-11-11T10:00:00"))
        for k in ("NOTIFY_SMTP_HOST", "NOTIFY_FROM", "NOTIFY_TO"):
            os.environ.pop(k, None)

    def ask(self, **kw):
        d = {"visitor": V, "email": "buyer@example.com", "name": "Rossi Srl", "consent": True, "lang": "en"}
        d.update(kw)
        return route_interest.record(app.con(), d)

    def test_it_records_the_route_in_the_visitors_own_words(self):
        code, out = self.ask(product="spirits", country="Mars")  # whatever the body says about the route is ignored
        self.assertEqual(code, 200)
        row = app.con().execute("SELECT product, country, email, name FROM route_interest").fetchone()
        self.assertEqual((row["product"], row["country"], row["email"], row["name"]), ("apples", "Canada", "buyer@example.com", "Rossi Srl"))

    def test_a_tem_asking_about_uncovered_countries_is_recorded_in_their_words(self):
        app.con().execute("UPDATE anon_chats SET role='tem', answers=? WHERE visitor_id=?", (json.dumps({"uncovered": ["UAE"]}), V))
        self.ask()
        row = app.con().execute("SELECT product, country FROM route_interest").fetchone()
        self.assertEqual((row["product"], row["country"]), ("TEM clients", "UAE"))

    def test_a_tem_introduction_request_is_recorded_as_interest_only(self):
        app.con().execute("UPDATE anon_chats SET answers=? WHERE visitor_id=?", (json.dumps({"product": ["wine"], "tem_intro": ["yes"]}), V))
        self.assertEqual(self.ask()[0], 200)
        row = app.con().execute("SELECT product, country FROM route_interest").fetchone()
        self.assertEqual((row["product"], row["country"]), ("TEM introduction", None))

    def test_consent_and_a_real_email_are_required(self):
        self.assertEqual(self.ask(consent=False)[0], 400)
        self.assertEqual(self.ask(consent="yes")[0], 400)
        self.assertEqual(self.ask(email="nope")[0], 400)
        self.assertEqual(app.con().execute("SELECT COUNT(*) AS n FROM route_interest").fetchone()["n"], 0)

    def test_a_filled_trap_looks_like_success_and_saves_nothing(self):
        code, out = self.ask(website="http://spam")
        self.assertEqual((code, out["ok"]), (200, True))
        self.assertEqual(app.con().execute("SELECT COUNT(*) AS n FROM route_interest").fetchone()["n"], 0)

    def test_one_request_per_email_per_day_and_an_hourly_cap(self):
        self.ask(); self.ask()
        self.assertEqual(app.con().execute("SELECT COUNT(*) AS n FROM route_interest").fetchone()["n"], 1)
        for i in range(route_interest.HOURLY_CAP):
            self.ask(email=f"p{i}@example.com")
        self.assertEqual(self.ask(email="late@example.com")[0], 429)

    def test_staff_listing(self):
        self.ask()
        lst = route_interest.listing(app.con())
        self.assertEqual((lst["total"], lst["requests"][0]["product"]), (1, "apples"))

    def test_staff_email_is_off_until_configured(self):
        self.assertFalse(notify.enabled())
        with mock.patch("smtplib.SMTP") as smtp:
            self.assertFalse(notify.send("s", "b"))
            smtp.assert_not_called()

    def test_staff_email_sends_when_configured_and_never_breaks_the_request(self):
        os.environ.update(NOTIFY_SMTP_HOST="smtp.example.com", NOTIFY_FROM="a@example.com", NOTIFY_TO="b@example.com")
        try:
            with mock.patch("smtplib.SMTP") as smtp:
                self.assertEqual(self.ask()[0], 200)
                inst = smtp.return_value.__enter__.return_value
                inst.send_message.assert_called_once()
                self.assertIn("apples", str(inst.send_message.call_args[0][0]))
            app.con().execute("DELETE FROM route_interest")
            with mock.patch("smtplib.SMTP", side_effect=OSError("down")):
                self.assertEqual(self.ask()[0], 200)  # a mail failure must not fail the visitor's request
        finally:
            for k in ("NOTIFY_SMTP_HOST", "NOTIFY_FROM", "NOTIFY_TO"):
                os.environ.pop(k, None)


if __name__ == "__main__":
    unittest.main()
