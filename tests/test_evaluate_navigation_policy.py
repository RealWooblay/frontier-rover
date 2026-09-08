from pathlib import Path
import sys
import tempfile
import unittest


SIM_PATH = Path(__file__).parents[1] / "software" / "sim"
sys.path.insert(0, str(SIM_PATH))
from evaluate_navigation_policy import evaluate, summarize  # noqa: E402
from mlp_policy import TinyMLP  # noqa: E402


class EvaluateNavigationPolicyTest(unittest.TestCase):
    def test_summary_counts_outcomes(self):
        records = [
            {"success": True, "collisions": 0, "recoveries": 1, "elapsed_s": 2.0, "path_length_m": 1.0},
            {"success": False, "collisions": 2, "recoveries": 2, "elapsed_s": 4.0, "path_length_m": 3.0},
        ]
        result = summarize(records)
        self.assertEqual(result["successes"], 1)
        self.assertEqual(result["success_rate"], 0.5)
        self.assertEqual(result["collision_total"], 2)

    def test_evaluation_is_seeded_and_contains_both_policies(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "policy.npz"
            TinyMLP(seed=5).save(model_path)
            first = evaluate(model_path, 2, 4)
            second = evaluate(model_path, 2, 4)
        self.assertEqual(first["summary"], second["summary"])
        self.assertIn("deterministic_expert", first["summary"])
        self.assertIn("learned_mlp_with_safety", first["summary"])
        self.assertEqual(len(first["visualizations"]), 2)


if __name__ == "__main__":
    unittest.main()
