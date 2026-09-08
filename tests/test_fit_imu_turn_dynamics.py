import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "software"
    / "sim"
    / "fit_imu_turn_dynamics.py"
)
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("fit_imu_turn_dynamics", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ImuTurnAnalysisTest(unittest.TestCase):
    def test_integrates_bias_corrected_rate(self):
        rows = [
            {"time_s": "0.0", "gy_dps": "2.0"},
            {"time_s": "0.5", "gy_dps": "12.0"},
            {"time_s": "1.0", "gy_dps": "22.0"},
        ]

        angle = MODULE.integrate_angle_degrees(rows, "gy_dps", 2.0)

        self.assertAlmostEqual(angle, 10.0)

    def test_identifies_axis_with_opposite_turn_responses(self):
        rows = []
        for phase, gyroscope_y in (("turn_left", 100.0), ("turn_right", -100.0)):
            rows.append(
                {
                    "phase": phase,
                    "gx_dps": "1.0",
                    "gy_dps": str(gyroscope_y),
                    "gz_dps": "2.0",
                }
            )

        axis = MODULE.identify_yaw_axis(rows, (0.0, 0.0, 0.0))

        self.assertEqual(MODULE.GYRO_AXES[axis], "gy_dps")

    def test_phase_input_uses_steady_pwm_not_initial_status(self):
        rows = [
            {"time_s": "0.00", "left_pwm": "0.0", "right_pwm": "0.0"},
            {"time_s": "0.02", "left_pwm": "-0.35", "right_pwm": "0.35"},
            {"time_s": "0.04", "left_pwm": "-0.35", "right_pwm": "0.35"},
        ]

        forward, turn, duration = MODULE.phase_input(rows)

        self.assertAlmostEqual(forward, 0.0)
        self.assertAlmostEqual(turn, -0.35)
        self.assertAlmostEqual(duration, 0.06)


if __name__ == "__main__":
    unittest.main()
