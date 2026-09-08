import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "software"
    / "learning"
    / "one_weight_training.py"
)
SPEC = importlib.util.spec_from_file_location("one_weight_training", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class OneWeightTrainingTest(unittest.TestCase):
    def test_initial_gradient_points_toward_larger_weight(self):
        _predictions, _errors, loss, gradient = MODULE.evaluate(0.0)

        self.assertEqual(loss, 1687.5)
        self.assertEqual(gradient, -56.25)

    def test_training_converges_toward_sixty(self):
        history = MODULE.train(steps=8)

        self.assertLess(abs(history[-1].weight_after - 60.0), 0.5)
        self.assertLess(history[-1].loss, history[0].loss)


if __name__ == "__main__":
    unittest.main()
