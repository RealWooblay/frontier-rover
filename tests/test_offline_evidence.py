from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "software/sim"))
from build_offline_evidence import build_manifest  # noqa: E402


class OfflineEvidenceTest(unittest.TestCase):
    def test_manifest_verifies_hashes_metrics_and_claim_boundary(self):
        manifest = build_manifest()
        self.assertTrue(manifest["all_laptop_checks_pass"])
        self.assertIn("physical", manifest["claim_boundary"].lower())
        self.assertEqual(
            manifest["metrics"]["policy_evaluation"]["learned"]["contact_episodes"],
            0,
        )


if __name__ == "__main__":
    unittest.main()
