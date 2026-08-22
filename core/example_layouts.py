"""Pure geometry layouts shared by GameEngineExport quick examples and tests.

Name: core/example_layouts.py
Purpose: keep deterministic JSON-friendly example layouts independent from the FreeCAD GUI.
Main behavior: defines small reproducible scenes used by Quick Examples and regression tests.
Modification notes: the photometric example now has an exterior main entrance so GameStart can follow the common entrance convention.
Version: 2026-08-19-main-entrance-v1
Date and time: 2026-08-19 16:13 -06:00
"""

from __future__ import annotations

from typing import Dict


PHOTOMETRIC_DOOR_WIDTH_MM = 1200.0


def _room(name: str, kind: str, x: float, y: float, width: float, depth: float) -> Dict:
    return {
        "name": name,
        "kind": kind,
        "x_mm": round(float(x), 1),
        "y_mm": round(float(y), 1),
        "w_mm": round(float(width), 1),
        "d_mm": round(float(depth), 1),
        "area_m2": round(float(width) * float(depth) / 1000000.0, 2),
    }


def photometric_two_room_layout(
    width_mm: float,
    depth_mm: float,
    doorway_width_mm: float = PHOTOMETRIC_DOOR_WIDTH_MM,
) -> Dict:
    """Return two rooms with a real gap in the divider and a usable GameStart."""
    width = float(width_mm)
    depth = float(depth_mm)
    if width < 4000.0 or depth < 3000.0:
        raise ValueError("Photometric example requires at least 4000 x 3000 mm")

    divider_x = width * 0.5
    door_width = max(900.0, min(float(doorway_width_mm), depth * 0.45))
    door_y1 = (depth - door_width) * 0.5
    door_y2 = door_y1 + door_width
    entrance_width = min(PHOTOMETRIC_DOOR_WIDTH_MM, max(900.0, width * 0.18))
    entrance_center_x = width * 0.18
    entrance_x1 = max(250.0, entrance_center_x - entrance_width * 0.5)
    entrance_x2 = min(divider_x - 250.0, entrance_x1 + entrance_width)
    entrance_center_x = (entrance_x1 + entrance_x2) * 0.5

    return {
        "segments": {
            "variant": "calibracion_fotometrica_dos_recintos_v2",
            "exterior": [
                (0.0, 0.0, width, 0.0),
                (width, 0.0, width, depth),
                (width, depth, 0.0, depth),
                (0.0, depth, 0.0, 0.0),
            ],
            # The divider is physically split. Navigation does not depend on a
            # Boolean subtraction succeeding in Arch Wall.
            "interior": [
                (divider_x, 0.0, divider_x, door_y1),
                (divider_x, door_y2, divider_x, depth),
            ],
            # Main exterior entrance first, then the internal access between rooms.
            "doors": [
                (entrance_x1, 0.0, entrance_x2, 0.0),
                (divider_x, door_y1, divider_x, door_y2),
            ],
            "windows": [],
        },
        "rooms": [
            _room("Recinto fotometrico A", "calibracion", 0.0, 0.0, divider_x, depth),
            _room(
                "Recinto fotometrico B",
                "calibracion",
                divider_x,
                0.0,
                width - divider_x,
                depth,
            ),
        ],
        "gamestart": {
            "label": "GameStart",
            "position_mm": [round(entrance_center_x, 1), -1800.0, 0.0],
            "yaw_deg": 180.0,
            "pitch_deg": 0.0,
            "roll_deg": 0.0,
            "height_offset_mm": 1600.0,
            "fov_deg": 60.0,
            "faces": "main_entrance",
        },
        "photometric_example": {
            "lumens_per_luminaire": 3600.0,
            "beam_angle_deg": 120.0,
            "cct_kelvin": 4000.0,
            "doorway_width_mm": round(door_width, 1),
        },
    }


__all__ = ["PHOTOMETRIC_DOOR_WIDTH_MM", "photometric_two_room_layout"]
