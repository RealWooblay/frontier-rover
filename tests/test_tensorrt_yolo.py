from pathlib import Path
import sys
import unittest

import numpy


JETSON_PATH = Path(__file__).resolve().parents[1] / "software" / "jetson"
if str(JETSON_PATH) not in sys.path:
    sys.path.insert(0, str(JETSON_PATH))
from tensorrt_yolo import decode_output, non_maximum_suppression  # noqa: E402


class TensorRTYoloPostprocessTest(unittest.TestCase):
    def test_decodes_letterboxed_bottle_and_removes_overlap(self):
        output = numpy.zeros((1, 84, 2), dtype=numpy.float32)
        output[0, 0:4, 0] = (320, 320, 100, 200)
        output[0, 43, 0] = 0.9
        output[0, 0:4, 1] = (322, 320, 100, 200)
        output[0, 43, 1] = 0.8
        detection = decode_output(output, 39, 0.4, 640, 360, 1.0, 0.0, 140.0)
        self.assertIsNotNone(detection)
        self.assertEqual(detection.class_name, "bottle")
        self.assertAlmostEqual(detection.horizontal_error, 0.0)
        self.assertAlmostEqual(detection.y1_px, 80.0)
        self.assertAlmostEqual(detection.y2_px, 280.0)

    def test_empty_output_has_no_detection(self):
        output = numpy.zeros((1, 84, 1), dtype=numpy.float32)
        self.assertIsNone(decode_output(output, 39, 0.4, 640, 360, 1.0, 0.0, 140.0))


if __name__ == "__main__":
    unittest.main()
