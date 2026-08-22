"""Tests for deterministic JSON-friendly maze generation."""

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "core" / "maze_generator.py"
SPEC = importlib.util.spec_from_file_location("gee_maze_generator_test", MODULE_PATH)
maze_generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(maze_generator)


class MazeGeneratorTests(unittest.TestCase):
    def test_same_seed_is_deterministic(self):
        first = maze_generator.generate_maze_layout(6, 8, 1800.0, 12345)
        second = maze_generator.generate_maze_layout(6, 8, 1800.0, 12345)
        self.assertEqual(first, second)

    def test_perfect_maze_has_one_less_passage_than_cells(self):
        layout = maze_generator.generate_maze_layout(7, 10, 2000.0, 77)
        self.assertEqual(layout["maze"]["passage_count"], 69)
        self.assertTrue(layout["maze"]["perfect_maze"])
        self.assertEqual(layout["maze"]["entrance_cell"][1], 0)
        self.assertEqual(layout["maze"]["exit_cell"][1], 9)
        self.assertGreater(len(layout["maze"]["solution_cells"]), 1)

    def test_segments_are_axis_aligned_and_inside_bounds(self):
        layout = maze_generator.generate_maze_layout(5, 9, 1500.0, 12)
        width, depth = 9 * 1500.0, 5 * 1500.0
        for segment in layout["exterior"] + layout["interior"] + layout["doors"]:
            x1, y1, x2, y2 = segment
            self.assertTrue(x1 == x2 or y1 == y2)
            self.assertTrue(0.0 <= x1 <= width and 0.0 <= x2 <= width)
            self.assertTrue(0.0 <= y1 <= depth and 0.0 <= y2 <= depth)


if __name__ == "__main__":
    unittest.main()
