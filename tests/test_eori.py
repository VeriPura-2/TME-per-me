import os
import unittest

os.environ["DB_PATH"] = ":memory:"
from vialibera import app, db, eori
from test_journey import who


def case(u):
    c = app.con()
    cid = db.create_case(c, 1, owner_sub=u)
    db.case_write(c, cid, "company", {"legal_name": "Rossi Vini Srl", "vat_number": "IT01234567890",
                                       "contact": "Mario Rossi, mario@rossi.it, +39 011 123456"})
    c.commit()
    return cid


class EoriTest(unittest.TestCase):
    def test_prefill_from_case_and_missing_listed(self):
        cid = case("e1")
        code, out = app.handle_eori({"case_id": cid, "lang": "en"}, who("e1"))
        self.assertEqual(code, 200)
        v = {f["key"]: f["value"] for f in out["fields"]}
        self.assertEqual(v["name"], "Rossi Vini Srl")
        self.assertEqual(v["piva"], "01234567890")
        self.assertEqual(v["c_email"], "mario@rossi.it")
        self.assertEqual((v["c_name"], v["c_surname"]), ("Mario", "Rossi"))
        self.assertIn("office", out["missing"])
        self.assertIn("legal_form", out["missing"])
        self.assertNotIn("name", out["missing"])
        self.assertIn("does not file or sign", out["note"])

    def test_pdf_is_filled_saved_and_unsigned(self):
        cid = case("e2")
        code, pdf = app.handle_eori_pdf({"case_id": cid, "values": {"office": "Torino", "legal_form": "company", "city": "Alba"}}, who("e2"))
        self.assertEqual(code, 200)
        self.assertTrue(pdf.startswith(b"%PDF"))
        from pypdf import PdfReader
        import io
        txt = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
        self.assertIn("Rossi Vini Srl", txt)
        self.assertIn("Torino", txt)
        self.assertIn("Alba", txt)
        again = app.handle_eori({"case_id": cid}, who("e2"))[1]
        self.assertEqual({f["key"]: f["value"] for f in again["fields"]}["office"], "Torino")
        self.assertEqual(again["legal_form"], "company")

    def test_other_users_cannot_read_the_case(self):
        cid = case("e3")
        self.assertEqual(app.handle_eori({"case_id": cid}, who("intruder"))[0], 404)
