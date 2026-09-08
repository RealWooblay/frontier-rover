from pathlib import Path
import sys
import unittest


SIM_PATH = Path(__file__).parents[1] / "software" / "sim"
sys.path.insert(0, str(SIM_PATH))
import navigation_env as nav  # noqa: E402
from mujoco_rover import SimObservation  # noqa: E402


class NavigationGeometryTest(unittest.TestCase):
    def test_goal_to_right_has_positive_error(self):
        rover = SimObservation(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        observation = nav.observe_navigation(rover, (1.0, -1.0), ())
        self.assertGreater(observation.goal_error, 0.0)

    def test_front_ray_detects_obstacle(self):
        rover = SimObservation(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        obstacle = nav.CircleObstacle(0.5, 0.0, 0.1)
        self.assertLess(nav.clearance(rover, (obstacle,), 0.0), 0.3)
        self.assertEqual(nav.clearance(rover, (obstacle,), 1.57), 1.0)

    def test_expert_reverses_during_collision_recovery(self):
        observation = nav.NavigationObservation(
            0.5, 0.0, 0.0, 0.8, 0.2, 0.0, 0.0, 1.0, 0.0
        )
        action = nav.expert_action(observation)
        self.assertLess(action.forward, 0.0)
        self.assertEqual(action.mode, "recovery")

    def test_seeded_scenarios_are_reproducible(self):
        self.assertEqual(nav.generate_scenarios(3, 7), nav.generate_scenarios(3, 7))

    def test_expert_completes_clear_waypoint(self):
        scenario = nav.NavigationScenario(0, ((0.8, 0.0),), ())
        result = nav.run_navigation_scenario(
            scenario, nav.ExpertPolicy(), duration_s=15.0
        )
        self.assertTrue(result.success, result)

    def test_forced_stuck_fault_exercises_recovery(self):
        scenario = nav.NavigationScenario(0, ((0.8, 0.0),), ())
        result = nav.run_navigation_scenario(
            scenario,
            nav.ExpertPolicy(),
            duration_s=15.0,
            forced_stuck_window=(0.5, 1.0),
        )
        self.assertGreaterEqual(result.recoveries, 1)
        self.assertTrue(result.success, result)


if __name__ == "__main__":
    unittest.main()
