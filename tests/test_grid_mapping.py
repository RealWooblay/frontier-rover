from pathlib import Path
import math
import sys
import unittest


SHARED = Path(__file__).resolve().parents[1] / "software" / "shared"
sys.path.insert(0, str(SHARED))
from grid_mapping import DeadReckoningEstimator, OccupancyGrid, Pose2D  # noqa: E402


class GridMappingTest(unittest.TestCase):
    def test_range_ray_marks_free_space_and_an_occupied_endpoint(self):
        grid = OccupancyGrid(width=20, height=20, resolution_m=0.1, origin_x_m=-1.0, origin_y_m=-1.0)
        pose = Pose2D(0.0, 0.0, 0.0)
        grid.update_scan(pose, [0.5], [0.0], 1.0)
        self.assertEqual(grid.state(grid.world_to_cell(0.2, 0.0)), 0)
        self.assertEqual(grid.state(grid.world_to_cell(0.5, 0.0)), 100)

    def test_frontier_and_astar_are_derived_from_the_map(self):
        grid = OccupancyGrid(width=20, height=20, resolution_m=0.1, origin_x_m=-1.0, origin_y_m=-1.0)
        pose = Pose2D(0.0, 0.0, 0.0)
        bearings = [math.radians(value) for value in range(-90, 91, 15)]
        grid.update_scan(pose, [0.8] * len(bearings), bearings, 1.0)
        start = grid.world_to_cell(0.0, 0.0)
        frontier = grid.choose_frontier(start, minimum_distance_cells=2)
        self.assertIsNotNone(frontier)
        self.assertGreater(len(grid.plan(start, frontier)), 1)

    def test_dead_reckoning_integrates_in_si_units_and_grows_uncertainty(self):
        estimator = DeadReckoningEstimator()
        first = estimator.update(0.5, 0.0, 2.0)
        second = estimator.update(0.0, math.pi / 2.0, 1.0)
        self.assertAlmostEqual(first.pose.x_m, 1.0, places=3)
        self.assertAlmostEqual(second.pose.heading_rad, math.pi / 2.0, places=3)
        self.assertGreater(second.position_uncertainty_m, 0.02)
        self.assertGreater(second.heading_uncertainty_degrees, 1.0)


if __name__ == "__main__":
    unittest.main()
