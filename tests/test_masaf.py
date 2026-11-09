"""MASAF control-body table: the JSON the app reads, and the parser that builds it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from vialibera import masaf  # noqa: E402

SRC = os.path.join(os.path.dirname(masaf.__file__), "data", "masaf_source")


class Table(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = masaf.load()

    def test_refresh_date_and_disclaimer(self):
        self.assertRegex(self.d["refreshed"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn("not proof", self.d["note"])

    def test_known_food_names_map_to_their_bodies(self):
        want = {"Parmigiano Reggiano": "ocqpr", "Grana Padano": "csqa", "Pecorino Romano": "ifcq",
                "Gorgonzola": "csqa", "Aceto Balsamico di Modena": "csqa", "Prosciutto di Parma": "csqa",
                "Toscano": "tca"}
        for name, body in want.items():
            self.assertEqual({r["body_id"] for r in masaf.lookup(name, self.d)}, {body}, name)

    def test_wine_denominations(self):
        self.assertEqual({r["body_id"] for r in masaf.lookup("Brachetto d'Acqui", self.d)}, {"valoritalia"})
        self.assertEqual({r["body_id"] for r in masaf.lookup("Chianti Classico", self.d)}, {"valoritalia"})

    def test_lookup_ignores_case_and_accents(self):
        self.assertTrue(masaf.lookup("PARMIGIANO reggiano", self.d))
        self.assertTrue(masaf.lookup("Valtellina Casera", self.d))

    def test_unknown_name_gives_empty_list(self):
        self.assertEqual(masaf.lookup("Formaggio Inventato", self.d), [])

    def test_every_body_in_rows_has_a_contact_record_or_is_unnamed(self):
        # wine-only bodies (Siquria, Triveneta, the Bolzano and Trento chambers) are not in the contact PDFs
        wine_only = {"siquria", "triveneta", "cciaa-bolzano", "cciaa-trento"}
        for r in self.d["rows"]:
            if r["body_id"] and r["body_id"] not in wine_only:
                self.assertIn(r["body_id"], self.d["bodies"], r)

    def test_rows_without_a_body_are_only_the_two_unnamed_ones(self):
        no_body = [r["denomination"] for r in self.d["rows"] if not r["body_id"]]
        self.assertEqual(sorted(no_body), ["Coppia Ferrarese", "Tergeste"])

    def test_counts_match_the_published_lists(self):
        food = [r for r in self.d["rows"] if r["sector"] == "food" and r["category"] in ("D.O.P.", "I.G.P.")]
        wine = [r for r in self.d["rows"] if r["sector"] == "wine"]
        stg = [r for r in self.d["rows"] if r["category"] == "STG"]
        self.assertEqual(len(food), 330)
        self.assertEqual(len(wine), 533)
        self.assertEqual(len(stg), 27)
        self.assertEqual(len(self.d["bodies"]), 34)
        self.assertEqual(self.d["bodies"]["valoritalia"]["pec"], "amministrazione@pec.valoritalia.it; biologico@pec.valoritalia.it")

    def test_contacts_are_present_for_main_bodies(self):
        b = self.d["bodies"]
        self.assertEqual(b["ocqpr"]["email"], "ocqpr@ocqpr.it")
        self.assertEqual(b["csqa"]["email"], "csqa@csqa.it")
        self.assertEqual(b["ifcq"]["email"], "info@ifcq.it")


class Parser(unittest.TestCase):
    def setUp(self):
        try:
            import pdfplumber  # noqa: F401
        except ImportError:
            self.skipTest("pdfplumber not installed (only needed to refresh the data)")
        if not os.path.isdir(SRC):
            self.skipTest("source PDFs not present")

    def test_rebuild_matches_the_stored_table(self):
        d = masaf.build(SRC, "2000-01-01")
        stored = masaf.load()
        self.assertEqual(d["rows"], stored["rows"])
        self.assertEqual(d["bodies"], stored["bodies"])

    def test_body_ids(self):
        self.assertEqual(masaf.body_id("OCQ PR ORGANISMO CONTROLLO QUALITA' PRODUZIONI REGOLAMENTATE SOC COOP"), "ocqpr")
        self.assertEqual(masaf.body_id("V a l o r i t a l i a S r l"), "valoritalia")
        self.assertIsNone(masaf.body_id(None))


if __name__ == "__main__":
    unittest.main()
