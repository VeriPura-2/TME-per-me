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


class EligibilityCheck(unittest.TestCase):
    """F1: a rule fires only on a sourced fact; unknown or unsure always gives 'check with the funder'."""

    def by(self, profile):
        from vialibera import funding_check
        return {x["id"]: x for x in funding_check.results(profile)}

    def test_farming_is_not_eligible_for_simest_and_reason_is_sourced(self):
        r = self.by({"size": "small", "region": "Veneto", "activity": "farming", "applicant": "company", "cofund": "yes"})["simest_tm"]
        self.assertEqual(r["result"], "no")
        self.assertIn("primary agricultural production", r["reasons"][0]["en"])

    def test_a_processor_that_answered_everything_is_likely_for_simest(self):
        r = self.by({"size": "small", "region": "Veneto", "activity": "processing", "applicant": "company", "cofund": "yes"})["simest_tm"]
        self.assertEqual((r["result"], r["reasons"]), ("likely", []))

    def test_region_and_area_rules(self):
        res = self.by({"size": "micro", "region": "Lombardy", "activity": "processing", "applicant": "company", "cofund": "yes"})
        self.assertEqual(res["er_intl_2026"]["result"], "no")
        self.assertEqual(res["lo_export_su_misura_2026"]["result"], "likely")
        vr = self.by({"size": "micro", "region": "Veneto", "activity": "processing", "applicant": "company", "cofund": "yes"})["vr_intl_2026"]
        self.assertEqual(vr["result"], "check")
        self.assertIn("provincia di Verona", vr["reasons"][0]["it"])

    def test_large_companies_are_not_eligible_for_sme_only_calls(self):
        res = self.by({"size": "large", "region": "Emilia-Romagna", "activity": "processing", "applicant": "company", "cofund": "yes"})
        self.assertEqual(res["er_digital_export_2026"]["result"], "no")
        self.assertEqual(res["simest_tm"]["result"], "likely")

    def test_unsure_answers_and_cofunding_give_check_never_no(self):
        res = self.by({"size": "not_sure", "region": "Emilia-Romagna", "activity": "not_sure", "applicant": "not_sure", "cofund": "no"})
        self.assertEqual(res["er_intl_2026"]["result"], "check")
        self.assertTrue(any("50% (55% with premium)" in w["en"] for w in res["er_intl_2026"]["reasons"]))

    def test_tuscany_and_the_brochure_are_always_check(self):
        res = self.by({"size": "small", "region": "Tuscany", "activity": "processing", "applicant": "company", "cofund": "yes"})
        self.assertEqual(res["to_intl_2026"]["result"], "check")
        self.assertEqual(res["aa_brochure_2026"]["result"], "no")  # Piedmont only
        pie = self.by({"size": "small", "region": "Piedmont", "activity": "processing", "applicant": "company", "cofund": "yes"})
        self.assertEqual(pie["aa_brochure_2026"]["result"], "check")

    def test_open_schemes_come_first_and_may_fit_counts_them(self):
        from vialibera import funding_check
        p = {"size": "small", "region": "Tuscany", "activity": "processing", "applicant": "company", "cofund": "yes"}
        out = funding_check.results(p)
        self.assertEqual(out[0]["status"], "open")
        self.assertEqual(funding_check.may_fit(p), 2)  # Tuscany (check) and SIMEST (likely)

    def test_endpoint_saves_per_company_and_ignores_bad_values(self):
        from test_start_form import user
        who = user("fund-f1")
        code, out = app.handle_start({"category": "wine", "country": "USA"}, who)
        cid = out["case_id"]
        code, j = app.handle_tools("/tools/funding_check", {"case_id": cid}, who)
        self.assertEqual((code, j["profile"], j["destination"]), (200, None, "USA"))
        code, j = app.handle_tools("/tools/funding_profile", {"case_id": cid, "answers": {"size": "huge", "region": "Veneto", "activity": "processing"}}, who)
        self.assertEqual((j["profile"]["size"], j["profile"]["region"]), (None, "Veneto"))
        self.assertEqual(len(j["results"]), len(funding.schemes()))
        self.assertEqual(app.handle_tools("/tools/funding_check", {"case_id": cid}, user("someone-else"))[0], 404)


