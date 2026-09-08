from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch


SIM_PATH = Path(__file__).parents[1] / "software" / "sim"
sys.path.insert(0, str(SIM_PATH))
from lab_server import Lab, build_summary, build_turn_traces  # noqa: E402


class LabServerTest(unittest.TestCase):
    def test_camera_proxy_preserves_source_frame_metadata(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"jpeg"
        response.headers = {"X-Frame-Id": "42", "X-Frame-Age-Ms": "170"}
        with patch("lab_server.urlopen", return_value=response):
            image, headers = Lab("http://127.0.0.1:1").camera_frame()
        self.assertEqual(image, b"jpeg")
        self.assertEqual(headers, response.headers)

    def test_camera_proxy_rejects_missing_age_instead_of_inventing_freshness(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {"X-Frame-Id": "42"}
        with patch("lab_server.urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "metadata"):
                Lab("http://127.0.0.1:1").camera_frame()

    def test_summary_exposes_training_navigation_and_claims(self):
        summary = build_summary()
        self.assertIn("training", summary)
        self.assertIn("navigation", summary)
        self.assertGreaterEqual(len(summary["claims"]), 3)

    def test_turn_trace_contains_comparable_series(self):
        traces = build_turn_traces()
        self.assertIn("turn_left", traces)
        self.assertIn("physical_degrees", traces["turn_left"][-1])
        self.assertIn("simulated_degrees", traces["turn_left"][-1])

    def test_custom_scenario_runs_real_mujoco_adapter(self):
        lab = Lab("http://127.0.0.1:1")
        result = lab.run_scenario(
            {"scenario_id": 0, "policy": "learned", "floor_friction": 1.0}
        )
        self.assertIn("trace", result)
        self.assertGreater(len(result["trace"]), 5)
        self.assertEqual(result["provenance"]["engine"], "MuJoCo")

    def test_hidden_target_scenario_searches_then_arrives(self):
        lab = Lab("http://127.0.0.1:1")
        result = lab.run_target_scenario(
            {"bearing_degrees": 170, "distance_m": 1.5}
        )
        self.assertEqual(result["kind"], "target_search")
        self.assertTrue(result["result"]["success"], result["result"])
        self.assertEqual(result["provenance"]["source"], "simulated")
        self.assertTrue(
            any(not row["observation"]["target_visible"] for row in result["trace"])
        )
        self.assertTrue(
            any(row["observation"]["target_visible"] for row in result["trace"])
        )

    def test_policy_arena_uses_contact_world_and_imperfect_observations(self):
        lab = Lab("http://127.0.0.1:1")
        result = lab.run_policy_arena(
            {"scenario_id": 2, "policy": "learned", "capture_frames": False}
        )
        self.assertEqual(result["kind"], "high_fidelity_policy_arena")
        self.assertGreater(len(result["trace"]), 20)
        self.assertEqual(result["provenance"]["physics"], "MuJoCo rigid-body and contact solver")
        self.assertIn("ground_truth", result["trace"][0])
        self.assertNotIn("ground_truth", result["trace"][0]["observation"])

    def test_prediction_exposes_hidden_activations(self):
        lab = Lab("http://127.0.0.1:1")
        values = {
            "goal_distance": 0.5,
            "goal_error": 0.2,
            "front_clearance": 1.0,
            "left_clearance": 1.0,
            "right_clearance": 1.0,
            "forward_velocity": 0.0,
            "yaw_rate": 0.0,
            "collision": 0.0,
            "stuck": 0.0,
        }
        result = lab.predict(values)
        self.assertEqual(len(result["hidden"]), 32)
        self.assertIn("turn", result["outputs"])

    def test_mapping_exploration_exposes_estimate_map_and_truth_separately(self):
        lab = Lab("http://127.0.0.1:1")
        result = lab.run_exploration_scenario({})
        self.assertTrue(result["result"]["success"], result["result"])
        self.assertEqual(result["kind"], "mapping_exploration")
        self.assertIn("cells", result["map"])
        self.assertIn("estimate", result["trace"][0])
        self.assertIn("ground_truth", result["trace"][0])
        self.assertIn("observation_gap", result["provenance"])

    def test_heading_hold_requires_an_explicit_boolean(self):
        lab = Lab("http://127.0.0.1:1")
        with self.assertRaisesRegex(ValueError, "boolean"):
            lab.heading_hold({"enabled": "yes"})


if __name__ == "__main__":
    unittest.main()
