import importlib.util
from pathlib import Path
import sys
import unittest


JETSON = Path(__file__).resolve().parents[1] / "software" / "jetson"
sys.path.insert(0, str(JETSON))
SPEC = importlib.util.spec_from_file_location("mission_runtime", JETSON / "mission_runtime.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class MissionRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.config = MODULE.RuntimeConfig()

    def test_search_is_a_measured_heading_turn(self):
        action = MODULE.Action(0.0, 0.35, MODULE.ControlState.SEARCHING)
        command = MODULE.plan_execution(
            action, MODULE.Observation(False), self.config, MODULE.SearchProgress()
        )
        self.assertEqual(command.kind, MODULE.ExecutionKind.HEADING_TURN)
        self.assertEqual(command.heading_degrees, -30.0)
        self.assertEqual(command.progress.steps, 1)

    def test_full_sweep_becomes_bounded_reverse(self):
        action = MODULE.Action(0.0, 0.35, MODULE.ControlState.SEARCHING)
        command = MODULE.plan_execution(
            action,
            MODULE.Observation(False),
            self.config,
            MODULE.SearchProgress(self.config.maximum_search_steps, 0),
        )
        self.assertEqual(command.kind, MODULE.ExecutionKind.MOTOR_PULSE)
        self.assertEqual(command.action.state, MODULE.ControlState.RECOVERING)
        self.assertLess(command.action.forward, 0.0)
        self.assertTrue(command.flip_search_direction)

    def test_approach_duration_shrinks_near_target(self):
        action = MODULE.Action(0.5, 0.0, MODULE.ControlState.APPROACHING)
        far = MODULE.plan_execution(
            action, MODULE.Observation(True, area_ratio=0.01), self.config, MODULE.SearchProgress()
        )
        near = MODULE.plan_execution(
            action, MODULE.Observation(True, area_ratio=0.07), self.config, MODULE.SearchProgress()
        )
        self.assertGreater(far.duration_ms, near.duration_ms)
        self.assertGreaterEqual(near.duration_ms, 50)


if __name__ == "__main__":
    unittest.main()
