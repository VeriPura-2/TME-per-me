import os
import unittest
from types import SimpleNamespace as NS

os.environ["DB_PATH"] = ":memory:"
from vialibera import accounts, app, db


class Fake:
    messages = NS(create=lambda **kw: NS(content=[NS(type="text", text="ok", model_dump=lambda: {"type": "text", "text": "ok"})]))


def who(u):
    return {"user": u, "org": None, "roles": []}


class AccountsTest(unittest.TestCase):
    def test_vat_checksum(self):
        self.assertEqual(accounts.normalise_vat("IT 00743110157")[0], "IT00743110157")
        self.assertEqual(accounts.normalise_vat("00743110157")[0], "IT00743110157")
        self.assertIsNotNone(accounts.normalise_vat("00743110158")[1])
        self.assertIsNone(accounts.normalise_vat("DE123456789")[1])
        self.assertIsNotNone(accounts.normalise_vat("hello")[1])

    def test_consent_required_then_ok(self):
        w = who("c1")
        self.assertEqual(app.handle_chat({"message": "hi"}, llm=Fake(), who=w)[0], 403)
        self.assertEqual(app.handle_consent({"accept_terms": True}, w)[0], 400)
        self.assertEqual(app.handle_consent({"accept_terms": True, "accept_onerous": True}, w)[0], 200)
        self.assertEqual(app.handle_chat({"message": "hi"}, llm=Fake(), who=w)[0], 200)

    def test_vat_creates_company_then_second_user_must_request_access(self):
        a, b = who("a1"), who("b1")
        for w in (a, b):
            accounts.record_consent(app.con(), w["user"], app.TERMS_VERSION, "it", True)
        _, out = app.handle_chat({"message": "hi"}, llm=Fake(), who=a)
        db.case_write(app.con(), out["case_id"], "company", {"vat_number": "IT00743110157", "legal_name": "Alba SRL"})
        n = accounts.attach_company(app.con(), out["case_id"], a)
        self.assertEqual(n["status"], "created")
        _, out2 = app.handle_chat({"message": "hi"}, llm=Fake(), who=b)
        db.case_write(app.con(), out2["case_id"], "company", {"vat_number": "00743110157"})
        n2 = accounts.attach_company(app.con(), out2["case_id"], b)
        self.assertEqual(n2["status"], "access_requested")
        row = app.con().execute("SELECT company_id FROM cases WHERE id=?", (out2["case_id"],)).fetchone()
        self.assertIsNone(row["company_id"])  # not attached until approved
        self.assertEqual(app.handle_chat({"message": "x", "case_id": out["case_id"]}, llm=Fake(), who=b)[0], 404)

    def test_invalid_vat_does_not_create(self):
        a = who("z1")
        accounts.record_consent(app.con(), "z1", app.TERMS_VERSION, "it", True)
        _, out = app.handle_chat({"message": "hi"}, llm=Fake(), who=a)
        db.case_write(app.con(), out["case_id"], "company", {"vat_number": "123"})
        self.assertEqual(accounts.attach_company(app.con(), out["case_id"], a)["status"], "invalid_vat")


if __name__ == "__main__":
    unittest.main()
