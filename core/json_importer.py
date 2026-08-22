"""Import Quick Example JSON payloads.

Fecha: 2026-07-11.
Objetivo: leer JSON pegado desde ChatGPT y reconstruir ejemplos BIM.
Instrucciones principales:
- No usar API externa.
- Aceptar JSON puro o texto con JSON embebido.
- Ignorar payload["objects"] porque pertenece a otro documento FreeCAD.
- Reutilizar GameEngineExportWB.core.quick_examples para generar geometria.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Sequence

import FreeCAD

from . import quick_examples


LOG_PREFIX = "[GAMEEXPORT] "


def _warn(message: str) -> None:
    FreeCAD.Console.PrintWarning(LOG_PREFIX + message + "\n")


def extract_json_text(text: str) -> str:
    """Extract the first-to-last JSON object block from arbitrary text."""
    raw = str(text or "").strip()
    first = raw.find("{")
    last = raw.rfind("}")
    if first < 0 or last < 0 or last <= first:
        raise ValueError("No JSON object block found.")
    return raw[first : last + 1]


def load_payload_from_text(text: str) -> Dict:
    """Load a dict payload from JSON text or text containing JSON."""
    json_text = extract_json_text(text)
    try:
        payload = json.loads(json_text)
    except Exception as exc:
        raise ValueError("JSON parse error: %s" % exc)
    if not isinstance(payload, dict):
        raise ValueError("JSON root must be an object.")
    return payload


def _as_float(value, name: str) -> float:
    try:
        return float(value)
    except Exception:
        raise ValueError("%s must be numeric." % name)


def _reasonable_positive(value: float, name: str, min_value: float, max_value: float) -> None:
    if value < min_value or value > max_value:
        raise ValueError("%s out of reasonable range: %s" % (name, value))


def _validate_segment(segment, name: str) -> None:
    if not isinstance(segment, (list, tuple)) or len(segment) != 4:
        raise ValueError("%s must be [x1,y1,x2,y2]." % name)
    for index, value in enumerate(segment):
        _as_float(value, "%s[%d]" % (name, index))


def _segment_list(payload_segments: Dict, key: str) -> Sequence:
    value = payload_segments.get(key, [])
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ValueError("segments.%s must be a list." % key)
    return value


def validate_quick_example_payload(payload: Dict) -> List[str]:
    """Validate minimum Quick Example JSON and return warning messages."""
    if not isinstance(payload, dict):
        raise ValueError("Payload must be an object.")
    warnings: List[str] = []

    units = payload.get("units", "mm")
    if "units" not in payload:
        warnings.append("units missing; assuming mm.")
    elif units != "mm":
        raise ValueError("Only units='mm' is supported.")

    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ValueError("dimensions object is required.")
    segments = payload.get("segments")
    if not isinstance(segments, dict):
        raise ValueError("segments object is required.")

    width = _as_float(dimensions.get("width_mm"), "dimensions.width_mm")
    depth = _as_float(dimensions.get("depth_mm"), "dimensions.depth_mm")
    if width <= 0 or depth <= 0:
        raise ValueError("width_mm and depth_mm must be greater than zero.")

    _reasonable_positive(_as_float(dimensions.get("ext_wall_mm", quick_examples.DEFAULT_EXT_WALL_MM), "ext_wall_mm"), "ext_wall_mm", 10.0, 2000.0)
    _reasonable_positive(_as_float(dimensions.get("int_wall_mm", quick_examples.DEFAULT_INT_WALL_MM), "int_wall_mm"), "int_wall_mm", 10.0, 2000.0)
    _reasonable_positive(_as_float(dimensions.get("wall_height_mm", quick_examples.DEFAULT_WALL_HEIGHT_MM), "wall_height_mm"), "wall_height_mm", 500.0, 20000.0)
    _reasonable_positive(_as_float(dimensions.get("door_height_mm", quick_examples.DEFAULT_DOOR_HEIGHT_MM), "door_height_mm"), "door_height_mm", 500.0, 10000.0)
    _reasonable_positive(_as_float(dimensions.get("window_height_mm", quick_examples.DEFAULT_WINDOW_HEIGHT_MM), "window_height_mm"), "window_height_mm", 100.0, 10000.0)

    exterior = _segment_list(segments, "exterior_walls")
    if not exterior:
        raise ValueError("segments.exterior_walls must contain at least one segment.")
    for key in ("exterior_walls", "interior_walls", "door_openings", "window_openings"):
        for index, segment in enumerate(_segment_list(segments, key)):
            _validate_segment(segment, "segments.%s[%d]" % (key, index))

    rooms = payload.get("rooms", [])
    if rooms is not None and not isinstance(rooms, list):
        raise ValueError("rooms must be a list when present.")
    maze = payload.get("maze")
    if maze is not None and not isinstance(maze, dict):
        raise ValueError("maze must be an object when present.")
    return warnings


def _normalize_segment(segment) -> List[float]:
    return [round(float(segment[0]), 1), round(float(segment[1]), 1), round(float(segment[2]), 1), round(float(segment[3]), 1)]


def normalize_quick_example_payload(payload: Dict) -> Dict:
    """Return a clean payload using defaults compatible with quick_examples."""
    warnings = validate_quick_example_payload(payload)
    for message in warnings:
        _warn(message)

    dimensions_in = dict(payload.get("dimensions") or {})
    terrain_in = dict(payload.get("terrain") or {})
    segments_in = dict(payload.get("segments") or {})
    normalized = {
        "macro": "GameEngineExportWB Quick Example",
        "building_type": str(payload.get("building_type", "Casa") or "Casa"),
        "building_variant": str(payload.get("building_variant", "json_import") or "json_import"),
        "seed": int(float(payload.get("seed", 0) or 0)),
        "units": "mm",
        "dimensions": {
            "width_mm": _as_float(dimensions_in.get("width_mm"), "width_mm"),
            "depth_mm": _as_float(dimensions_in.get("depth_mm"), "depth_mm"),
            "ext_wall_mm": _as_float(dimensions_in.get("ext_wall_mm", quick_examples.DEFAULT_EXT_WALL_MM), "ext_wall_mm"),
            "int_wall_mm": _as_float(dimensions_in.get("int_wall_mm", quick_examples.DEFAULT_INT_WALL_MM), "int_wall_mm"),
            "wall_height_mm": _as_float(dimensions_in.get("wall_height_mm", quick_examples.DEFAULT_WALL_HEIGHT_MM), "wall_height_mm"),
            "door_height_mm": _as_float(dimensions_in.get("door_height_mm", quick_examples.DEFAULT_DOOR_HEIGHT_MM), "door_height_mm"),
            "window_sill_mm": _as_float(dimensions_in.get("window_sill_mm", quick_examples.DEFAULT_WINDOW_SILL_MM), "window_sill_mm"),
            "window_height_mm": _as_float(dimensions_in.get("window_height_mm", quick_examples.DEFAULT_WINDOW_HEIGHT_MM), "window_height_mm"),
        },
        "terrain": {
            "enabled": bool(terrain_in.get("enabled", True)),
            "flatten_pad": bool(terrain_in.get("flatten_pad", quick_examples.DEFAULT_FLATTEN_PAD)),
            "pad_margin_mm": _as_float(terrain_in.get("pad_margin_mm", quick_examples.DEFAULT_PAD_MARGIN_MM), "pad_margin_mm"),
            "terrain_margin_mm": _as_float(terrain_in.get("terrain_margin_mm", quick_examples.DEFAULT_TERRAIN_MARGIN_MM), "terrain_margin_mm"),
            "terrain_variation_mm": _as_float(terrain_in.get("terrain_variation_mm", quick_examples.DEFAULT_TERRAIN_VARIATION_MM), "terrain_variation_mm"),
            "floor_overhang_mm": _as_float(terrain_in.get("floor_overhang_mm", quick_examples.DEFAULT_FLOOR_OVERHANG_MM), "floor_overhang_mm"),
        },
        "segments": {
            "exterior_walls": [_normalize_segment(s) for s in _segment_list(segments_in, "exterior_walls")],
            "interior_walls": [_normalize_segment(s) for s in _segment_list(segments_in, "interior_walls")],
            "door_openings": [_normalize_segment(s) for s in _segment_list(segments_in, "door_openings")],
            "window_openings": [_normalize_segment(s) for s in _segment_list(segments_in, "window_openings")],
        },
        "rooms": list(payload.get("rooms") or []),
    }
    for key in ("maze", "ai_editing"):
        value = payload.get(key)
        if isinstance(value, dict):
            normalized[key] = dict(value)
    return normalized


def generate_quick_example_from_payload(payload: Dict, options: Optional[Dict] = None):
    """Generate a FreeCAD quick example from a normalized or raw payload."""
    normalized = normalize_quick_example_payload(payload)
    build_options = dict(options or {})
    payload_extensions = dict(build_options.get("payload_extensions", {}) or {})
    for key in ("maze", "ai_editing"):
        if isinstance(normalized.get(key), dict):
            payload_extensions[key] = normalized[key]
    if payload_extensions:
        build_options["payload_extensions"] = payload_extensions
    return quick_examples.build_quick_example_from_data(
        normalized["building_type"],
        normalized["building_variant"],
        normalized["seed"],
        normalized["dimensions"],
        normalized["terrain"],
        normalized["segments"],
        normalized.get("rooms", []),
        build_options,
    )
