from argparse import Namespace
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "software/learning"))
from rover_workshop import gradient, vision


class RoverWorkshopTest(unittest.TestCase):
    def trace(self, **kwargs):
        args = dict(box=[440, 180, 520, 260], lost=False, frame_age_ms=100,
                    left_scale=0.8, right_scale=1.0)
        args.update(kwargs)
        return vision(Namespace(**args))

    def test_right_hand_box_uses_real_controller_and_mixer(self):
        result = self.trace()
        self.assertEqual(result["box"]["source"], "classroom")
        self.assertEqual(result["box"]["horizontal_error"], 0.5)
        self.assertEqual(result["operation"]["action"]["state"], "aligning")
        self.assertEqual(result["signed_pwm_fraction"], (0.24, -0.3))
        self.assertFalse(result["hardware_contacted"])

    def test_centered_box_approaches_and_close_box_stops(self):
        result = self.trace(box=[280, 180, 360, 260])
        left, right = result["signed_pwm_fraction"]
        self.assertGreater(left, 0.0)
        self.assertAlmostEqual(left / right, 0.8)
        close = self.trace(box=[270, 250, 370, 350])
        self.assertEqual(close["operation"]["action"]["state"], "arrived")
        self.assertEqual(close["signed_pwm_fraction"], (0.0, 0.0))

    def test_stale_frames_stop_and_missing_target_requests_heading_feedback(self):
        stale = self.trace(frame_age_ms=1000)
        self.assertEqual(stale["signed_pwm_fraction"], (0.0, 0.0))
        lost = self.trace(lost=True)
        self.assertEqual(lost["operation"]["execution"], "heading_turn")
        self.assertIsNone(lost["signed_pwm_fraction"])

    def test_gradient_matches_numerical_slope_without_modifying_saved_model(self):
        result = gradient(Namespace())
        self.assertAlmostEqual(result["analytic_gradient"],
                               result["finite_difference_gradient"], places=7)
        self.assertLess(result["weighted_loss_after"], result["weighted_loss_before"])
        self.assertTrue(result["saved_model_unchanged"])


if __name__ == "__main__":
    unittest.main()
