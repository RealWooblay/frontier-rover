from pathlib import Path
import tempfile
import sys
import unittest

import numpy


SIM_PATH = Path(__file__).parents[1] / "software" / "sim"
sys.path.insert(0, str(SIM_PATH))
from mlp_policy import LearnedNavigationPolicy, SafetyShield, TinyMLP  # noqa: E402
from navigation_env import NavigationAction, NavigationObservation  # noqa: E402


class TinyMLPTest(unittest.TestCase):
    def test_training_reduces_loss(self):
        rng = numpy.random.default_rng(4)
        inputs = rng.uniform(-1, 1, (300, 9))
        targets = numpy.stack((inputs[:, 0] * 0.4, inputs[:, 1] * 0.2), axis=1)
        model = TinyMLP(hidden_size=12, seed=4)
        before = numpy.mean((model.predict(inputs) - targets) ** 2)
        model.fit(inputs, targets, inputs, targets, epochs=40, batch_size=64, seed=4)
        after = numpy.mean((model.predict(inputs) - targets) ** 2)
        self.assertLess(after, before * 0.2)

    def test_saved_policy_reloads_exactly(self):
        model = TinyMLP(hidden_size=8, seed=2)
        inputs = numpy.arange(9, dtype=float) / 10.0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.npz"
            model.save(path)
            loaded = TinyMLP.load(path)
            numpy.testing.assert_allclose(model.predict(inputs), loaded.predict(inputs))

    def test_collision_uses_safety_override(self):
        policy = LearnedNavigationPolicy(TinyMLP())
        observation = NavigationObservation(0.5, 0.0, 0.0, 1.0, 0.2, 0.0, 0.0, 1.0, 0.0)
        action = policy.act(observation)
        self.assertLess(action.forward, 0.0)
        self.assertTrue(action.mode.startswith("safety_"))

    def test_shield_leaves_clear_safe_proposal_unchanged(self):
        shield = SafetyShield()
        observation = NavigationObservation(0.5, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0)
        proposed = NavigationAction(0.4, 0.02, "learned_track")
        self.assertEqual(shield.apply(observation, proposed), proposed)

    def test_shield_pivots_before_driving_into_front_obstacle(self):
        shield = SafetyShield()
        observation = NavigationObservation(0.5, 0.0, 0.25, 0.8, 0.2, 0.2, 0.0, 0.0, 0.0)
        action = shield.apply(observation, NavigationAction(0.6, 0.0, "track"))
        self.assertEqual(action.forward, 0.0)
        self.assertLess(action.turn, 0.0)
        self.assertEqual(action.mode, "safety_recovery_pivot")

    def test_shield_steers_away_from_close_left_side(self):
        shield = SafetyShield()
        observation = NavigationObservation(0.5, 0.0, 1.0, 0.1, 0.9, 0.2, 0.0, 0.0, 0.0)
        action = shield.apply(observation, NavigationAction(0.5, -0.1, "track"))
        self.assertLessEqual(action.forward, 0.2)
        self.assertGreaterEqual(action.turn, 0.12)


if __name__ == "__main__":
    unittest.main()
