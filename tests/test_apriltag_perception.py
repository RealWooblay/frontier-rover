import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "software"
    / "jetson"
    / "apriltag_perception.py"
)
SPEC = importlib.util.spec_from_file_location("apriltag_perception", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class TagMeasurementTest(unittest.TestCase):
    def test_centred_tag_has_zero_horizontal_error(self):
        measurement = MODULE.measure_tag(
            7,
            ((270, 130), (370, 130), (370, 230), (270, 230)),
            640,
            360,
        )

        self.assertEqual(measurement.tag_id, 7)
        self.assertEqual(measurement.center_x_px, 320)
        self.assertEqual(measurement.horizontal_error, 0)
        self.assertAlmostEqual(
            measurement.area_ratio,
            10000 / (640 * 360),
            places=6,
        )

    def test_error_sign_identifies_left_and_right(self):
        left = MODULE.measure_tag(
            0,
            ((20, 100), (60, 100), (60, 140), (20, 140)),
            640,
            360,
        )
        right = MODULE.measure_tag(
            0,
            ((580, 100), (620, 100), (620, 140), (580, 140)),
            640,
            360,
        )

        self.assertLess(left.horizontal_error, 0)
        self.assertGreater(right.horizontal_error, 0)

    def test_invalid_geometry_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.measure_tag(0, ((0, 0),), 640, 360)


if __name__ == "__main__":
    unittest.main()
