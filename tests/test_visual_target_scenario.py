import importlib.util
from pathlib import Path
import sys
import unittest


SIM_PATH = Path(__file__).resolve().parents[1] / "software" / "sim"
if str(SIM_PATH) not in sys.path:
    sys.path.insert(0, str(SIM_PATH))
MODULE_PATH = SIM_PATH / "visual_target_scenario.py"
SPEC = importlib.util.spec_from_file_location("visual_target_scenario", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class VisualTargetScenarioTest(unittest.TestCase):
    def test_target_ahead_is_centred_and_visible(self):
        rover = MODULE.SimObservation(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        observation = MODULE.target_observation(rover, MODULE.VisualTarget(1.0, 0.0))
        self.assertTrue(observation.target_visible)
        self.assertAlmostEqual(observation.horizontal_error, 0.0)

    def test_target_to_right_has_positive_camera_error(self):
        rover = MODULE.SimObservation(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        observation = MODULE.target_observation(rover, MODULE.VisualTarget(1.0, -0.2))
        self.assertGreater(observation.horizontal_error, 0.0)

    def test_closed_loop_reaches_centred_target(self):
        trace = []
        result = MODULE.run_scenario(MODULE.VisualTarget(1.0, 0.0), trace=trace)
        self.assertTrue(result.success, result)
        self.assertGreaterEqual(result.final_distance_m, 0.35)
        self.assertLessEqual(result.final_distance_m, 0.65)
        self.assertGreater(len(trace), 1)
        self.assertIn("observation", trace[0])
        self.assertIn("action", trace[0])

    def test_search_finds_target_initially_behind_rover(self):
        result = MODULE.run_scenario(
            MODULE.VisualTarget(-1.5, 0.0), duration_s=20.0
        )
        self.assertTrue(result.success, result)

    def test_trace_uses_shared_measured_search_semantics(self):
        trace = []
        MODULE.run_scenario(MODULE.VisualTarget(-1.5, 0.0), duration_s=20.0, trace=trace)
        search = next(row for row in trace if row["action"]["state"] == "searching")
        self.assertEqual(search["command"]["execution"], "heading_turn")
        self.assertEqual(abs(search["command"]["heading_degrees"]), 30.0)


if __name__ == "__main__":
    unittest.main()
