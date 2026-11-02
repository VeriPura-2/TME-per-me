import unittest

from vialibera import docs, requirements as rq


def ids(cat, country, have=()):
    return [i["id"] for i in rq.required(cat, country, set(have))["data"]["items"]]


class RequirementsTest(unittest.TestCase):
    def test_all_20_wave1_lanes_are_covered(self):
        for cat in ("pasta", "wine", "olive oil", "cheese and dairy"):
            for country in ("UK", "USA", "Canada", "Germany", "France"):
                out = rq.required(cat, country, set())
                self.assertIsNotNone(out, (cat, country))
                self.assertFalse(out["simulated"])
                self.assertTrue(out["data"]["items"], (cat, country))

    def test_outside_wave1_is_not_covered(self):
        self.assertFalse(rq.covers("spirits", "UK"))
        self.assertFalse(rq.covers("wine", "Japan"))
        self.assertIsNone(rq.required("wine", "Japan", set()))

    def test_germany_is_intra_eu(self):
        got = ids("pasta", "Germany")
        for x in ("eori", "export_decl", "origin_stmt", "packing"):
            self.assertNotIn(x, got)
        self.assertIn("invoice_de", got)
        self.assertIn("lucid", got)

    def test_france_is_intra_eu_with_french_rules(self):
        got = ids("pasta", "France")
        for x in ("eori", "export_decl", "origin_stmt", "packing", "lucid", "label_de"):
            self.assertNotIn(x, got)
        for x in ("invoice_de", "vies", "label_fr", "triman", "fr_epr", "intrastat"):
            self.assertIn(x, got)
        self.assertNotIn("fr_excise", got)
        self.assertTrue(rq.covers("wine", "Francia"))

    def test_france_wine_excise_and_glass_exclusion(self):
        out = rq.required("wine", "France", set())["data"]["items"]
        got = [i["id"] for i in out]
        for x in ("fr_excise", "ead_de", "label_de_wine", "excise_auth"):
            self.assertIn(x, got)
        tri = [i for i in out if i["id"] == "triman"]
        self.assertEqual(len(tri), 1)
        self.assertIsNotNone(tri[0]["only_if"])
        self.assertTrue([i for i in out if i["id"] == "fr_excise"][0]["importer_side"])

    def test_reference_lanes(self):
        self.assertIn("uk_composite", ids("pasta", "UK"))
        self.assertIn("fda_ffr", ids("olive oil", "USA"))
        ca = ids("cheese and dairy", "Canada")
        for x in ("gac_permit", "ca_zoo", "sfc", "origin_stmt"):
            self.assertIn(x, ca)

    def test_uk_wine_lists_vi1_as_not_needed(self):
        out = rq.required("wine", "UK", set())
        self.assertTrue(any("VI-1" in n["en"] for n in out["data"]["not_needed"]))

    def test_only_confidence_a_counts_as_verified(self):
        for i in rq.required("cheese and dairy", "UK", set())["data"]["items"]:
            self.assertEqual(i["verified"], i["confidence"] == "A", i["id"])

    def test_on_file_match_uses_document_types(self):
        out = rq.required("pasta", "USA", {"invoice"})
        inv = [i for i in out["data"]["items"] if i["id"] == "invoice"][0]
        self.assertTrue(inv["on_file"])

    def test_doc_types_exist_and_sources_are_urls(self):
        for r in rq.ROWS:
            if r["doc_type"]:
                self.assertIn(r["doc_type"], docs.TYPE_IDS, r["id"])
            if r["source"]:
                self.assertTrue(r["source"].startswith("https://"), r["id"])
            self.assertIn(r["conf"], ("A", "B", "C"))
            self.assertIn(r["who"], rq.WHO)

    def test_country_names_are_normalised(self):
        self.assertTrue(rq.covers("Wine", " usa "))
        self.assertTrue(rq.covers("cheese", "Regno Unito"))
