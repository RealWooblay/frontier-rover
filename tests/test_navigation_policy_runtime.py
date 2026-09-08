import importlib.util
from pathlib import Path
import sys
import unittest

import numpy


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "software" / "jetson" / "navigation_policy_runtime.py"
SPEC = importlib.util.spec_from_file_location("navigation_policy_runtime", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class NavigationPolicyRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = MODULE.NavigationPolicyRuntime(
            ROOT / "artifacts" / "models" / "navigation-policy.npz"
        )

    @staticmethod
    def clear_observation():
        return {
            "goal_distance": 0.5,
            "goal_error": 0.0,
            "front_clearance": 1.0,
            "left_clearance": 1.0,
            "right_clearance": 1.0,
            "forward_velocity": 0.0,
            "yaw_rate": 0.0,
            "collision": 0.0,
            "stuck": 0.0,
        }

    def test_artifact_executes_learned_inference(self):
        result = self.runtime.predict(self.clear_observation())
        self.assertEqual(result["mode"], "learned")
        self.assertTrue(numpy.isfinite(result["forward"]))
        self.assertTrue(numpy.isfinite(result["turn"]))

    def test_collision_bypasses_network_output_with_safety_action(self):
        observation = self.clear_observation()
        observation["collision"] = 1.0
        result = self.runtime.predict(observation)
        self.assertEqual(result["mode"], "safety_recovery")
        self.assertEqual(result["forward"], -0.24)

    def test_missing_observation_is_rejected(self):
        observation = self.clear_observation()
        del observation["yaw_rate"]
        with self.assertRaises(ValueError):
            self.runtime.predict(observation)


if __name__ == "__main__":
    unittest.main()
