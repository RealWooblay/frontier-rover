import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "software" / "jetson" / "yolo_perception.py"
SPEC = importlib.util.spec_from_file_location("yolo_perception", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class YoloGeometryTest(unittest.TestCase):
    def test_centred_box_produces_zero_horizontal_error(self):
        detection = MODULE.measure_box(39, "bottle", 0.8, (240, 90, 400, 270), 640, 360)
        self.assertEqual(detection.horizontal_error, 0.0)
        self.assertAlmostEqual(detection.area_ratio, 0.125)
        self.assertEqual(detection.bottom_edge_ratio, 0.75)

    def test_right_box_produces_positive_horizontal_error(self):
        detection = MODULE.measure_box(39, "bottle", 0.8, (480, 100, 600, 300), 640, 360)
        self.assertGreater(detection.horizontal_error, 0.0)

    def test_primary_detection_uses_confidence_then_area(self):
        low = MODULE.measure_box(39, "bottle", 0.5, (0, 0, 200, 200), 640, 360)
        high = MODULE.measure_box(39, "bottle", 0.9, (10, 10, 50, 50), 640, 360)
        self.assertEqual(MODULE.select_primary([low, high]), high)

    def test_invalid_box_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.measure_box(39, "bottle", 0.8, (100, 100, 50, 200), 640, 360)


if __name__ == "__main__":
    unittest.main()
