import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("LOCAL_STORE", tempfile.mkdtemp())
from vialibera import accounts, db, jobs, requirements, tems, vat_check
from vialibera.adapters.tariff import UKTradeTariff, USITCHts

FX = os.path.join(os.path.dirname(__file__), "fixtures")
VALID = json.dumps({"isValid": True, "userError": "VALID", "name": "ALFA S.R.L.", "address": "VIA ROMA 1 \n12051 ALBA CN\n"})
NOT_IN = json.dumps({"isValid": False, "userError": "INVALID", "name": "---", "address": "---"})
DOWN = json.dumps({"isValid": False, "userError": "MS_UNAVAILABLE"})


def load(name):
    with open(os.path.join(FX, name)) as f:
        return f.read()


class Vat(unittest.TestCase):
    def setUp(self):
        self.con = db.connect()

    def test_italian_only(self):
        self.assertEqual(vat_check.italian("01765920051"), ("IT01765920051", None))
        self.assertIsNotNone(vat_check.italian("DE123456789")[1])
        self.assertIsNotNone(vat_check.italian("IT01765920052")[1])  # check digit

    def test_vies_states(self):
        v = vat_check.vies("IT01765920051", http=lambda u: VALID)
        self.assertEqual((v["state"], v["name"], v["address"]), ("valid", "ALFA S.R.L.", "VIA ROMA 1 12051 ALBA CN"))
        self.assertEqual(vat_check.vies("IT01765920051", http=lambda u: NOT_IN)["state"], "not_in_vies")
        self.assertEqual(vat_check.vies("IT01765920051", http=lambda u: DOWN)["state"], "unavailable")
        self.assertEqual(vat_check.vies("IT01765920051")["state"], "unavailable")  # network off in tests

    def test_valid_marks_company_verified_not_in_vies_does_not_block(self):
        self.con.execute("INSERT INTO companies(id, vat, legal_name, created_at) VALUES ('c1','IT01765920051','A',?)", (db.now(),))
        vat_check.check_company(self.con, "c1", http=lambda u: NOT_IN)
        r = self.con.execute("SELECT status, vies_state FROM companies WHERE id='c1'").fetchone()
        self.assertEqual((r["status"], r["vies_state"]), ("unverified", "not_in_vies"))
        vat_check.check_company(self.con, "c1", http=lambda u: VALID)
        r = self.con.execute("SELECT status, vies_name FROM companies WHERE id='c1'").fetchone()
        self.assertEqual((r["status"], r["vies_name"]), ("verified", "ALFA S.R.L."))

    def test_chat_refuses_foreign_vat(self):
        cid = db.create_case(self.con, 1, owner_sub="u1")
        db.case_write(self.con, cid, "company", {"vat_number": "DE123456789", "legal_name": "X"})
        out = accounts.attach_company(self.con, cid, {"user": "u1", "org": None, "roles": []})
        self.assertEqual(out["status"], "invalid_vat")

    def test_germany_lane_lists_vies_and_ticks_it_when_confirmed(self):
        self.con.execute("INSERT INTO companies(id, vat, legal_name, created_at, vies_state) VALUES ('c2','IT01765920051','A',?,'valid')", (db.now(),))
        req = requirements.required("pasta", "Germany", set())
        self.assertIn("vies", [i["id"] for i in req["data"]["items"]])
        vat_check.apply_to_checklist(self.con, "c2", req)
        self.assertTrue([i for i in req["data"]["items"] if i["id"] == "vies"][0]["on_file"])
        self.assertNotIn("vies", [i["id"] for i in requirements.required("pasta", "UK", set())["data"]["items"]])


