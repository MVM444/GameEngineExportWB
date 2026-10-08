"""GameStart helpers for Game Engine Export WB.

Name: core/gamestart.py
Purpose: create, locate, place and read the GameStart marker used as the X3D initial viewpoint.
Main behavior: keeps one reusable marker and can place it outside a main boundary entrance, facing inward.
Modification notes: keep the geometry-independent entrance calculation reusable from Quick Examples and future MCP adapters.
Version: 2026-08-19-main-entrance-v1
Date and time: 2026-08-19 16:13 -06:00
"""

from __future__ import annotations

import math
import string
from typing import Dict, List, Optional, Sequence


LOG_PREFIX = "[GAMEEXPORT] "
PROPERTY_GROUP = "GameEngineExport"
DEFAULT_LABEL = "GameStart"
DEFAULT_FOV_DEG = 60.0
DEFAULT_HEIGHT_OFFSET_MM = 1600.0
DEFAULT_ENTRANCE_DISTANCE_MM = 1800.0
DEFAULT_BOUNDARY_TOLERANCE_MM = 5.0


def ensure_gamestart(doc, label: str = DEFAULT_LABEL):
    """Create or update the GameStart marker in the active document."""
    FreeCAD = __import__("FreeCAD")

    if doc is None:
        FreeCAD.Console.PrintWarning(LOG_PREFIX + "Cannot create GameStart: no active document\n")
        return None

    clean_label = (label or DEFAULT_LABEL).strip() or DEFAULT_LABEL
    obj = find_gamestart(doc, clean_label)
    created = obj is None

    if created:
        obj = doc.addObject("Part::Feature", _safe_object_name(clean_label))
    obj.Label = clean_label

    try:
        obj.Shape = _make_marker_shape()
    except Exception as exc:
        FreeCAD.Console.PrintError(LOG_PREFIX + "Could not build GameStart shape: " + str(exc) + "\n")
        if created:
            try:
                doc.removeObject(obj.Name)
            except Exception:
                pass
        return None

    _ensure_marker_properties(obj)
    _ensure_view_style(obj)

    try:
        doc.recompute()
    except Exception as exc:
        FreeCAD.Console.PrintWarning(LOG_PREFIX + "GameStart recompute warning: " + str(exc) + "\n")

    action = "Created" if created else "Updated"
    FreeCAD.Console.PrintMessage(LOG_PREFIX + action + " GameStart marker: " + obj.Label + "\n")
    return obj


def compute_main_entrance_pose(
    door_segments,
    width_mm: float,
    depth_mm: float,
    distance_mm: float = DEFAULT_ENTRANCE_DISTANCE_MM,
    z_mm: float = 0.0,
) -> Optional[Dict[str, object]]:
    """Return a JSON-friendly pose outside the first door on the outer boundary."""
    width = float(width_mm)
    depth = float(depth_mm)
    distance = max(0.0, float(distance_mm))
    tolerance = max(DEFAULT_BOUNDARY_TOLERANCE_MM, max(width, depth) * 1e-7)
    for index, segment in enumerate(list(door_segments or [])):
        try:
            x1, y1, x2, y2 = [float(value) for value in segment[:4]]
        except Exception:
            continue
        mid_x = (x1 + x2) * 0.5
        mid_y = (y1 + y2) * 0.5
        side = None
        outward = (0.0, 0.0)
        inward = (0.0, 0.0)
        if abs(y1) <= tolerance and abs(y2) <= tolerance:
            side, outward, inward = "south", (0.0, -1.0), (0.0, 1.0)
        elif abs(y1 - depth) <= tolerance and abs(y2 - depth) <= tolerance:
            side, outward, inward = "north", (0.0, 1.0), (0.0, -1.0)
        elif abs(x1) <= tolerance and abs(x2) <= tolerance:
            side, outward, inward = "west", (-1.0, 0.0), (1.0, 0.0)
        elif abs(x1 - width) <= tolerance and abs(x2 - width) <= tolerance:
            side, outward, inward = "east", (1.0, 0.0), (-1.0, 0.0)
        if side is None:
            continue
        yaw_deg = math.degrees(math.atan2(inward[0], -inward[1]))
        yaw_deg = ((yaw_deg + 180.0) % 360.0) - 180.0
        if abs(yaw_deg + 180.0) <= 1e-9:
            yaw_deg = 180.0
        return {
            "position_mm": (mid_x + outward[0] * distance, mid_y + outward[1] * distance, float(z_mm)),
            "yaw_deg": yaw_deg,
            "pitch_deg": 0.0,
            "roll_deg": 0.0,
            "boundary_side": side,
            "door_index": index,
            "door_segment": (x1, y1, x2, y2),
            "fallback": False,
        }
    return None


