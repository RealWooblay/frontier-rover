import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).parents[1] / "software" / "pi" / "heading_control.py"
SPEC = importlib.util.spec_from_file_location("heading_control", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class HeadingTurnStateTest(unittest.TestCase):
    def make_state(self, target=90.0):
        return MODULE.HeadingTurnState(target, 10.0, 0.0, MODULE.HeadingConfig())

    def test_positive_error_commands_left(self):
        self.assertEqual(MODULE.HeadingTurnState.direction(20.0), "left")
        self.assertEqual(MODULE.HeadingTurnState.direction(-20.0), "right")

    def test_stops_early_then_completes_after_coast(self):
        state = self.make_state()
        self.assertIsNone(state.advance(80.0, 1.0))
        self.assertEqual(state.advance(88.0, 2.0), "stop")
        self.assertEqual(state.state, "settling")
        self.assertEqual(state.advance(99.0, 2.3), "stop")
        self.assertEqual(state.state, "complete")
        self.assertAlmostEqual(state.measured_degrees, 89.0)

    def test_undershoot_generates_bounded_correction(self):
        state = self.make_state()
        self.assertEqual(state.advance(88.0, 1.0), "stop")
        self.assertEqual(state.advance(88.0, 1.3), "left")
        self.assertEqual(state.state, "correcting")
        self.assertEqual(state.corrections, 1)
        self.assertLessEqual(state.state_deadline - 1.3, 0.15)

    def test_negative_target_uses_signed_delta(self):
        state = self.make_state(-45.0)
        self.assertIsNone(state.advance(-20.0, 0.5))
        self.assertEqual(state.advance(-25.0, 1.0), "stop")
        self.assertAlmostEqual(state.measured_degrees, -35.0)

    def test_status_reports_target_error_and_timing(self):
        state = self.make_state(60.0)
        state.advance(30.0, 1.0)
        status = state.status(1.25)
        self.assertEqual(status["target_degrees"], 60.0)
        self.assertEqual(status["measured_degrees"], 20.0)
        self.assertEqual(status["error_degrees"], 40.0)
        self.assertEqual(status["elapsed_seconds"], 1.25)


if __name__ == "__main__":
    unittest.main()
