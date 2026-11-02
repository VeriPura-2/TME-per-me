import os
import unittest
from datetime import date, datetime, timedelta, timezone

from vialibera import db, jobs, tariff_watch as tw

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "ch_duty_rates_sample.xlsx")
PAGE = ('<a href="/dam/en/sd-web/abc/file_description_duty_rates.xlsx">d</a>'
        '<a href="https://www.bazg.admin.ch/dam/en/sd-web/suXEbuatJI1d/duty_rates_chapter_01_to_30.xlsx">1-30</a>')


def fresh():
    return db.connect()  # a new in-memory database each time


def fake_get(url, timeout=60, limit=0):
    if url == tw.CH_PAGE:
        return PAGE.encode()
    if url.endswith("duty_rates_chapter_01_to_30.xlsx"):
        return open(FIX, "rb").read()
    raise OSError("unexpected url " + url)


class SwissFileTest(unittest.TestCase):
    """Values checked by hand in Tares on 2 Nov 2026 (goods from Italy)."""

    def setUp(self):
        self.rates = tw.ch_rates(open(FIX, "rb").read(), {l[3] for l in tw.LINES if l[1] == "CH"}, on=date(2026, 11, 2))

    def test_known_swiss_rates(self):
        self.assertEqual(self.rates["1902.1910"]["eu_rate"], "CHF 1.60 per 100 kg net mass")
        self.assertEqual(self.rates["1902.1910"]["normal_rate"], "CHF 14.60 per 100 kg gross")
        self.assertEqual(self.rates["1902.1110"]["eu_rate"], "CHF 6.10 per 100 kg net mass")
        self.assertEqual(self.rates["1509.2091"]["eu_rate"], "CHF 49.70 per 100 kg gross")
        self.assertEqual(self.rates["0406.9039"]["eu_rate"], "CHF 0.00 per 100 kg gross")
        self.assertEqual(self.rates["2204.2149"]["normal_rate"], "CHF 2.45 per 1 litre")

    def test_red_wine_has_no_eu_preference(self):
        self.assertIn("no EU preference", self.rates["2204.2141"]["eu_rate"])

    def test_closed_rates_are_ignored(self):
        old = tw.ch_rates(open(FIX, "rb").read(), {"1902.1910"}, on=date(2026, 1, 15))
        self.assertNotEqual(old.get("1902.1910", {}).get("normal_rate"), "CHF 14.60 per 100 kg gross")

    def test_file_link_found_on_page(self):
        self.assertTrue(tw.ch_file_url(PAGE).endswith("duty_rates_chapter_01_to_30.xlsx"))
        self.assertIsNone(tw.ch_file_url("<a href='x.pdf'>"))

    def test_file_link_found_in_escaped_page_data(self):
        # Real BAZG raw HTML, 2026-11-02: the link only appears inside the page's JSON data block.
        raw = ('{"text":5526},"\\u003Cstrong>\\u003Ca href=\\\"https://www.bazg.admin.ch/dam/en/sd-web/'
               'suXEbuatJI1d/duty_rates_chapter_01_to_30.xlsx\\\" target=\\\"_self\\\"')
        self.assertEqual(tw.ch_file_url(raw),
                         "https://www.bazg.admin.ch/dam/en/sd-web/suXEbuatJI1d/duty_rates_chapter_01_to_30.xlsx")


def ca_text(ch):
    return open(os.path.join(os.path.dirname(__file__), "fixtures", f"ca_ch{ch}_2026.txt")).read()


class CanadaPdfTest(unittest.TestCase):
    """CBSA T2026 values read by hand from the chapter PDFs on 2 Nov 2026."""

    KNOWN = {
        "1902.19.21": ("Free", "Free"),
        "1902.19.22": ("Free", "Free"),
        "1902.19.23": ("16.27¢/kg", "Free"),
        "1902.11.10": ("4%", "Free"),
        "1902.11.29": ("16.27¢/kg plus 8.5%", "Free"),
        "1509.20.00": ("Free", "Free"),
        "2204.21.10": ("1.87¢/litre", "Free"),
        "2204.21.21": ("4.68¢/litre", "Free"),
        "0406.90.93": ("3.32¢/kg", "Free"),
        "0406.90.94": ("245.5% but not less than $5.08/kg", None),
    }

    def test_known_canadian_rates(self):
        for code, (mfn, ceta) in self.KNOWN.items():
            r = tw.ca_rates(ca_text(code[:2]), code)
            self.assertEqual(r["mfn_rate"], mfn, code)
            if ceta:
                self.assertEqual(r["ceta_rate"], ceta, code)
            else:
                self.assertIn("no CETA preference", r["ceta_rate"], code)

    def test_note_mentions_are_not_items(self):
        self.assertIsNone(tw.ca_rates("see tariff item No. 0406.90.11, or 0406.90.12", "0406.90.11"))

    def test_reads_the_real_pdf(self):
        pdf = open(os.path.join(os.path.dirname(__file__), "fixtures", "ca_ch15_2026.pdf"), "rb").read()
        vals, errs = tw.read_ca(None, [l for l in tw.LINES if l[0] == "CA:1509.20.00"],
                                get=lambda url, timeout=60, limit=0: pdf, year=2026)
        self.assertEqual(errs, {})
        self.assertEqual(vals["CA:1509.20.00"]["ceta_rate"], "Free")

    def test_falls_back_to_last_year(self):
        asked = []

        def get(url, timeout=60, limit=0):
            asked.append(url)
            if "/2027/" in url:
                raise OSError("404")
            return b"pdf"
        vals, errs = tw.read_ca(None, [l for l in tw.LINES if l[0] == "CA:1509.20.00"], get=get,
                                pdf_text=lambda b: ca_text("15"), year=2027)
        self.assertIn("CA:1509.20.00", vals)
        self.assertIn("/2026/", asked[-1])


