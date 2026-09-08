import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "software" / "dataset" / "annotation_server.py"
SPEC = importlib.util.spec_from_file_location("annotation_server", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DatasetTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        session = self.root / "raw" / "session"
        session.mkdir(parents=True)
        (session / "frame-0001.jpg").write_bytes(b"image")
        (session / "frame-0001-raw.jpg").write_bytes(b"image")
        self.dataset = MODULE.Dataset(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_lists_only_canonical_images(self):
        self.assertEqual(self.dataset.list_images(), ["raw/session/frame-0001.jpg"])

    def test_saves_and_reads_normalized_yolo_box(self):
        box = {"class_id": 0, "x_center": 0.5, "y_center": 0.6, "width": 0.2, "height": 0.3}
        path = self.dataset.save_boxes("raw/session/frame-0001.jpg", [box])
        self.assertEqual(path.relative_to(self.root).as_posix(), "labels/session/frame-0001.txt")
        self.assertEqual(self.dataset.read_boxes("raw/session/frame-0001.jpg"), [box])

    def test_rejects_path_traversal_and_invalid_coordinates(self):
        with self.assertRaises(ValueError):
            self.dataset.image_path("../outside.jpg")
        with self.assertRaises(ValueError):
            self.dataset.save_boxes(
                "raw/session/frame-0001.jpg",
                [{"class_id": 0, "x_center": 1.2, "y_center": 0.5, "width": 0.2, "height": 0.2}],
            )

    def test_saves_sequential_browser_captures(self):
        jpeg = b"\xff\xd8camera frame\xff\xd9"
        first = self.dataset.save_capture("train-c", jpeg)
        second = self.dataset.save_capture("train-c", jpeg)
        self.assertEqual(first.relative_to(self.root).as_posix(), "raw/train-c/capture-0001.jpg")
        self.assertEqual(second.relative_to(self.root).as_posix(), "raw/train-c/capture-0002.jpg")
        self.assertEqual(first.read_bytes(), jpeg)

    def test_rejects_unsafe_capture_session_and_invalid_jpeg(self):
        with self.assertRaises(ValueError):
            self.dataset.save_capture("../outside", b"\xff\xd8frame\xff\xd9")
        with self.assertRaises(ValueError):
            self.dataset.save_capture("train-c", b"not a jpeg")


if __name__ == "__main__":
    unittest.main()
