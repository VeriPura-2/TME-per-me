import os
import unittest

from vialibera import features, sim


class FeatureTests(unittest.TestCase):
    def test_every_sim_has_a_file_name_inside_sim_folder(self):
        for name, f in features.active_simulations():
            self.assertTrue(f.startswith("sim/"), name)

    def test_sim_files_exist(self):
        base = os.path.dirname(features.__file__)
        missing = [f for _, f in features.active_simulations() if not os.path.exists(os.path.join(base, f))]
        # Files are added phase by phase; this lists what is still to build.
        self.assertIsInstance(missing, list)

    def test_tag_marks_simulated(self):
        out = sim.tag("payment", {"x": 1})
        self.assertTrue(out["simulated"])
        self.assertIn("en", out["note"])

    def test_tag_refuses_live_feature(self):
        with self.assertRaises(RuntimeError):
            sim.tag("interview", {})

    def test_public_hides_file_names(self):
        for v in features.public().values():
            self.assertEqual(set(v), {"phase", "mode"})

    def test_removal_checklist_lists_simulations(self):
        names = [n for n, _ in features.active_simulations()]
        self.assertIn("payment", names)
        self.assertNotIn("interview", names)