class Daily(unittest.TestCase):
    def setUp(self):
        p = mock.patch("vialibera.tariff_watch.due", return_value=False)  # weekly tariff check: own tests
        p.start()
        self.addCleanup(p.stop)
        self.con = db.connect()
        self.uk = UKTradeTariff(http=lambda url: load("uk_1902199090.json"))
        self.us = USITCHts(http=lambda url: load("us_" + url.rsplit("=", 1)[1] + ".json"))
        self.pages = {u: "page " + u for u in jobs.source_urls()}

    def run_job(self, vies_http=None):
        return jobs.run_daily(self.con, uk=self.uk, us=self.us, fetch=lambda u: self.pages[u], vies_http=vies_http)

    def test_first_run_is_quiet_and_known_answers_pass(self):
        out = self.run_job()
        self.assertEqual(out["tariffs"]["known_answers"], "pass")
        self.assertEqual(out["sources"]["changed"], 0)
        self.assertEqual(jobs.changes(self.con), [])

    def test_known_answer_change_is_reported(self):
        self.run_job()
        changed = json.loads(load("us_1509.20.20.json")); changed[0]["general"] = "7¢/kg on contents and container"
        self.us = USITCHts(http=lambda url: json.dumps(changed) if "20.20" in url else load("us_1509.20.90.json"))
        out = self.run_job()
        self.assertEqual(out["tariffs"]["known_answers"], "fail")
        kinds = {c["kind"] for c in jobs.changes(self.con)}
        self.assertEqual(kinds, {"known_answer_failed"})  # lane duty changes: weekly check, see test_tariff_watch

    def test_source_change_sends_items_back_to_staff_until_reconfirmed(self):
        self.run_job()
        url = requirements.SRC["ca_rawcheese"]
        self.pages[url] = "the rules changed"
        out = self.run_job()
        self.assertEqual(out["sources"]["changed"], 1)
        req = requirements.required("cheese and dairy", "Canada", set())
        tems.apply_confirmations(self.con, "case1", req)
        jobs.apply_source_flags(self.con, "case1", req)
        item = [i for i in req["data"]["items"] if i["id"] == "ca_zoo"][0]
        self.assertFalse(item["verified"])
        self.assertTrue(item["source_changed"])
        # exporters and TEM firms do not see the flag: the row stays as it was
        seen = requirements.required("cheese and dairy", "Canada", set())
        before = [dict(i) for i in seen["data"]["items"]]
        jobs.apply_source_flags(self.con, "case1", seen, staff=False)
        self.assertEqual(seen["data"]["items"], before)
        self.assertNotIn("source_changed", [i for i in seen["data"]["items"] if i["id"] == "ca_zoo"][0])
        # a confirmation after the change clears it
        self.con.execute("INSERT INTO checklist_confirmations(case_id, item_id, confirmed_by, by_label, at) VALUES ('case1','ca_zoo','t','TEM','9999')")
        req = requirements.required("cheese and dairy", "Canada", set())
        tems.apply_confirmations(self.con, "case1", req)
        jobs.apply_source_flags(self.con, "case1", req)
        self.assertTrue([i for i in req["data"]["items"] if i["id"] == "ca_zoo"][0]["verified"])

    def test_unreachable_source_is_reported(self):
        def boom(u):
            raise OSError("down")
        out = jobs.run_daily(self.con, uk=self.uk, us=self.us, fetch=boom)
        self.assertEqual(out["sources"]["unreachable"], len(jobs.source_urls()))

    def test_vies_recheck_reports_newly_confirmed(self):
        self.con.execute("INSERT INTO companies(id, vat, legal_name, created_at, vies_state) VALUES ('c3','IT01765920051','A',?,'not_in_vies')", (db.now(),))
        self.run_job(vies_http=lambda u: VALID)
        self.assertIn("vies_rechecked", {c["kind"] for c in jobs.changes(self.con)})

    def test_each_part_runs_on_its_own(self):
        f = lambda u: self.pages[u]
        s = jobs.run_part(self.con, "sources", uk=self.uk, us=self.us, fetch=f)
        self.assertEqual(s["sources"]["changed"], 0)
        self.assertNotIn("vies", s)
        self.assertIn("companies_rechecked", jobs.run_part(self.con, "vies", vies_http=lambda u: VALID)["vies"])
        self.assertEqual(jobs.run_part(self.con, "tariffs")["tariff_watch"], "not due")
        with self.assertRaises(ValueError):
            jobs.run_part(self.con, "everything")

    def test_failing_part_does_not_stop_the_others(self):
        self.con.execute("INSERT INTO companies(id, vat, legal_name, created_at, vies_state) VALUES ('c4','IT01765920051','A',?,'not_in_vies')", (db.now(),))
        with mock.patch("vialibera.jobs.recheck_vies", side_effect=IndexError("tuple index out of range")):
            out = self.run_job()
        self.assertEqual(out["vies_error"], "IndexError")
        self.assertEqual(out["tariff_watch"], "not due")  # the part after the failure still ran
        self.assertIn("job_failed", {c["kind"] for c in jobs.changes(self.con)})

    def test_dismiss(self):
        self.run_job()
        jobs._change(self.con, "duty_changed", "x", "test")
        cid = jobs.changes(self.con)[0]["id"]
        jobs.dismiss(self.con, {"user": "admin"}, cid)
        self.assertEqual(jobs.changes(self.con), [])