class DeadlinesAndAlerts(unittest.TestCase):
    """F2: deadline list (micro firms see the share the scheme pays first) and at-most-once email alerts."""
    P = {"size": "small", "region": "Tuscany", "activity": "processing", "applicant": "company", "cofund": "yes"}

    def setUp(self):
        self.c = app.con()
        for t in ("funding_alerts", "funding_alerts_sent", "funding_seen", "funding_profiles"):
            self.c.execute(f"DELETE FROM {t}")
        self.c.commit()

    def test_deadline_list_open_first_then_no_window(self):
        from vialibera import funding_check
        d = funding_check.deadlines(self.P, today=date(2026, 11, 22))
        self.assertEqual([x["id"] for x in d], ["to_intl_2026", "simest_tm"])
        self.assertEqual(d[0]["deadline"], "2026-12-18")
        self.assertTrue(d[0]["share_unconfirmed"])
        self.assertFalse(d[1]["share_unconfirmed"])
        self.assertEqual([x["id"] for x in funding_check.deadlines(self.P, today=date(2026, 12, 19))], ["simest_tm"])  # past deadline

    def test_micro_firms_see_the_sourced_share_first(self):
        from vialibera import funding_check
        d = funding_check.deadlines(dict(self.P, size="micro"), today=date(2026, 11, 22))
        self.assertEqual([x["id"] for x in d], ["simest_tm", "to_intl_2026"])

    def test_alerts_need_an_email_and_go_out_once(self):
        from vialibera import funding_check
        who = {"user": "fa1"}
        self.assertEqual(funding_check.set_alerts(self.c, "co-1", who, True, "", "en")[0], 400)
        self.assertEqual(funding_check.set_alerts(self.c, "co-1", who, True, "a@b.example", "en")[0], 200)
        funding_check.save_profile(self.c, "co-1", who, self.P)
        sent = []
        send = lambda to, subj, body: sent.append((to, subj, body)) or True
        self.assertEqual(funding_check.send_alerts(self.c, "https://app.example", send, today=date(2026, 11, 22))["funding_emails"], 0)
        funding_check.send_alerts(self.c, "https://app.example", send, today=date(2026, 12, 5))   # 13 days before 18 Dec
        funding_check.send_alerts(self.c, "https://app.example", send, today=date(2026, 12, 6))   # same window: not again
        funding_check.send_alerts(self.c, "https://app.example", send, today=date(2026, 12, 16))  # 2 days before
        self.assertEqual([s[1] for s in sent], ["Tuscany: internationalisation call 2026 closes on 2026-12-18"] * 2)
        self.assertIn("check with the funder", sent[0][2])
        self.assertIn("https://www.regione.toscana.it/bandi-aperti", sent[0][2])
        self.assertNotIn(EM_DASH, sent[0][2])

    def test_an_email_when_staff_change_a_fitting_scheme_to_open(self):
        from vialibera import funding_check
        who = {"user": "fa2"}
        funding_check.set_alerts(self.c, "co-2", who, True, "x@y.example", "it")
        funding_check.save_profile(self.c, "co-2", who, self.P)
        sent = []
        send = lambda to, subj, body: sent.append(subj) or True
        self.c.execute("INSERT INTO funding_seen(scheme_id, status, seen_at) VALUES ('to_intl_2026','check','x')")
        funding_check.send_alerts(self.c, "https://app.example", send, today=date(2026, 11, 22))
        self.assertEqual(sent, ["Toscana: bando internazionalizzazione 2026 è aperto"])
        funding_check.send_alerts(self.c, "https://app.example", send, today=date(2026, 11, 23))
        self.assertEqual(len(sent), 1)

    def test_switching_off_stops_emails(self):
        from vialibera import funding_check
        who = {"user": "fa3"}
        funding_check.set_alerts(self.c, "co-3", who, True, "x@y.example", "en")
        funding_check.set_alerts(self.c, "co-3", who, False, None, "en")
        self.assertFalse(funding_check.get_alerts(self.c, "co-3")["on"])
