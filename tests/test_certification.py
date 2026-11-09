"""Certification questions: fields, the claimed-only guard, the control_body tool. Offline, no AI calls."""
import unittest

from vialibera import agent, db, fields, masaf


def case(**kw):
    c = {"company": {}, "product": {}, "market": {}}
    for k, v in kw.items():
        sec, key = k.split("__")
        c[sec][key] = v
    return c


class CertFieldsTest(unittest.TestCase):
    def test_no_follow_up_without_a_protected_name(self):
        self.assertEqual(fields.cert_note(case(company__certifications="BRC, none")), "")
        self.assertNotIn("CERTIFICATION", fields.prompt_note(case()))

    def test_follow_up_asks_the_name_first(self):
        note = fields.cert_note(case(company__certifications="DOP/DOCG/IGP"))
        self.assertIn("product.denomination", note)
        self.assertNotIn("control_body", note)

    def test_follow_up_then_uses_the_tool_and_asks_for_the_upload(self):
        note = fields.cert_note(case(company__certifications="DOP", product__denomination="Parmigiano Reggiano"))
        for word in ("call control_body", "cert_control_body", "Documents button", "cert_status=claimed", "not proof"):
            self.assertIn(word, note)

    def test_follow_up_stops_once_claimed_with_a_body(self):
        c = case(company__certifications="DOP", product__denomination="Pecorino Romano",
                 company__cert_status="claimed", company__cert_control_body="IFCQ")
        self.assertEqual(fields.cert_note(c), "")

    def test_wine_appellation_counts(self):
        self.assertTrue(fields.mentions_protected_name(case(product__appellation="Barolo DOCG")))

    def test_agent_may_only_record_claimed(self):
        for status in (fields.CERT_UPLOADED, fields.CERT_CONFIRMED, "verified"):
            ok, err = fields.check_write("company", {"cert_status": status, "cert_control_body": "IFCQ"})
            self.assertNotIn("cert_status", ok)
            self.assertEqual(ok["cert_control_body"], "IFCQ")
            self.assertIn("claimed", err)
        ok, err = fields.check_write("company", {"cert_status": "Claimed"})
        self.assertEqual((ok, err), ({"cert_status": "Claimed"}, None))

    def test_new_keys_are_in_the_field_guide_but_not_required(self):
        guide = fields.field_guide()
        for key in ("product.denomination", "company.cert_control_body", "company.cert_status"):
            self.assertIn(key, guide)
        keys = [k for _, k, _, _ in fields.applicable(case())]
        self.assertNotIn("cert_status", keys)
        self.assertNotIn("denomination", keys)


class ControlBodyToolTest(unittest.TestCase):
    def test_known_names_name_their_body_with_date_and_disclaimer(self):
        r = masaf.describe("Parmigiano Reggiano")
        self.assertIn("OCQ PR", r["found"][0]["control_body"])
        self.assertIn("not proof", r["note"])
        self.assertTrue(r["refreshed"])
        self.assertIn("Valoritalia", masaf.describe("Barolo")["found"][0]["control_body"])

    def test_unknown_name_is_empty_not_guessed(self):
        self.assertEqual(masaf.describe("Zzz Not A Cheese")["found"], [])

    def test_tool_runs_through_the_agent_and_saves_nothing(self):
        con = db.connect()
        cid = db.create_case(con, 1)
        before = db.case_read(con, cid)
        out = agent.run_tool(con, cid, {}, "control_body", {"denomination": "Grana Padano"})
        self.assertIn("CSQA", out["found"][0]["control_body"])
        self.assertEqual(db.case_read(con, cid), before)

    def test_tool_is_offered_to_the_ai(self):
        self.assertIn("control_body", [t["name"] for t in agent.TOOLS])


if __name__ == "__main__":
    unittest.main()
