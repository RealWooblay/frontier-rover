import importlib.util
import math
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "software"
    / "sim"
    / "validate_closed_loop_turn.py"
)
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("validate_closed_loop_turn", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ClosedLoopValidationTest(unittest.TestCase):
    def test_unwraps_heading_across_negative_pi_boundary(self):
        previous = math.radians(-179.0)
        current = math.radians(179.0)

        change = MODULE.angle_change(current, previous)

        self.assertAlmostEqual(math.degrees(change), -2.0)

    def test_maps_physical_turn_names_to_simulator_sign(self):
        self.assertEqual(
            MODULE.command_turn({"motion": "left", "throttle": "0.7"}),
            -0.35,
        )
        self.assertEqual(
            MODULE.command_turn({"motion": "right", "throttle": "0.7"}),
            0.35,
        )


if __name__ == "__main__":
    unittest.main()
