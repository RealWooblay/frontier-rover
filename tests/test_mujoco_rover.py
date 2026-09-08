import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "software"
    / "sim"
    / "mujoco_rover.py"
)
SPEC = importlib.util.spec_from_file_location("mujoco_rover", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ActionMixingTest(unittest.TestCase):
    def test_forward_drives_both_sides_equally(self):
        self.assertEqual(MODULE.action_to_tank(0.4, 0.0), (0.4, 0.4))

    def test_right_turn_drives_left_faster(self):
        left, right = MODULE.action_to_tank(0.4, 0.2)
        self.assertGreater(left, right)

    def test_mixer_scales_without_changing_ratio(self):
        left, right = MODULE.action_to_tank(1.0, 1.0)
        self.assertEqual((left, right), (1.0, 0.0))


class MuJoCoRoverTest(unittest.TestCase):
    def test_model_compiles_and_exposes_observation(self):
        simulation = MODULE.RoverSimulation()
        observation = simulation.observe()
        self.assertAlmostEqual(observation.time_s, 0.0)

    def test_forward_action_moves_chassis_forward(self):
        simulation = MODULE.RoverSimulation()
        observation = simulation.step(0.4, 0.0, 1.0)
        self.assertGreater(observation.x_m, 0.01)
        self.assertLess(abs(observation.y_m), 0.01)

    def test_turn_action_changes_heading(self):
        simulation = MODULE.RoverSimulation()
        observation = simulation.step(0.0, 0.4, 1.0)
        self.assertLess(observation.yaw_rate_rps, -0.05)

    def test_domain_parameters_change_motor_strength(self):
        simulation = MODULE.RoverSimulation()
        parameters = MODULE.DynamicsParameters(0.8, 0.9, 1.1, 0.006)
        simulation.apply_dynamics(parameters)
        simulation.set_action(0.0, -0.4)
        self.assertEqual(simulation.model.actuator_gainprm[0, 0], 0.9)
        simulation.set_action(0.0, 0.4)
        self.assertEqual(simulation.model.actuator_gainprm[0, 0], 1.1)
        self.assertEqual(simulation.model.actuator_biasprm[0, 2], -0.006)


if __name__ == "__main__":
    unittest.main()
