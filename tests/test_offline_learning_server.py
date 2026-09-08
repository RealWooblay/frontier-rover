"""The travel simulator must never forward requests to physical hardware."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "software/learning"))
from offline_server import OfflineLab


class OfflineLearningTests(unittest.TestCase):
    def test_all_device_requests_are_disabled(self):
        lab = OfflineLab("http://192.168.0.87:8765", "http://192.168.55.1:8771")
        with patch("lab_server.urlopen", side_effect=AssertionError("network attempted")):
            with self.assertRaises(OSError):
                lab.manual_command({"command": "forward"})
            with self.assertRaises(OSError):
                lab.autonomy_command("arm")
            with self.assertRaises(OSError):
                lab.heading_hold({"enabled": True})
            with self.assertRaises(OSError):
                lab.camera_frame()
            self.assertTrue(all("error" in result for result in lab.live().values()))


if __name__ == "__main__":
    unittest.main()
