from pathlib import Path
import sys
import unittest


SIM = Path(__file__).resolve().parents[1] / "software" / "sim"
sys.path.insert(0, str(SIM))
from exploration_scenario import run_exploration  # noqa: E402


class ExplorationScenarioTest(unittest.TestCase):
    def test_hidden_target_requires_mapping_then_is_found(self):
        trace = []
        result = run_exploration(trace=trace)
        self.assertTrue(result["target_seen"], result)
        self.assertTrue(result["success"], result)
        self.assertGreater(result["map"]["counts"]["free"], 100)
        self.assertGreater(result["replans"], 1)
        self.assertTrue(any(row["mode"] == "explore" for row in trace))
        self.assertTrue(any(row["mode"] == "target_track" for row in trace))
        self.assertIn("ground_truth", trace[0])
        self.assertIn("estimate", trace[0])


if __name__ == "__main__":
    unittest.main()
