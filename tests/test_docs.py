import os
import tempfile
import unittest
from types import SimpleNamespace as NS

os.environ["DB_PATH"] = ":memory:"
os.environ["LOCAL_STORE"] = tempfile.mkdtemp()
from vialibera import accounts, app, db, docs, storage

PDF = b"%PDF-1.4 test"


def who(u):
    return {"user": u, "org": None, "roles": []}


class DocsTest(unittest.TestCase):
    def setUp(self):
        for u in ("d1", "d2"):
            accounts.record_consent(app.con(), u, app.TERMS_VERSION, "it", True)

    def test_upload_proposes_type_and_stores(self):
        code, out = docs.upload(app.con(), who("d1"), "Etichetta_Barolo_2020.pdf", PDF, product="Barolo")
        self.assertEqual((code, out["doc_type"], out["status"]), (200, "label", "proposed"))
        row = docs.get_doc(app.con(), out["id"], who("d1"))
        self.assertEqual(storage.store().get(row["store_key"]), PDF)

    def test_company_level_types_drop_product(self):
        _, out = docs.upload(app.con(), who("d1"), "visura camerale.pdf", PDF + b"1", product="Barolo")
        self.assertIsNone(docs.get_doc(app.con(), out["id"], who("d1"))["product"])

    def test_rejections(self):
        self.assertEqual(docs.upload(app.con(), who("d1"), "x.exe", b"MZ")[0], 400)
        self.assertEqual(docs.upload(app.con(), who("d1"), "x.pdf", b"not a pdf")[0], 400)
        self.assertEqual(docs.upload(app.con(), who("d1"), "x.pdf", b"")[0], 400)
        self.assertEqual(docs.upload(app.con(), who("d1"), "x.pdf", PDF + b"0" * (docs.MAX_BYTES + 1))[0], 400)

    def test_duplicate_detected(self):
        docs.upload(app.con(), who("d1"), "a.pdf", PDF + b"dup")
        _, out = docs.upload(app.con(), who("d1"), "b.pdf", PDF + b"dup")
        self.assertTrue(out.get("duplicate"))

    def test_privacy_between_users_and_confirm(self):
        _, out = docs.upload(app.con(), who("d1"), "analisi.pdf", PDF + b"priv")
        self.assertIsNone(docs.get_doc(app.con(), out["id"], who("d2")))
        self.assertEqual(app.handle_doc_update(out["id"], {"confirm": True, "product": "Pasta"}, who("d2"))[0], 404)
        c, r = app.handle_doc_update(out["id"], {"confirm": True, "product": "Pasta", "doc_type": "lab_analysis"}, who("d1"))
        self.assertEqual((c, r["status"], r["product"]), (200, "confirmed", "Pasta"))

    def test_project_link_and_listing(self):
        w = who("d1")
        cid = db.create_case(app.con(), 1, owner_sub="d1")
        _, out = docs.upload(app.con(), w, "fattura.pdf", PDF + b"inv")
        self.assertTrue(docs.link(app.con(), w, cid, out["id"]))
        self.assertEqual(len(docs.listing(app.con(), w, case_id=cid)), 1)
        self.assertFalse(docs.link(app.con(), who("d2"), cid, out["id"]))

    def test_documents_move_to_company_library(self):
        w = who("d9")
        accounts.record_consent(app.con(), "d9", app.TERMS_VERSION, "it", True)
        _, out = docs.upload(app.con(), w, "label.pdf", PDF + b"co")
        cid = db.create_case(app.con(), 1, owner_sub="d9")
        db.case_write(app.con(), cid, "company", {"vat_number": "IT10000000009", "legal_name": "X"})
        accounts.attach_company(app.con(), cid, w)
        row = docs.get_doc(app.con(), out["id"], w)
        self.assertIsNotNone(row["company_id"])


if __name__ == "__main__":
    unittest.main()


class SummaryTest(unittest.TestCase):
    def test_summary_lists_names_not_contents(self):
        accounts.record_consent(app.con(), "s1", app.TERMS_VERSION, "it", True)
        w = who("s1")
        cid = db.create_case(app.con(), 1, owner_sub="s1")
        _, out = docs.upload(app.con(), w, "etichetta_barolo.pdf", PDF + b"summ", product="Barolo")
        docs.link(app.con(), w, cid, out["id"])
        t = docs.summary_for_case(app.con(), cid)
        self.assertIn("etichetta_barolo.pdf", t)
        self.assertIn("in this project", t)
        self.assertNotIn("%PDF", t)
