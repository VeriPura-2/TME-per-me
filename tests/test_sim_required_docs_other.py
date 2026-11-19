import unittest

from vialibera.sim import required_docs


def ids(category):
    return {i["id"] for i in required_docs.required(category, set())["data"]["items"]}


class OtherProductList(unittest.TestCase):
    def test_unknown_product_has_no_food_only_rows(self):
        for cat in ("other", "", None, "organic cosmetics"):
            got = ids(cat)
            self.assertFalse({"facility", "haccp", "lab"} & got, cat)
            self.assertTrue({"registration", "tax_ids", "invoice", "packing", "customs"} <= got, cat)

    def test_known_food_categories_keep_the_full_draft_list(self):
        for cat in ("pasta", "wine", "olive oil", "cheese and dairy", "spirits", "cured meat", "preserves", "bakery"):
            self.assertTrue({"facility", "haccp", "lab"} <= ids(cat), cat)

    def test_list_stays_marked_simulated(self):
        self.assertTrue(required_docs.required("other", set()).get("simulated"))


if __name__ == "__main__":
    unittest.main()