def place_gamestart_at_main_entrance(
    doc,
    root,
    door_segments,
    width_mm: float,
    depth_mm: float,
    label: str = DEFAULT_LABEL,
    distance_mm: float = DEFAULT_ENTRANCE_DISTANCE_MM,
    height_offset_mm: float = DEFAULT_HEIGHT_OFFSET_MM,
    fov_deg: float = DEFAULT_FOV_DEG,
):
    """Create/update GameStart outside the main entrance and point it inward."""
    FreeCAD = __import__("FreeCAD")
    marker = ensure_gamestart(doc, label)
    if marker is None:
        return None
    pose = compute_main_entrance_pose(door_segments, width_mm, depth_mm, distance_mm)
    if pose is None:
        pose = {
            "position_mm": (float(width_mm) * 0.5, -float(distance_mm), 0.0),
            "yaw_deg": 180.0,
            "pitch_deg": 0.0,
            "roll_deg": 0.0,
            "boundary_side": "south_fallback",
            "door_index": -1,
            "door_segment": None,
            "fallback": True,
        }
        FreeCAD.Console.PrintWarning(LOG_PREFIX + "No boundary entrance found; GameStart uses controlled south fallback\n")
    position = pose["position_mm"]
    marker.Placement.Base = FreeCAD.Vector(float(position[0]), float(position[1]), float(position[2]))
    for name, value in (
        ("Yaw", float(pose["yaw_deg"])),
        ("Pitch", float(pose["pitch_deg"])),
        ("Roll", float(pose["roll_deg"])),
        ("HeightOffset", float(height_offset_mm)),
        ("FOV", float(fov_deg)),
        ("FieldOfView", float(fov_deg)),
    ):
        try:
            setattr(marker, name, value)
        except Exception:
            pass
    _ensure_property(marker, "App::PropertyString", "EntranceSide", str(pose["boundary_side"]))
    _ensure_property(marker, "App::PropertyFloat", "EntranceDistance_mm", float(distance_mm))
    try:
        marker.EntranceSide = str(pose["boundary_side"])
        marker.EntranceDistance_mm = float(distance_mm)
    except Exception:
        pass
    if root is not None:
        try:
            root.addObject(marker)
        except Exception:
            pass
    try:
        doc.recompute()
    except Exception:
        pass
    FreeCAD.Console.PrintMessage(
        LOG_PREFIX + "GameStart placed at main entrance: side=" + str(pose["boundary_side"])
        + ", position_mm=" + ",".join(f"{float(value):.1f}" for value in position)
        + ", yaw_deg=" + f"{float(pose['yaw_deg']):.1f}"
        + (", fallback=true" if pose.get("fallback") else "") + "\n"
    )
    return marker


def find_gamestart(doc, label: str = DEFAULT_LABEL):
    """Find GameStart by marker properties, export type, label or name."""
    if doc is None:
        return None

    clean_label = (label or DEFAULT_LABEL).strip() or DEFAULT_LABEL
    for obj in getattr(doc, "Objects", []):
        if _is_gamestart_marker(obj):
            return obj

    for obj in getattr(doc, "Objects", []):
        obj_label = getattr(obj, "Label", "") or ""
        obj_name = getattr(obj, "Name", "") or ""
        if obj_label == clean_label or obj_name == clean_label:
            return obj

    return None


def get_metadata(obj) -> Optional[Dict[str, object]]:
    """Extract lightweight viewpoint metadata from a GameStart object."""
    if obj is None:
        return None

    FreeCAD = __import__("FreeCAD")
    placement = getattr(obj, "Placement", None)
    base = getattr(placement, "Base", None) if placement is not None else None
    position_mm = (
        float(getattr(base, "x", 0.0)),
        float(getattr(base, "y", 0.0)),
        float(getattr(base, "z", 0.0)),
    )
    yaw_deg = _get_float_property(obj, ("Yaw",), 0.0)
    pitch_deg = _get_float_property(obj, ("Pitch",), 0.0)
    roll_deg = _get_float_property(obj, ("Roll",), 0.0)

    return {
        "position_mm": position_mm,
        "orientation": _placement_orientation(placement),
        "yaw_deg": yaw_deg,
        "pitch_deg": pitch_deg,
        "roll_deg": roll_deg,
        "fov_rad": math.radians(_get_float_property(obj, ("FOV", "FieldOfView"), DEFAULT_FOV_DEG)),
        "height_offset_mm": _get_float_property(
            obj, ("HeightOffset", "HeightOffsetMm"), DEFAULT_HEIGHT_OFFSET_MM
        ),
        "description": getattr(obj, "Label", "") or getattr(obj, "Name", "") or DEFAULT_LABEL,
        "source_doc": getattr(getattr(obj, "Document", None), "Name", ""),
        "freecad_version": getattr(FreeCAD, "Version", lambda: [])(),
    }


