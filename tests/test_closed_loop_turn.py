import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "software"
    / "pi"
    / "closed_loop_turn.py"
)
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("closed_loop_turn", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class YawIntegratorTest(unittest.TestCase):
    def test_subtracts_bias_and_integrates_rate(self):
        integrator = MODULE.YawIntegrator(2.0)

        integrator.update(0, 12.0)
        integrator.update(500_000_000, 12.0)
        integrator.update(1_000_000_000, 12.0)

        self.assertAlmostEqual(integrator.angle_degrees, 10.0)

    def test_direction_follows_signed_error(self):
        self.assertEqual(MODULE.direction_for(20.0), "left")
        self.assertEqual(MODULE.direction_for(-20.0), "right")

    def test_correction_pulse_is_bounded(self):
        self.assertEqual(MODULE.correction_duration(1.0), 0.05)
        self.assertEqual(MODULE.correction_duration(100.0), 0.15)


if __name__ == "__main__":
    unittest.main()
