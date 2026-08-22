"""Regression tests for GameStart main-entrance pose calculation."""

import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "core" / "gamestart.py"
SPEC = importlib.util.spec_from_file_location("gee_gamestart_test", MODULE_PATH)
gamestart = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gamestart)


class GameStartEntrancePoseTests(unittest.TestCase):
    def test_south_entrance_places_marker_outside_and_faces_positive_y(self):
        pose = gamestart.compute_main_entrance_pose(
            [(1000.0, 0.0, 2200.0, 0.0)], 10000.0, 8000.0
        )
        self.assertEqual(pose["boundary_side"], "south")
        self.assertEqual(pose["position_mm"], (1600.0, -1800.0, 0.0))
        self.assertEqual(pose["yaw_deg"], 180.0)

    def test_west_entrance_faces_positive_x(self):
        pose = gamestart.compute_main_entrance_pose(
            [(0.0, 2000.0, 0.0, 3200.0)], 10000.0, 8000.0
        )
        self.assertEqual(pose["boundary_side"], "west")
        self.assertEqual(pose["position_mm"], (-1800.0, 2600.0, 0.0))
        self.assertEqual(pose["yaw_deg"], 90.0)

    def test_internal_door_is_ignored(self):
        pose = gamestart.compute_main_entrance_pose(
            [(5000.0, 2000.0, 5000.0, 3200.0)], 10000.0, 8000.0
        )
        self.assertIsNone(pose)


if __name__ == "__main__":
    unittest.main()