def _make_marker_shape():
    """Build a simple marker: flat cylinder base plus cone arrow."""
    FreeCAD = __import__("FreeCAD")
    Part = __import__("Part")

    base_radius = 160.0
    base_height = 35.0
    cone_radius = 110.0
    cone_height = 260.0
    axis = FreeCAD.Vector(0.0, 0.0, 1.0)

    base = Part.makeCylinder(base_radius, base_height, FreeCAD.Vector(0.0, 0.0, 0.0), axis)
    cone = Part.makeCone(
        cone_radius,
        0.0,
        cone_height,
        FreeCAD.Vector(0.0, 0.0, base_height),
        axis,
    )
    return Part.makeCompound([base, cone])


def _ensure_marker_properties(obj) -> None:
    _ensure_property(obj, "App::PropertyBool", "IsGameStart", True)
    _ensure_property(obj, "App::PropertyBool", "IsGameStartMarker", True)
    _ensure_property(obj, "App::PropertyString", "GameExportType", DEFAULT_LABEL)
    _ensure_property(obj, "App::PropertyFloat", "Yaw", 0.0)
    _ensure_property(obj, "App::PropertyFloat", "Pitch", 0.0)
    _ensure_property(obj, "App::PropertyFloat", "Roll", 0.0)
    _ensure_property(obj, "App::PropertyFloat", "FOV", DEFAULT_FOV_DEG)
    _ensure_property(obj, "App::PropertyFloat", "FieldOfView", DEFAULT_FOV_DEG)
    _ensure_property(obj, "App::PropertyFloat", "HeightOffset", DEFAULT_HEIGHT_OFFSET_MM)

    # Marker identity must stay true even if an older object already existed.
    for name, value in (
        ("IsGameStart", True),
        ("IsGameStartMarker", True),
        ("GameExportType", DEFAULT_LABEL),
    ):
        try:
            setattr(obj, name, value)
        except Exception:
            pass


def _ensure_property(obj, property_type: str, name: str, default) -> None:
    properties = set(getattr(obj, "PropertiesList", []) or [])
    added = False
    if name not in properties:
        try:
            obj.addProperty(
                property_type,
                name,
                PROPERTY_GROUP,
                "Game Engine Export GameStart marker property",
            )
            added = True
        except Exception:
            pass

    if not added:
        try:
            current = getattr(obj, name)
            if current not in (None, ""):
                return
        except Exception:
            pass

    try:
        setattr(obj, name, default)
    except Exception:
        pass


def _ensure_view_style(obj) -> None:
    view = getattr(obj, "ViewObject", None)
    if view is None:
        return

    for name, value in (
        ("ShapeColor", (0.1, 0.45, 1.0)),
        ("Transparency", 10),
        ("DisplayMode", "Shaded"),
    ):
        try:
            setattr(view, name, value)
        except Exception:
            pass


def _is_gamestart_marker(obj) -> bool:
    for name in ("IsGameStart", "IsGameStartMarker"):
        try:
            if bool(getattr(obj, name)):
                return True
        except Exception:
            pass

    try:
        export_type = str(getattr(obj, "GameExportType", "") or "")
        if export_type.lower() == DEFAULT_LABEL.lower():
            return True
    except Exception:
        pass

    return False


def _placement_orientation(placement) -> Sequence[float]:
    if placement is None:
        return (0.0, 1.0, 0.0, 0.0)

    rotation = getattr(placement, "Rotation", None)
    axis = getattr(rotation, "Axis", None) if rotation is not None else None
    if axis is None:
        return (0.0, 1.0, 0.0, 0.0)

    length = float(getattr(axis, "Length", 0.0) or 0.0)
    angle_rad = float(getattr(rotation, "Angle", 0.0) or 0.0)
    if length <= 0.0 or abs(angle_rad) < 1e-9:
        return (0.0, 1.0, 0.0, 0.0)

    return (
        float(getattr(axis, "x", 0.0)),
        float(getattr(axis, "y", 0.0)),
        float(getattr(axis, "z", 0.0)),
        angle_rad,
    )


def _get_float_property(obj, names: Sequence[str], default: float) -> float:
    for name in names:
        try:
            value = getattr(obj, name)
            if value is not None:
                return float(value)
        except Exception:
            pass
    return float(default)


def _safe_object_name(label: str) -> str:
    allowed = set(string.ascii_letters + string.digits + "_")
    name = "".join(ch if ch in allowed else "_" for ch in label.strip())
    name = name.strip("_") or DEFAULT_LABEL
    if name[0] in string.digits:
        name = DEFAULT_LABEL + "_" + name
    return name


__all__: List[str] = [
    "compute_main_entrance_pose",
    "ensure_gamestart",
    "find_gamestart",
    "get_metadata",
    "place_gamestart_at_main_entrance",
]
