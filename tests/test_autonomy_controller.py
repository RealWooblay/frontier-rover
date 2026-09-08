import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "software"
    / "jetson"
    / "autonomy_controller.py"
)
SPEC = importlib.util.spec_from_file_location("autonomy_controller", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class TargetControllerTest(unittest.TestCase):
    def setUp(self):
        self.controller = MODULE.TargetController()

    def test_missing_target_searches_without_forward_motion(self):
        action = self.controller.update(MODULE.Observation(target_visible=False))
        self.assertEqual(action.forward, 0.0)
        self.assertGreater(action.turn, 0.0)
        self.assertEqual(action.state, MODULE.ControlState.SEARCHING)

    def test_search_continues_toward_last_seen_side(self):
        self.controller.update(
            MODULE.Observation(True, horizontal_error=-0.5, area_ratio=0.02)
        )
        action = self.controller.update(MODULE.Observation(target_visible=False))
        self.assertLess(action.turn, 0.0)
        self.assertEqual(action.state, MODULE.ControlState.SEARCHING)

    def test_stale_frame_stops_even_when_target_is_visible(self):
        action = self.controller.update(
            MODULE.Observation(True, horizontal_error=0.0, area_ratio=0.01, frame_age_ms=301)
        )
        self.assertEqual(action.forward, 0.0)
        self.assertEqual(action.turn, 0.0)
        self.assertEqual(action.state, MODULE.ControlState.STALE_FRAME)

    def test_distant_centred_target_requests_forward_motion(self):
        action = self.controller.update(
            MODULE.Observation(True, horizontal_error=0.0, area_ratio=0.02)
        )
        self.assertGreater(action.forward, 0.0)
        self.assertEqual(action.turn, 0.0)
        self.assertEqual(action.state, MODULE.ControlState.APPROACHING)

    def test_off_centre_target_aligns_before_driving(self):
        right = self.controller.update(
            MODULE.Observation(True, horizontal_error=0.5, area_ratio=0.02)
        )
        left = self.controller.update(
            MODULE.Observation(True, horizontal_error=-0.5, area_ratio=0.02)
        )
        self.assertEqual(right.forward, 0.0)
        self.assertGreater(right.turn, 0.0)
        self.assertEqual(left.forward, 0.0)
        self.assertLess(left.turn, 0.0)
        self.assertEqual(right.state, MODULE.ControlState.ALIGNING)

    def test_minimum_turn_overcomes_motor_deadband(self):
        controller = MODULE.TargetController(
            MODULE.ControllerConfig(turn_gain=0.1, max_turn=0.4, min_turn=0.3)
        )
        action = controller.update(
            MODULE.Observation(True, horizontal_error=0.2, area_ratio=0.02)
        )
        self.assertEqual(action.turn, 0.3)

    def test_near_target_stops(self):
        action = self.controller.update(
            MODULE.Observation(True, horizontal_error=0.0, area_ratio=0.14)
        )
        self.assertEqual(action.forward, 0.0)
        self.assertEqual(action.turn, 0.0)
        self.assertEqual(action.state, MODULE.ControlState.ARRIVED)

    def test_floor_target_near_bottom_edge_stops_before_camera_loses_it(self):
        action = self.controller.update(
            MODULE.Observation(
                True,
                horizontal_error=0.0,
                area_ratio=0.05,
                bottom_edge_ratio=0.93,
            )
        )
        self.assertEqual(action.forward, 0.0)
        self.assertEqual(action.turn, 0.0)
        self.assertEqual(action.state, MODULE.ControlState.ARRIVED)

    def test_arrival_latches_despite_later_measurement_noise(self):
        self.controller.update(
            MODULE.Observation(True, horizontal_error=0.0, area_ratio=0.14)
        )
        action = self.controller.update(
            MODULE.Observation(True, horizontal_error=0.0, area_ratio=0.02)
        )
        self.assertEqual(action.forward, 0.0)
        self.assertEqual(action.turn, 0.0)
        self.assertEqual(action.state, MODULE.ControlState.ARRIVED)

    def test_turn_and_forward_outputs_are_bounded(self):
        action = self.controller.update(
            MODULE.Observation(True, horizontal_error=1.0, area_ratio=0.0)
        )
        self.assertLessEqual(abs(action.turn), 0.35)
        self.assertLessEqual(action.forward, 0.7)

    def test_invalid_normalized_geometry_is_rejected(self):
        with self.assertRaises(ValueError):
            self.controller.update(MODULE.Observation(True, horizontal_error=1.1))


if __name__ == "__main__":
    unittest.main()
