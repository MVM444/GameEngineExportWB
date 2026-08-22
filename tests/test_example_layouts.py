"""Regression tests for pure quick-example layouts."""

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "core" / "example_layouts.py"
SPEC = importlib.util.spec_from_file_location("gee_example_layouts_test", MODULE_PATH)
example_layouts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(example_layouts)


class PhotometricExampleLayoutTests(unittest.TestCase):
    def test_divider_has_real_1200_mm_access(self):
        layout = example_layouts.photometric_two_room_layout(10000.0, 5000.0)
        lower, upper = layout["segments"]["interior"]
        doorway = layout["segments"]["doors"][1]
        self.assertEqual(lower[3], doorway[1])
        self.assertEqual(upper[1], doorway[3])
        self.assertEqual(doorway[3] - doorway[1], 1200.0)

    def test_main_entrance_is_on_south_boundary(self):
        layout = example_layouts.photometric_two_room_layout(10000.0, 5000.0)
        entrance = layout["segments"]["doors"][0]
        self.assertEqual(entrance[1], 0.0)
        self.assertEqual(entrance[3], 0.0)
        self.assertGreater(entrance[2] - entrance[0], 0.0)

    def test_gamestart_is_outside_main_entrance_and_faces_inside(self):
        layout = example_layouts.photometric_two_room_layout(10000.0, 5000.0)
        start = layout["gamestart"]
        x, y, z = start["position_mm"]
        entrance = layout["segments"]["doors"][0]
        self.assertAlmostEqual(x, (entrance[0] + entrance[2]) * 0.5)
        self.assertLess(y, 0.0)
        self.assertEqual(z, 0.0)
        self.assertEqual(start["yaw_deg"], 180.0)
        self.assertEqual(start["height_offset_mm"], 1600.0)


if __name__ == "__main__":
    unittest.main()
