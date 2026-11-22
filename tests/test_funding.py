"""F5 (22 Nov 2026): funding schemes with an official source and a check date per fact."""
import os
import unittest
from datetime import date

os.environ.setdefault("DB_PATH", ":memory:")
from vialibera import app, funding, jobs, tools

EM_DASH = "—"


class FundingData(unittest.TestCase):
    def test_every_fact_has_an_official_source_and_a_check_date(self):
        for s in funding.schemes():
            self.assertIn(s["status"]["value"], funding.STATUSES, s["id"])
            for name, v in [("status", s["status"])] + list(s.get("facts", {}).items()):
                self.assertIn(name, ("status",) + funding.FACT_FIELDS, s["id"])
                self.assertTrue(v["source"].startswith("https://"), (s["id"], name))
                date.fromisoformat(v["checked"])
            self.assertTrue(s["note"]["en"] and s["note"]["it"])
            self.assertNotIn(EM_DASH, s["note"]["en"] + s["note"]["it"] + s["label"]["en"] + s["label"]["it"])
            self.assertNotIn("voucher", s["note"]["en"].lower())

    def test_recheck_of_22_nov_2026(self):
        by = {s["id"]: s for s in funding.schemes()}
        self.assertIn("29.10.2026", by["simest_tm"]["url"])
        self.assertEqual(by["simest_tm"]["status"]["value"], "no_window")
        self.assertEqual(by["er_digital_export_2026"]["status"]["value"], "closed")
        self.assertEqual(by["to_intl_2026"]["status"]["value"], "open")
        self.assertEqual(by["to_intl_2026"]["facts"]["deadline"]["value"], "2026-12-18")
        self.assertEqual(by["aa_brochure_2026"]["status"]["value"], "closed")

    def test_card_lines_carry_the_check_date_and_go_stale_after_30_days(self):
        links = funding.card_links()
        self.assertTrue(all(l["checked"] == "2026-11-22" for l in links))
        self.assertFalse(funding._stale("2026-11-22", date(2026, 12, 22)))
        self.assertTrue(funding._stale("2026-11-22", date(2026, 12, 23)))
        html = open(os.path.join(os.path.dirname(funding.__file__), "static", "index.html"), encoding="utf-8").read()
        self.assertIn("/ 86400000 > %d ? t.chk_stale" % funding.STALE_DAYS, html)
        card = {c["id"]: c for c in tools.for_case("wine", "USA")}["funding"]
        self.assertEqual(len(card["today"]["links"]), len(funding.schemes()))

    def test_the_weekly_watch_reads_every_scheme_page_and_names_the_scheme(self):
        urls = jobs.source_urls()
        for s in funding.schemes():
            self.assertIn(s["url"], urls)
        self.assertEqual(funding.scheme_for_url(funding.schemes()[0]["url"]), [funding.schemes()[0]["id"]])

    def test_stale_schemes_raise_one_staff_alert_each(self):
        c = app.con()
        c.execute("DELETE FROM data_changes WHERE kind='funding_stale'")
        orig = funding.stale_list
        funding.stale_list = lambda today=None: [{"id": "simest_tm", "checked": "2026-11-22"}]
        try:
            self.assertEqual(jobs.flag_stale_funding(c), 1)
            self.assertEqual(jobs.flag_stale_funding(c), 0)
        finally:
            funding.stale_list = orig
