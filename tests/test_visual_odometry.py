from pathlib import Path
import sys
import unittest

import cv2
import numpy


JETSON = Path(__file__).resolve().parents[1] / "software" / "jetson"
sys.path.insert(0, str(JETSON))
from visual_odometry import VisualMotionEstimator  # noqa: E402


def encoded(frame):
    ok, jpeg = cv2.imencode(".jpg", frame)
    assert ok
    return jpeg.tobytes()


class VisualMotionEstimatorTest(unittest.TestCase):
    def test_tracks_a_translated_feature_field_without_claiming_metres(self):
        rng = numpy.random.default_rng(4)
        frame = numpy.zeros((360, 640), dtype=numpy.uint8)
        for x, y in rng.integers((20, 20), (620, 340), size=(180, 2)):
            cv2.circle(frame, (int(x), int(y)), 2, 255, -1)
        moved = cv2.warpAffine(frame, numpy.float32([[1, 0, 8], [0, 1, 5]]), (640, 360))
        estimator = VisualMotionEstimator()
        first = estimator.process(encoded(frame))
        second = estimator.process(encoded(moved))
        self.assertEqual(first["state"], "initialized")
        self.assertEqual(second["state"], "tracking")
        self.assertGreater(second["inliers"], 20)
        self.assertEqual(second["metric_scale"], "unobservable_without_calibration_or_odometry")

    def test_invalid_frame_is_diagnostic_not_an_exception(self):
        result = VisualMotionEstimator().process(b"not a jpeg")
        self.assertEqual(result["state"], "invalid_frame")


if __name__ == "__main__":
    unittest.main()
