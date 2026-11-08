import unittest

from vialibera import plans, features
from vialibera import plan_prices


class PlanTests(unittest.TestCase):
    def test_exporters_see_three_plans_italian_names(self):
        self.assertEqual([p["name"]["it"] for p in plans.public()["plans"].values()], ["Esplora", "Parti", "Cresci"])
        self.assertIn("tem", plans.PLANS)
        self.assertNotIn("tem", plans.public()["plans"])

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

    def test_price_menu_matches_the_decisions_of_8_nov(self):
        m = plan_prices.MENU
        self.assertEqual([m[k]["monthly"] for k in ("esplora", "parti", "cresci", "tem")], [0, 25000, 75000, 100000])
        self.assertEqual([m[k]["levels"][2] for k in ("parti", "cresci", "tem")], [2900, 2900, 2900])
        self.assertEqual([m[k]["levels"][3] for k in ("parti", "cresci", "tem")], [9900, 7900, 7900])

    def test_explore_cannot_buy_checks(self):
        self.assertIsNone(plan_prices.MENU["esplora"]["levels"][2])
        self.assertIsNone(plan_prices.MENU["esplora"]["levels"][3])

    def test_every_plan_has_a_price(self):
        self.assertEqual(set(plan_prices.MENU), set(plans.PLANS))

    def test_price_menu_is_live_not_simulated(self):
        self.assertNotIn("price_menu", dict(features.active_simulations()))


if __name__ == "__main__":
    unittest.main()
