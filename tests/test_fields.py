import unittest
from vialibera import fields


def case(**kw):
    c = {"company": {}, "product": {}, "market": {}}
    for k, v in kw.items():
        sec, key = k.split("__")
        c[sec][key] = v
    return c


class FieldsTest(unittest.TestCase):
    def test_first_missing_is_company_name(self):
        a, t, m, u = fields.status(case())
        self.assertEqual((a, m[0][1]), (0, "legal_name"))

    def test_category_extras_appear_only_when_known(self):
        base = fields.status(case())[1]
        wine = fields.status(case(product__category="Wine"))[1]
        pasta = fields.status(case(product__category="pasta"))[1]
        self.assertGreater(wine, base)
        self.assertNotEqual(wine, pasta)
        self.assertIn("abv", [k for _, k, _, _ in fields.applicable(case(product__category="wine"))])
        self.assertNotIn("abv", [k for _, k, _, _ in fields.applicable(case(product__category="pasta"))])

    def test_unknown_counts_but_flagged(self):
        a, t, m, u = fields.status(case(company__vat_number="unknown"))
        self.assertEqual((a, u), (1, ["vat_number"]))

    def test_complete(self):
        c = case()
        for sec, key, *_ in fields.applicable(c):
            c[sec][key] = "x"
        self.assertIn("complete", fields.prompt_note(c))


if __name__ == "__main__":
    unittest.main()