class Watch(unittest.TestCase):
    def test_sources_are_fetched_in_parallel_and_failures_reported(self):
        con = db.connect()
        seen = []

        def fetch(u):
            seen.append(u)
            if "eur-lex" in u:
                raise OSError("down")
            return "page " + u
        out = jobs.check_sources(con, fetch)
        self.assertEqual(sorted(seen), jobs.source_urls())
        n = len([u for u in jobs.source_urls() if "eur-lex" in u])
        self.assertEqual(out["unreachable"], n)
        self.assertEqual(len([c for c in jobs.changes(con) if c["kind"] == "source_unreachable"]), n)

    def test_change_shows_the_lines_that_changed_and_keeps_only_the_latest_text(self):
        con = db.connect()
        url = jobs.source_urls()[0]
        pages = {u: "Title\nRule: 60 days\nFooter" for u in jobs.source_urls()}
        jobs.check_sources(con, lambda u: pages[u])
        pages[url] = "Title\nRule: 90 days\nFooter"
        out = jobs.check_sources(con, lambda u: pages[u])
        self.assertEqual(out["changed"], 1)
        d = [c for c in jobs.changes(con) if c["kind"] == "source_changed"][0]["detail"]
        self.assertEqual(d["removed"], ["Rule: 60 days"])
        self.assertEqual(d["added"], ["Rule: 90 days"])
        row = con.execute("SELECT page_text FROM source_snapshots WHERE url=?", (url,)).fetchone()
        self.assertEqual(row["page_text"], "Title\nRule: 90 days\nFooter")  # yesterday's text is gone
        self.assertEqual(con.execute("SELECT COUNT(*) AS n FROM source_snapshots").fetchone()["n"], len(jobs.source_urls()))

    def test_sources_stored_before_text_was_kept_start_quietly(self):
        con = db.connect()
        url = jobs.source_urls()[0]
        con.execute("INSERT INTO source_snapshots(url, sha256, checked_at) VALUES (?,?,?)", (url, "old-format-hash", db.now()))
        jobs.check_sources(con, lambda u: "text " + u)
        self.assertEqual([c for c in jobs.changes(con) if c["kind"] == "source_changed"], [])
        self.assertIsNotNone(con.execute("SELECT page_text FROM source_snapshots WHERE url=?", (url,)).fetchone()["page_text"])

    def test_diff_is_capped(self):
        d = jobs.text_diff("\n".join(f"a{i}" for i in range(100)), "\n".join(f"b{i}" for i in range(100)))
        self.assertEqual(len(d["removed"]) + len(d["added"]), jobs.DIFF_LINES)

    def test_page_text_keeps_one_line_per_block(self):
        t = jobs.page_text("<html><nav>menu</nav><h1>Rule</h1><p>Aged <b>60</b> days</p><li>one</li>"
                           "<p>Current to 2026-10-19</p><script>x()</script></html>")
        self.assertEqual(t.splitlines(), ["Rule", "Aged 60 days", "one", "Current to"])

    def test_pdf_bytes_leave_no_control_characters(self):
        # 3 Nov 2026: PDF sources put NUL characters in the stored text; Postgres refused them (ValueError)
        t = jobs.page_text(b"%PDF-1.4\x00\x01binary\x00 stream\x1f end".decode("utf-8", "replace"))
        self.assertFalse(any(ord(ch) < 32 and ch not in "\n" for ch in t))
        self.assertIn("binary", t)

    def test_importer_only_sources_are_not_watched(self):
        # importer-only rows are never shown to the exporter, so their sources are not checked either
        urls = jobs.source_urls()
        for k in ("usda_dairy", "gac_cheese", "lucid"):
            self.assertNotIn(requirements.SRC[k], urls, k)
            self.assertNotIn(requirements.WATCH.get(k, "-"), urls, k)
        self.assertIn(requirements.SRC["ca_rawcheese"], urls)
        self.assertIn(requirements.watch_url(requirements.SRC["fda_ffr"]), urls)
        self.assertIn(requirements.SRC["ttb"], urls)  # shared with COLA, which the exporter acts on
        self.assertIn(requirements.SRC["ca_label"], urls)  # Canadian label rules (exporter)
        self.assertIn(requirements.WATCH["eu_fic"], urls)  # EUR-Lex: the amendments page, not the original act
        self.assertNotIn(requirements.SRC["eu_fic"], urls)

class PgSql(unittest.TestCase):
    """Postgres treats % as a placeholder marker: literal % must be doubled (daily job IndexError, 2 Nov 2026)."""

    def test_literal_percent_is_escaped(self):
        from vialibera import db as _db
        self.assertEqual(_db.pg_sql("SELECT id FROM companies WHERE vat LIKE 'IT%' AND id=?"),
                         "SELECT id FROM companies WHERE vat LIKE 'IT%%' AND id=%s")

    def test_recheck_query_formats_without_error(self):
        # psycopg2 formats queries with Python % rules; this reproduces the IndexError without a database.
        from vialibera import db as _db
        sql = "SELECT id FROM companies WHERE vat LIKE 'IT%' AND (vies_state IS NULL)"
        with self.assertRaises((IndexError, ValueError, TypeError)):
            sql.replace("?", "%s") % ()
        self.assertEqual(_db.pg_sql(sql) % (), sql)
