import unittest

from vialibera import plans, features
from vialibera.sim import prices


class PlanTests(unittest.TestCase):
    def test_three_plans_italian_names(self):
        self.assertEqual([p["name"]["it"] for p in plans.PLANS.values()], ["Esplora", "Parti", "Cresci"])

    def test_free_plan_has_one_project(self):
        self.assertTrue(plans.can_add_project("esplora", 0))
        self.assertFalse(plans.can_add_project("esplora", 1))
        self.assertTrue(plans.can_add_project("cresci", 999))

    def test_unknown_plan_falls_back_to_free(self):
        self.assertEqual(plans.get("nope")["rank"], 0)

    def test_every_sim_item_has_a_level(self):
        for item in ("tariff_lookup", "document_check", "lab_cert"):
            self.assertIn(plans.level_of(item), (1, 2, 3))

    def test_plans_hold_no_money(self):
        for p in plans.PLANS.values():
            self.assertFalse(any("price" in k or "eur" in k for k in p))

    def test_example_prices_are_labelled_simulated(self):
        out = prices.prices()
        self.assertTrue(out["simulated"])
        self.assertIn("price_menu", dict(features.active_simulations()))

    def test_paid_levels_get_cheaper_on_higher_plans(self):
        e = prices.EXAMPLE
        self.assertLess(e["cresci"]["levels"][2], e["parti"]["levels"][2])
        self.assertLess(e["parti"]["levels"][2], e["esplora"]["levels"][2])


if __name__ == "__main__":
    unittest.main()
