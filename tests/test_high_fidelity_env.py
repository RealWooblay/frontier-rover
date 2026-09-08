from pathlib import Path
import sys
import unittest

import numpy
from gymnasium.utils.env_checker import check_env


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "software/sim", ROOT / "software/shared", ROOT / "software/jetson"):
    sys.path.insert(0, str(path))

from high_fidelity_env import (  # noqa: E402
    FrontierRoverEnv,
    NavigationFidelity,
    default_scenario,
    generate_scenarios,
    run_policy_episode,
)
from navigation_env import ExpertPolicy  # noqa: E402


class HighFidelityEnvironmentTest(unittest.TestCase):
    def test_gymnasium_contract_and_truth_boundary(self):
        env = FrontierRoverEnv(default_scenario())
        try:
            check_env(env, skip_render_check=True)
            observation, info = env.reset(seed=11)
            self.assertEqual(observation.shape, (9,))
            self.assertTrue(env.observation_space.contains(observation))
            self.assertIn("ground_truth", info)
            self.assertNotIn("ground_truth", info["observation"])
        finally:
            env.close()

    def test_command_latency_delays_applied_motion(self):
        env = FrontierRoverEnv(
            default_scenario(),
            fidelity=NavigationFidelity(command_latency_ms=100),
        )
        try:
            env.reset(seed=4)
            _obs, _reward, _done, _truncated, first = env.step(
                numpy.asarray((0.5, 0.0), dtype=numpy.float32)
            )
            self.assertEqual(first["applied_action"], [0.0, 0.0])
            env.step(numpy.asarray((0.5, 0.0), dtype=numpy.float32))
            _obs, _reward, _done, _truncated, third = env.step(
                numpy.asarray((0.5, 0.0), dtype=numpy.float32)
            )
            self.assertAlmostEqual(third["applied_action"][0], 0.5)
        finally:
            env.close()

    def test_policy_velocity_comes_from_imperfect_sensor_not_truth(self):
        env = FrontierRoverEnv(
            default_scenario(),
            fidelity=NavigationFidelity(
                command_latency_ms=0,
                range_noise_sigma_m=0.0,
                range_dropout_probability=0.0,
                range_latency_ms=0,
                odometry_scale=0.75,
                odometry_noise_sigma_mps=0.0,
                gyro_scale=0.75,
                gyro_bias_dps=0.0,
                gyro_noise_sigma_dps=0.0,
            ),
        )
        try:
            env.reset(seed=4)
            _obs, _reward, _done, _truncated, info = env.step(
                numpy.asarray((0.5, 0.12), dtype=numpy.float32)
            )
            observed_speed = info["observation"]["forward_velocity"] * 0.6
            observed_yaw_rate = info["observation"]["yaw_rate"] * 4.0
            truth = info["ground_truth"]
            self.assertAlmostEqual(observed_speed, truth["forward_velocity_mps"] * 0.75)
            self.assertAlmostEqual(observed_yaw_rate, truth["yaw_rate_rps"] * 0.75)
            self.assertNotAlmostEqual(observed_speed, truth["forward_velocity_mps"])
        finally:
            env.close()

    def test_fault_reports_zero_executed_action(self):
        env = FrontierRoverEnv(
            default_scenario(),
            fidelity=NavigationFidelity(command_latency_ms=0),
            forced_stuck_window=(0.0, 1.0),
        )
        try:
            env.reset(seed=4)
            _obs, _reward, _done, _truncated, info = env.step(
                numpy.asarray((0.5, 0.1), dtype=numpy.float32)
            )
            self.assertEqual(info["applied_action"], [0.5, 0.10000000149011612])
            self.assertEqual(info["executed_action"], [0.0, 0.0])
        finally:
            env.close()

    def test_expert_reaches_goal_through_contact_world(self):
        episode = run_policy_episode(default_scenario(), ExpertPolicy(), seed=7)
        self.assertTrue(episode["result"]["success"], episode["result"])
        self.assertEqual(episode["provenance"]["physics"], "MuJoCo rigid-body and contact solver")
        self.assertGreater(len(episode["trace"]), 20)

    def test_scenarios_are_seeded_and_geometry_varies(self):
        first = generate_scenarios(3, 12)
        second = generate_scenarios(3, 12)
        different = generate_scenarios(3, 13)
        self.assertEqual(first, second)
        self.assertNotEqual(first, different)


if __name__ == "__main__":
    unittest.main()
