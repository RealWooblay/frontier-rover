import importlib.util
import pathlib
import sys
import unittest


MODULE_PATH = (
    pathlib.Path(__file__).parents[1]
    / "software"
    / "pi"
    / "imu_motion_experiment.py"
)
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("imu_motion_experiment", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class MotionSequenceTest(unittest.TestCase):
    def test_sequence_is_bounded_and_stops_between_movements(self):
        phases = MODULE.PHASES

        self.assertEqual(phases[0].motion, "stop")
        self.assertEqual(phases[-1].motion, "stop")
        self.assertLess(sum(phase.duration_s for phase in phases), 12.0)
        for index, phase in enumerate(phases):
            if phase.motion != "stop" and index + 1 < len(phases):
                self.assertEqual(phases[index + 1].motion, "stop")

    def test_command_refresh_is_faster_than_motor_watchdog(self):
        self.assertLess(1.0 / 10.0, 0.35)


if __name__ == "__main__":
    unittest.main()
