from pathlib import Path
import math
import sys
import unittest

import numpy


SIM = Path(__file__).resolve().parents[1] / "software" / "sim"
sys.path.insert(0, str(SIM))
from exploration_scenario import ExplorationWorld  # noqa: E402
from mujoco_rover import RoverSimulation  # noqa: E402
from mujoco_world import (  # noqa: E402
    GeometrySensors,
    build_world_xml,
    detect_orange_target,
)


class MujocoWorldTest(unittest.TestCase):
    def setUp(self):
        self.world = ExplorationWorld()
        self.simulation = RoverSimulation(model_xml=build_world_xml(self.world))
        self.sensors = GeometrySensors(self.simulation.model, self.simulation.data)

    def tearDown(self):
        self.sensors.close()

    def test_ray_distance_comes_from_wall_geometry(self):
        self.simulation.set_planar_state(0.0, 0.0, 0.0)
        distance = self.sensors.ranges(0.0, [0.0], 5.0)[0]
        self.assertAlmostEqual(distance, 1.9, delta=0.03)

    def test_obstacle_generates_mujoco_contact_pair(self):
        obstacle = self.world.obstacles[0]
        self.simulation.set_planar_state(obstacle.x_m, obstacle.y_m, 0.0)
        self.simulation.step(0.0, 0.0, 0.01)
        contacts = self.sensors.contacts()
        self.assertTrue(any("obstacle_0" in pair for pair in contacts), contacts)

    def test_pixel_detector_obeys_positive_image_right_contract(self):
        frame = numpy.zeros((180, 320, 3), dtype=numpy.uint8)
        frame[80:120, 220:260] = (255, 76, 3)
        detection = detect_orange_target(frame)
        self.assertTrue(detection.target_visible)
        self.assertGreater(detection.horizontal_error, 0.0)
        self.assertIsNotNone(detection.estimated_distance_m)

    def test_pixel_detector_rejects_tiny_occlusion_fragment(self):
        frame = numpy.zeros((180, 320, 3), dtype=numpy.uint8)
        frame[90:94, 150:154] = (255, 76, 3)
        self.assertFalse(detect_orange_target(frame).target_visible)


if __name__ == "__main__":
    unittest.main()
