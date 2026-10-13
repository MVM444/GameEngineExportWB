"""Deterministic, JSON-friendly maze generation for Quick Examples."""

from __future__ import annotations

from collections import deque
import random
from typing import Dict, List, Sequence, Tuple


Cell = Tuple[int, int]
Segment = Tuple[float, float, float, float]


def _cell_pair(a: Cell, b: Cell) -> Tuple[Cell, Cell]:
    return (a, b) if a <= b else (b, a)


def _merge_collinear(segments: Sequence[Segment]) -> List[Segment]:
    """Merge adjacent axis-aligned pieces to keep the FreeCAD model compact."""
    vertical: Dict[float, List[Tuple[float, float]]] = {}
    horizontal: Dict[float, List[Tuple[float, float]]] = {}
    for x1, y1, x2, y2 in segments:
        if abs(x1 - x2) < 1e-9:
            vertical.setdefault(float(x1), []).append(tuple(sorted((float(y1), float(y2)))))
        elif abs(y1 - y2) < 1e-9:
            horizontal.setdefault(float(y1), []).append(tuple(sorted((float(x1), float(x2)))))
        else:
            raise ValueError("Maze wall segments must be axis-aligned.")

    merged: List[Segment] = []
    for x, spans in sorted(vertical.items()):
        start, end = sorted(spans)[0]
        for next_start, next_end in sorted(spans)[1:]:
            if next_start <= end + 1e-9:
                end = max(end, next_end)
            else:
                merged.append((x, start, x, end))
                start, end = next_start, next_end
        merged.append((x, start, x, end))
    for y, spans in sorted(horizontal.items()):
        start, end = sorted(spans)[0]
        for next_start, next_end in sorted(spans)[1:]:
            if next_start <= end + 1e-9:
                end = max(end, next_end)
            else:
                merged.append((start, y, end, y))
                start, end = next_start, next_end
        merged.append((start, y, end, y))
    return merged


def _solution_path(adjacency: Dict[Cell, List[Cell]], start: Cell, cols: int):
    parent = {start: None}
    distance = {start: 0}
    pending = deque([start])
    while pending:
        cell = pending.popleft()
        for neighbor in adjacency[cell]:
            if neighbor in parent:
                continue
            parent[neighbor] = cell
            distance[neighbor] = distance[cell] + 1
            pending.append(neighbor)
    exit_cell = max(
        (cell for cell in adjacency if cell[1] == cols - 1),
        key=lambda cell: (distance[cell], -cell[0]),
    )
    path = []
    current = exit_cell
    while current is not None:
        path.append(current)
        current = parent[current]
    path.reverse()
    return exit_cell, path


def generate_maze_layout(
    rows: int = 7,
    cols: int = 10,
    cell_size_mm: float = 2000.0,
    seed: int = 1,
) -> Dict[str, object]:
    """Generate a connected perfect maze using randomized depth-first search."""
    rows = int(rows)
    cols = int(cols)
    cell_size = float(cell_size_mm)
    if not 2 <= rows <= 50 or not 2 <= cols <= 50:
        raise ValueError("Maze rows and columns must be between 2 and 50.")
    if not 600.0 <= cell_size <= 10000.0:
        raise ValueError("Maze cell size must be between 600 and 10000 mm.")

    rng = random.Random(int(seed))
    start = (rng.randrange(rows), 0)
    visited = {start}
    stack = [start]
    passages = set()
    adjacency: Dict[Cell, List[Cell]] = {
        (row, col): [] for row in range(rows) for col in range(cols)
    }

    while stack:
        row, col = stack[-1]
        candidates = []
        for dr, dc in ((-1, 0), (0, 1), (1, 0), (0, -1)):
            neighbor = (row + dr, col + dc)
            if neighbor in adjacency and neighbor not in visited:
                candidates.append(neighbor)
        if not candidates:
            stack.pop()
            continue
        neighbor = rng.choice(candidates)
        passages.add(_cell_pair((row, col), neighbor))
        adjacency[(row, col)].append(neighbor)
        adjacency[neighbor].append((row, col))
        visited.add(neighbor)
        stack.append(neighbor)

    exit_cell, solution = _solution_path(adjacency, start, cols)
    width = cols * cell_size
    depth = rows * cell_size

    internal: List[Segment] = []
    for row in range(rows):
        y1, y2 = row * cell_size, (row + 1) * cell_size
        for col in range(1, cols):
            left, right = (row, col - 1), (row, col)
            if _cell_pair(left, right) not in passages:
                x = col * cell_size
                internal.append((x, y1, x, y2))
    for row in range(1, rows):
        y = row * cell_size
        for col in range(cols):
            lower, upper = (row - 1, col), (row, col)
            if _cell_pair(lower, upper) not in passages:
                x1, x2 = col * cell_size, (col + 1) * cell_size
                internal.append((x1, y, x2, y))

    opening_width = min(1600.0, max(900.0, cell_size * 0.55))
    start_y = (start[0] + 0.5) * cell_size
    exit_y = (exit_cell[0] + 0.5) * cell_size
    half_opening = opening_width * 0.5
    exterior = [
        (0.0, 0.0, width, 0.0),
        (width, 0.0, width, depth),
        (width, depth, 0.0, depth),
        (0.0, depth, 0.0, 0.0),
    ]
    doors = [
        (0.0, start_y - half_opening, 0.0, start_y + half_opening),
        (width, exit_y - half_opening, width, exit_y + half_opening),
    ]

    return {
        "exterior": exterior,
        "interior": _merge_collinear(internal),
        "doors": doors,
        "windows": [],
        "rooms": [
            {
                "name": "Laberinto",
                "kind": "navegacion_3d",
                "x_mm": 0.0,
                "y_mm": 0.0,
                "w_mm": width,
                "d_mm": depth,
                "area_m2": round(width * depth / 1000000.0, 2),
            }
        ],
        "maze": {
            "algorithm": "randomized_depth_first_search",
            "perfect_maze": True,
            "rows": rows,
            "cols": cols,
            "cell_size_mm": cell_size,
            "seed": int(seed),
            "passage_count": len(passages),
            "entrance_cell": list(start),
            "exit_cell": list(exit_cell),
            "opening_width_mm": opening_width,
            "solution_cells": [list(cell) for cell in solution],
            "ai_editable_fields": [
                "dimensions",
                "segments.interior_walls",
                "segments.door_openings",
                "maze.entrance_cell",
                "maze.exit_cell",
            ],
        },
    }


__all__ = ["generate_maze_layout"]