class WeeklyRunTest(unittest.TestCase):
    def setUp(self):
        self.con = fresh()
        self.uk_val = {"eu_rate": "0.00%", "normal_rate": "6.00%", "vat": "0.00%"}
        self.readers = {
            "UK": lambda con, lines: ({l[0]: dict(self.uk_val) for l in lines}, {}),
            "US": lambda con, lines: ({}, {l[0]: "service down" for l in lines}),
            "CH": lambda con, lines: tw.read_ch(con, lines, get=fake_get),
            "CA": lambda con, lines: tw.read_ca(con, lines, get=lambda u, timeout=60, limit=0: u.encode(),
                                                pdf_text=lambda b: ca_text(b.decode().split("/ch")[-1][:2]), year=2026),
        }

    def opened(self, kind):
        return [c for c in jobs.changes(self.con) if c["kind"] == kind]

    def test_first_run_stores_values_without_change_flags(self):
        out = tw.run(self.con, self.readers)
        n_uk = len([l for l in tw.LINES if l[1] == "UK"])
        n_ch = len([l for l in tw.LINES if l[1] in ("CH", "CA")])
        self.assertEqual(out["read"], n_uk + n_ch)
        self.assertEqual(out["changed"], 0)
        self.assertEqual(len(self.opened("tariff_changed")), 0)

    def test_unreadable_lines_are_recorded(self):
        out = tw.run(self.con, self.readers)
        n_us = len([l for l in tw.LINES if l[1] == "US"])
        self.assertEqual(out["unreadable"], n_us)
        self.assertEqual(len(self.opened("tariff_unreadable")), n_us)

    def test_a_change_is_flagged_for_staff(self):
        tw.run(self.con, self.readers)
        self.uk_val["eu_rate"] = "2.00%"
        out = tw.run(self.con, self.readers)
        n_uk = len([l for l in tw.LINES if l[1] == "UK"])
        self.assertEqual(out["changed"], n_uk)
        ch = self.opened("tariff_changed")[0]
        self.assertEqual(ch["detail"]["before"]["eu_rate"], "0.00%")
        self.assertEqual(ch["detail"]["after"]["eu_rate"], "2.00%")

    def test_swiss_page_without_file_marks_all_swiss_lines(self):
        self.readers["CH"] = lambda con, lines: tw.read_ch(con, lines, get=lambda u, timeout=60, limit=0: b"<html></html>")
        tw.run(self.con, self.readers)
        refs = {c["ref"] for c in self.opened("tariff_unreadable")}
        self.assertTrue({l[0] for l in tw.LINES if l[1] == "CH"} <= refs)

    def test_runs_weekly(self):
        self.assertTrue(tw.due(self.con))
        tw.run(self.con, self.readers)
        self.assertFalse(tw.due(self.con))
        past = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        self.con.execute("UPDATE settings SET value=? WHERE key='tariff_watch_last'", (past,))
        self.assertTrue(tw.due(self.con))

    def test_snapshot_lists_every_line(self):
        tw.run(self.con, self.readers)
        snap = tw.snapshot(self.con)
        self.assertEqual(len(snap), len(tw.LINES))
        ch = next(s for s in snap if s["ref"] == "CH:1902.1910")
        self.assertEqual(ch["value"]["eu_rate"], "CHF 1.60 per 100 kg net mass")

    def test_offline_in_tests_records_unreadable_not_crash(self):
        out = tw.run(self.con)
        self.assertEqual(out["read"], 0)
        self.assertEqual(out["unreadable"], len(tw.LINES))


if __name__ == "__main__":
    unittest.main()
