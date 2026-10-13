"""Lights management helpers for Game Engine Export WB.

Descripcion rapida: API compatible con panel_export para manejo de luces.
Fecha y hora: 2026-03-11 17:40 UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import unicodedata
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


LOG_PREFIX = "[GAMEEXPORT] "
DEBUG_VERSION = "2026-07-30-solid-only-light-origin-v2"
PROPERTY_GROUP = "GameEngineExport"
CGE_PROPERTY_GROUP = "GameEngineLight"
DEFAULT_INTENSITY = 1.0
DEFAULT_RADIUS_M = 12.0
DEFAULT_COLOR = (1.0, 1.0, 1.0)
DEFAULT_LUMENS = 3600.0
DEFAULT_BEAM_ANGLE_DEG = 120.0
DEFAULT_CCT_K = 4000.0
LEGACY_LIGHT_BBOX_OFFSET_MM = 50.0
CGE_LIGHT_TYPES = ["Point", "Linear", "RectPanel", "Circular", "Custom"]
CGE_LIGHT_PATTERNS = ["Single", "Line", "Grid", "Ring", "Custom"]
CGE_LIGHT_DIRECTIONS = ["Down", "Up", "Right", "Left", "Front", "Back", "Custom"]
CGE_LIGHT_ORIGINS = ["AutoFaceCenter", "ManualLocalPoint", "ReferenceMarker"]
MAX_POINTS_PER_LUMINAIRE = 25
PREVIEW_GROUP_NAME = "CGE_TempLightPreview"
REFERENCE_MARKER_PREFIX = "CGE_LightOrigin_"
AUTO_LUMINAIRE_KEYWORDS = (
    "luminaria",
    "luminaire",
    "lampara",
    "lamp",
    "light fixture",
    "lightfixture",
)
AUTO_LUMINAIRE_BOOL_PROPERTIES = (
    "IsGameExportLuminaire",
    "IsLuminaire",
    "IsLightFixture",
)
AUTO_LUMINAIRE_ROLE_PROPERTIES = (
    "GameExportRole",
    "IfcType",
    "PredefinedType",
    "ObjectType",
    "Category",
    "Role",
    "EquipmentType",
    "DeviceType",
)
AUTO_LUMINAIRE_INTENSITY = 0.55
AUTO_LUMINAIRE_RADIUS_M = 6.0
AUTO_LUMINAIRE_COLOR = (1.0, 0.95, 0.88)
AUTO_LUMINAIRE_OFFSET_MM = 40.0
_SOLID_BBOX_LOGGED = set()


@dataclass
class PointLightData:
    name: str
    label: str
    position_mm: tuple[float, float, float]
    intensity: float
    color_rgb: tuple[float, float, float]
    radius: float
    lumens: float = DEFAULT_LUMENS
    beam_angle_deg: float = DEFAULT_BEAM_ANGLE_DEG
    cct_kelvin: float = DEFAULT_CCT_K
    photometric_configured: bool = False


@dataclass
class LightDefinition:
    master_obj: object
    source_obj: object
    effective_placement: object
    light_properties: Dict[str, object]


def _log(message: str) -> None:
    FreeCAD = __import__("FreeCAD")
    FreeCAD.Console.PrintMessage(LOG_PREFIX + message + "\n")


def _log_info(message: str) -> None:
    FreeCAD = __import__("FreeCAD")
    FreeCAD.Console.PrintMessage(LOG_PREFIX + "[INFO] " + message + "\n")


def _log_debug(message: str) -> None:
    FreeCAD = __import__("FreeCAD")
    FreeCAD.Console.PrintMessage(LOG_PREFIX + "[DEBUG] " + message + "\n")


def _log_warn(message: str) -> None:
    FreeCAD = __import__("FreeCAD")
    FreeCAD.Console.PrintWarning(LOG_PREFIX + "[WARN] " + message + "\n")


def list_point_lights(doc) -> List[object]:
    """Return objects flagged as lights (best effort)."""
    if doc is None:
        return []
    return [obj for obj in getattr(doc, "Objects", []) if getattr(obj, "IsGameExportLight", False)]


def tag_selection_as_light(doc, selection: Sequence[object]) -> List[str]:
    if doc is None or not selection:
        return []
    names = []
    for obj in selection:
        if obj is None or getattr(obj, "Document", None) is not doc:
            continue
        _ensure_property(obj, "App::PropertyBool", "IsGameExportLight", "Mark as PointLight")
        _ensure_light_defaults(obj)
        setattr(obj, "IsGameExportLight", True)
        names.append(obj.Name)
    if names:
        _log("Tagged as lights: " + ", ".join(names))
    return names


def untag_selection_as_light(doc, selection: Sequence[object]) -> List[str]:
    if doc is None or not selection:
        return []
    names = []
    for obj in selection:
        if obj is None or getattr(obj, "Document", None) is not doc:
            continue
        if hasattr(obj, "IsGameExportLight"):
            setattr(obj, "IsGameExportLight", False)
            names.append(obj.Name)
    if names:
        _log("Un-tagged lights: " + ", ".join(names))
    return names


def apply_light_names(doc, names: Iterable[str]) -> None:
    if doc is None:
        return
    wanted = set(names or [])
    for obj in getattr(doc, "Objects", []):
        if hasattr(obj, "PropertiesList") and "IsGameExportLight" not in obj.PropertiesList:
            continue
        if hasattr(obj, "IsGameExportLight"):
            obj.IsGameExportLight = obj.Name in wanted or getattr(obj, "Label", "") in wanted


def get_light_properties(obj) -> dict:
    return {
        "intensity": float(getattr(obj, "GameExportLightIntensity", DEFAULT_INTENSITY)),
        "radius": float(getattr(obj, "GameExportLightRadius", DEFAULT_RADIUS_M)),
        "color": _normalize_color(getattr(obj, "GameExportLightColor", DEFAULT_COLOR)),
        "lumens": float(getattr(obj, "GameExportLightLumens", DEFAULT_LUMENS)),
        "beam_angle_deg": float(
            getattr(obj, "GameExportLightBeamAngle", DEFAULT_BEAM_ANGLE_DEG)
        ),
        "cct_kelvin": float(getattr(obj, "GameExportLightCCT", DEFAULT_CCT_K)),
    }


def set_light_properties(
    doc,
    objects: Sequence[object],
    intensity: Optional[float] = None,
    radius: Optional[float] = None,
    color: Optional[Iterable[float]] = None,
    lumens: Optional[float] = None,
    beam_angle_deg: Optional[float] = None,
    cct_kelvin: Optional[float] = None,
) -> List[str]:
    if doc is None or not objects:
        return []
    updated = []
    for obj in objects:
        if obj is None or getattr(obj, "Document", None) is not doc:
            continue
        _ensure_light_defaults(obj)
        if intensity is not None:
            setattr(obj, "GameExportLightIntensity", float(intensity))
        if radius is not None:
            setattr(obj, "GameExportLightRadius", float(radius))
        if color is not None:
            _set_light_color(obj, color)
        if lumens is not None:
            setattr(obj, "GameExportLightLumens", max(0.0, float(lumens)))
        if beam_angle_deg is not None:
            setattr(obj, "GameExportLightBeamAngle", _clamp(float(beam_angle_deg), 1.0, 179.0))
        if cct_kelvin is not None:
            setattr(obj, "GameExportLightCCT", _clamp(float(cct_kelvin), 1800.0, 10000.0))
        updated.append(obj.Name)
    return updated


def _ensure_light_defaults(obj) -> None:
    added_intensity = _ensure_property(obj, "App::PropertyFloat", "GameExportLightIntensity", "Light intensity")
    added_radius = _ensure_property(obj, "App::PropertyFloat", "GameExportLightRadius", "Light radius")
    added_color = _ensure_property(obj, "App::PropertyColor", "GameExportLightColor", "Light color")
    added_lumens = _ensure_property(obj, "App::PropertyFloat", "GameExportLightLumens", "Luminous flux (lm)")
    added_beam = _ensure_property(obj, "App::PropertyFloat", "GameExportLightBeamAngle", "Full beam angle (degrees)")
    added_cct = _ensure_property(obj, "App::PropertyFloat", "GameExportLightCCT", "Correlated color temperature (K)")
    if added_intensity:
        _set_default_if_empty(obj, "GameExportLightIntensity", None)
        setattr(obj, "GameExportLightIntensity", DEFAULT_INTENSITY)
    if added_radius:
        _set_default_if_empty(obj, "GameExportLightRadius", None)
        setattr(obj, "GameExportLightRadius", DEFAULT_RADIUS_M)
    if added_color:
        _set_light_color(obj, DEFAULT_COLOR)
    if added_lumens:
        setattr(obj, "GameExportLightLumens", DEFAULT_LUMENS)
    if added_beam:
        setattr(obj, "GameExportLightBeamAngle", DEFAULT_BEAM_ANGLE_DEG)
    if added_cct:
        setattr(obj, "GameExportLightCCT", DEFAULT_CCT_K)
    _set_default_if_empty(obj, "GameExportLightIntensity", DEFAULT_INTENSITY)
    _set_default_if_empty(obj, "GameExportLightRadius", DEFAULT_RADIUS_M)
    _set_light_color(obj, getattr(obj, "GameExportLightColor", DEFAULT_COLOR))
    _set_default_if_empty(obj, "GameExportLightLumens", DEFAULT_LUMENS)
    _set_default_if_empty(obj, "GameExportLightBeamAngle", DEFAULT_BEAM_ANGLE_DEG)
    _set_default_if_empty(obj, "GameExportLightCCT", DEFAULT_CCT_K)


def _ensure_property(obj, property_type: str, name: str, description: str) -> bool:
    if not hasattr(obj, "PropertiesList") or name in (getattr(obj, "PropertiesList", []) or []):
        return False
    try:
        obj.addProperty(property_type, name, PROPERTY_GROUP, description)
        return True
    except Exception:
        return False


def _set_default_if_empty(obj, name: str, default) -> None:
    try:
        value = getattr(obj, name)
        if value not in (None, ""):
            return
    except Exception:
        pass
    try:
        setattr(obj, name, default)
    except Exception:
        pass


def _set_default_if_added_or_empty(obj, name: str, default, added: bool) -> None:
    if added:
        try:
            setattr(obj, name, default)
        except Exception:
            pass
        return
    _set_default_if_empty(obj, name, default)


def _set_light_color(obj, color: Iterable[float]) -> None:
    rgb = _normalize_color(color)
    try:
        setattr(obj, "GameExportLightColor", rgb)
        return
    except Exception:
        pass
    try:
        setattr(obj, "GameExportLightColor", (rgb[0], rgb[1], rgb[2], 1.0))
    except Exception:
        pass


def _normalize_color(value) -> tuple[float, float, float]:
    if isinstance(value, str):
        try:
            value = [float(part.strip()) for part in value.split(",")]
        except Exception:
            value = DEFAULT_COLOR
    if hasattr(value, "r") and hasattr(value, "g") and hasattr(value, "b"):
        value = (value.r, value.g, value.b)
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        value = DEFAULT_COLOR

    numbers = [float(value[0]), float(value[1]), float(value[2])]
    if any(component > 1.0 for component in numbers):
        numbers = [component / 255.0 for component in numbers]
    return tuple(max(0.0, min(1.0, component)) for component in numbers)


def gather_point_light_data(
    doc,
    names: Iterable[str] | None = None,
    skip_effective_cge: bool = False,
    debug_records: Optional[List[Dict[str, object]]] = None,
) -> List[PointLightData]:
    if doc is None:
        return []
    allowed = set(names) if names is not None else None
    entries: List[PointLightData] = []
    for obj in list_point_lights(doc):
        if allowed is not None and obj.Name not in allowed and getattr(obj, "Label", "") not in allowed:
            continue
        if skip_effective_cge and has_effective_cge_light(obj):
            _log_debug("Skipping legacy point light because CGE light exists: " + _object_ref(obj))
            if debug_records is not None:
                debug_records.append(
                    {
                        "event": "legacy_skipped_by_cge",
                        "source": _debug_object_info(obj),
                    }
                )
            continue
        position, position_debug = _legacy_point_light_position(obj)
        _log_debug(
            "Legacy point light: source="
            + _object_ref(obj)
            + ", method="
            + str(position_debug.get("method", "unknown"))
            + ", world="
            + _format_tuple(position)
        )
        if debug_records is not None:
            debug_records.append(
                {
                    "event": "legacy_point_light",
                    "source": _debug_object_info(obj),
                    "position_mm": list(position),
                    "position_debug": position_debug,
                }
            )
        props = get_light_properties(obj)
        entries.append(
            PointLightData(
                name=obj.Name,
                label=getattr(obj, "Label", obj.Name),
                position_mm=position,
                intensity=float(props["intensity"]),
                color_rgb=tuple(props["color"]),
                radius=float(props["radius"]),
                lumens=float(props["lumens"]),
                beam_angle_deg=float(props["beam_angle_deg"]),
                cct_kelvin=float(props["cct_kelvin"]),
                photometric_configured=True,
            )
        )
    return entries


def _legacy_point_light_position(obj) -> Tuple[tuple[float, float, float], Dict[str, object]]:
    placement = get_global_placement(obj)
    base = getattr(placement, "Base", None)
    fallback = (
        float(getattr(base, "x", 0.0)),
        float(getattr(base, "y", 0.0)),
        float(getattr(base, "z", 0.0)),
    )
    master = resolve_master_object(obj) if _is_link(obj) else obj
    bbox = _get_local_bbox(master)
    if bbox is None:
        return fallback, {
            "method": "placement_base",
            "placement_base_mm": list(fallback),
            "reason": "no_shape_bbox",
        }

    local_point = _vector(
        (float(bbox.XMin) + float(bbox.XMax)) * 0.5,
        (float(bbox.YMin) + float(bbox.YMax)) * 0.5,
        float(bbox.ZMax) + LEGACY_LIGHT_BBOX_OFFSET_MM,
    )
    world_point = _placement_mult_vec(placement, local_point)
    position = (
        float(getattr(world_point, "x", fallback[0])),
        float(getattr(world_point, "y", fallback[1])),
        float(getattr(world_point, "z", fallback[2])),
    )
    return position, {
        "method": "bbox_top",
        "placement_base_mm": list(fallback),
        "bbox_local_mm": [
            float(bbox.XMin),
            float(bbox.YMin),
            float(bbox.ZMin),
            float(bbox.XMax),
            float(bbox.YMax),
            float(bbox.ZMax),
        ],
        "local_point_mm": _vector_tuple(local_point),
        "offset_mm": LEGACY_LIGHT_BBOX_OFFSET_MM,
    }


def ensure_cge_light_properties(obj) -> None:
    """Create CGE_Light properties on a master object."""
    if obj is None:
        return
    added_enabled = _ensure_property_in_group(obj, "App::PropertyBool", "CGE_LightEnabled", "Enable CGE light")
    _ensure_enum_property(obj, "CGE_LightType", CGE_LIGHT_TYPES, "Point")
    _ensure_enum_property(obj, "CGE_LightPattern", CGE_LIGHT_PATTERNS, "Single")
    _ensure_enum_property(obj, "CGE_LightDirection", CGE_LIGHT_DIRECTIONS, "Down")
    _ensure_enum_property(obj, "CGE_LightOriginMode", CGE_LIGHT_ORIGINS, "AutoFaceCenter")
    added_offset = _ensure_property_in_group(obj, "App::PropertyLength", "CGE_LightOffset", "Light offset")
    added_intensity = _ensure_property_in_group(obj, "App::PropertyFloat", "CGE_LightIntensity", "Light intensity")
    added_lumens = _ensure_property_in_group(obj, "App::PropertyFloat", "CGE_LightLumens", "Luminous flux (lm)")
    added_beam = _ensure_property_in_group(obj, "App::PropertyFloat", "CGE_LightBeamAngle", "Full beam angle (degrees)")
    added_cct = _ensure_property_in_group(obj, "App::PropertyFloat", "CGE_LightCCT", "Correlated color temperature (K)")
    added_range = _ensure_property_in_group(obj, "App::PropertyLength", "CGE_LightRange", "Light range")
    added_rows = _ensure_property_in_group(obj, "App::PropertyInteger", "CGE_LightRows", "Light rows")
    added_cols = _ensure_property_in_group(obj, "App::PropertyInteger", "CGE_LightCols", "Light columns")
    added_count = _ensure_property_in_group(obj, "App::PropertyInteger", "CGE_LightCount", "Light count")
    added_r = _ensure_property_in_group(obj, "App::PropertyFloat", "CGE_LightColorR", "Light red")
    added_g = _ensure_property_in_group(obj, "App::PropertyFloat", "CGE_LightColorG", "Light green")
    added_b = _ensure_property_in_group(obj, "App::PropertyFloat", "CGE_LightColorB", "Light blue")
    added_x = _ensure_property_in_group(obj, "App::PropertyLength", "CGE_LightLocalX", "Light local X")
    added_y = _ensure_property_in_group(obj, "App::PropertyLength", "CGE_LightLocalY", "Light local Y")
    added_z = _ensure_property_in_group(obj, "App::PropertyLength", "CGE_LightLocalZ", "Light local Z")
    added_preview = _ensure_property_in_group(
        obj, "App::PropertyBool", "CGE_LightPreviewEnabled", "Show light preview"
    )

    _set_default_if_added_or_empty(obj, "CGE_LightEnabled", True, added_enabled)
    _set_default_if_added_or_empty(obj, "CGE_LightOffset", 50.0, added_offset)
    _set_default_if_added_or_empty(obj, "CGE_LightIntensity", 1.0, added_intensity)
    _set_default_if_added_or_empty(obj, "CGE_LightLumens", DEFAULT_LUMENS, added_lumens)
    _set_default_if_added_or_empty(obj, "CGE_LightBeamAngle", DEFAULT_BEAM_ANGLE_DEG, added_beam)
    _set_default_if_added_or_empty(obj, "CGE_LightCCT", DEFAULT_CCT_K, added_cct)
    _set_default_if_added_or_empty(obj, "CGE_LightRange", 8000.0, added_range)
    _set_default_if_added_or_empty(obj, "CGE_LightRows", 2, added_rows)
    _set_default_if_added_or_empty(obj, "CGE_LightCols", 2, added_cols)
    _set_default_if_added_or_empty(obj, "CGE_LightCount", 6, added_count)
    _set_default_if_added_or_empty(obj, "CGE_LightColorR", 1.0, added_r)
    _set_default_if_added_or_empty(obj, "CGE_LightColorG", 0.95, added_g)
    _set_default_if_added_or_empty(obj, "CGE_LightColorB", 0.85, added_b)
    _set_default_if_added_or_empty(obj, "CGE_LightLocalX", 0.0, added_x)
    _set_default_if_added_or_empty(obj, "CGE_LightLocalY", 0.0, added_y)
    _set_default_if_added_or_empty(obj, "CGE_LightLocalZ", 0.0, added_z)
    _set_default_if_added_or_empty(obj, "CGE_LightPreviewEnabled", True, added_preview)


def has_cge_light_properties(obj) -> bool:
    properties = set(getattr(obj, "PropertiesList", []) or [])
    return "CGE_LightEnabled" in properties


def read_cge_light_properties(obj, create: bool = False) -> Optional[Dict[str, object]]:
    if obj is None:
        return None
    if create:
        ensure_cge_light_properties(obj)
    elif not has_cge_light_properties(obj):
        return None
    return {
        "enabled": bool(getattr(obj, "CGE_LightEnabled", True)),
        "type": _enum_value(getattr(obj, "CGE_LightType", "Point"), "Point", CGE_LIGHT_TYPES),
        "pattern": _enum_value(getattr(obj, "CGE_LightPattern", "Single"), "Single", CGE_LIGHT_PATTERNS),
        "direction": _enum_value(getattr(obj, "CGE_LightDirection", "Down"), "Down", CGE_LIGHT_DIRECTIONS),
        "origin_mode": _enum_value(
            getattr(obj, "CGE_LightOriginMode", "AutoFaceCenter"), "AutoFaceCenter", CGE_LIGHT_ORIGINS
        ),
        "offset_mm": _as_float(getattr(obj, "CGE_LightOffset", 50.0), 50.0),
        "intensity": _as_float(getattr(obj, "CGE_LightIntensity", 1.0), 1.0),
        "lumens": max(0.0, _as_float(getattr(obj, "CGE_LightLumens", DEFAULT_LUMENS), DEFAULT_LUMENS)),
        "beam_angle_deg": _clamp(_as_float(getattr(obj, "CGE_LightBeamAngle", DEFAULT_BEAM_ANGLE_DEG), DEFAULT_BEAM_ANGLE_DEG), 1.0, 179.0),
        "cct_kelvin": _clamp(_as_float(getattr(obj, "CGE_LightCCT", DEFAULT_CCT_K), DEFAULT_CCT_K), 1800.0, 10000.0),
        "range_m": _as_float(getattr(obj, "CGE_LightRange", 8000.0), 8000.0) * 0.001,
        "rows": max(1, int(getattr(obj, "CGE_LightRows", 2) or 2)),
        "cols": max(1, int(getattr(obj, "CGE_LightCols", 2) or 2)),
        "count": max(1, int(getattr(obj, "CGE_LightCount", 6) or 6)),
        "color": (
            _clamp(_as_float(getattr(obj, "CGE_LightColorR", 1.0), 1.0), 0.0, 1.0),
            _clamp(_as_float(getattr(obj, "CGE_LightColorG", 0.95), 0.95), 0.0, 1.0),
            _clamp(_as_float(getattr(obj, "CGE_LightColorB", 0.85), 0.85), 0.0, 1.0),
        ),
        "local_point": (
            _as_float(getattr(obj, "CGE_LightLocalX", 0.0), 0.0),
            _as_float(getattr(obj, "CGE_LightLocalY", 0.0), 0.0),
            _as_float(getattr(obj, "CGE_LightLocalZ", 0.0), 0.0),
        ),
        "preview_enabled": bool(getattr(obj, "CGE_LightPreviewEnabled", True)),
        "photometric_configured": True,
    }


def write_cge_light_properties(obj, values: Dict[str, object]) -> None:
    ensure_cge_light_properties(obj)
    obj.CGE_LightEnabled = bool(values.get("enabled", True))
    _set_enum_value(obj, "CGE_LightType", CGE_LIGHT_TYPES, str(values.get("type", "Point")))
    _set_enum_value(obj, "CGE_LightPattern", CGE_LIGHT_PATTERNS, str(values.get("pattern", "Single")))
    _set_enum_value(obj, "CGE_LightDirection", CGE_LIGHT_DIRECTIONS, str(values.get("direction", "Down")))
    _set_enum_value(
        obj, "CGE_LightOriginMode", CGE_LIGHT_ORIGINS, str(values.get("origin_mode", "AutoFaceCenter"))
    )
    obj.CGE_LightOffset = float(values.get("offset_mm", 50.0))
    obj.CGE_LightIntensity = float(values.get("intensity", 1.0))
    obj.CGE_LightLumens = max(0.0, float(values.get("lumens", DEFAULT_LUMENS)))
    obj.CGE_LightBeamAngle = _clamp(float(values.get("beam_angle_deg", DEFAULT_BEAM_ANGLE_DEG)), 1.0, 179.0)
    obj.CGE_LightCCT = _clamp(float(values.get("cct_kelvin", DEFAULT_CCT_K)), 1800.0, 10000.0)
    obj.CGE_LightRange = float(values.get("range_m", 8.0)) * 1000.0
    obj.CGE_LightRows = max(1, int(values.get("rows", 2)))
    obj.CGE_LightCols = max(1, int(values.get("cols", 2)))
    obj.CGE_LightCount = max(1, int(values.get("count", 6)))
    color = _normalize_color(values.get("color", (1.0, 0.95, 0.85)))
    obj.CGE_LightColorR = color[0]
    obj.CGE_LightColorG = color[1]
    obj.CGE_LightColorB = color[2]
    local_point = values.get("local_point", (0.0, 0.0, 0.0))
    if not isinstance(local_point, (list, tuple)) or len(local_point) != 3:
        local_point = (0.0, 0.0, 0.0)
    obj.CGE_LightLocalX = float(local_point[0])
    obj.CGE_LightLocalY = float(local_point[1])
    obj.CGE_LightLocalZ = float(local_point[2])
    obj.CGE_LightPreviewEnabled = bool(values.get("preview_enabled", True))


def resolve_light_definition(obj) -> Optional[LightDefinition]:
    if obj is None:
        return None
    master = resolve_master_object(obj)
    if master is None:
        return None
    props = read_cge_light_properties(master, create=False)
    if props is None:
        return None
    return LightDefinition(
        master_obj=master,
        source_obj=obj,
        effective_placement=get_global_placement(obj),
        light_properties=props,
    )


def has_effective_cge_light(obj) -> bool:
    definition = resolve_light_definition(obj)
    return definition is not None and bool(definition.light_properties.get("enabled", False))


def resolve_master_object(obj, seen: Optional[set[str]] = None):
    if obj is None:
        return None
    if not _is_link(obj):
        return obj
    seen = seen or set()
    name = getattr(obj, "Name", repr(obj))
    if name in seen:
        _log_warn("LinkedObject cycle detected while resolving " + name)
        return None
    seen.add(name)
    try:
        linked = getattr(obj, "LinkedObject", None)
    except Exception as exc:
        _log_warn("Could not read LinkedObject for " + name + ": " + str(exc))
        return None
    if linked is None:
        _log_warn("Link has no LinkedObject: " + name)
        return None
    return resolve_master_object(linked, seen)


def count_links_to_master(doc, master) -> int:
    if doc is None or master is None:
        return 0
    count = 0
    for obj in getattr(doc, "Objects", []) or []:
        if not _is_link(obj):
            continue
        linked = resolve_master_object(obj)
        if _same_object(linked, master):
            count += 1
    return count


def get_global_placement(obj):
    if obj is None:
        return None
    fallback = _global_placement_from_parent_chain(obj)
    if fallback is not None and _parent_geo_feature_group(obj) is not None:
        return fallback
    try:
        method = getattr(obj, "getGlobalPlacement", None)
        if callable(method):
            placement = method()
            if placement is not None:
                return placement
    except Exception:
        pass
    if fallback is not None:
        return fallback
    return getattr(obj, "Placement", None)


def gather_cge_light_data(
    doc,
    source_objects: Optional[Iterable[object]] = None,
    debug_records: Optional[List[Dict[str, object]]] = None,
) -> List[PointLightData]:
    if doc is None:
        return []
    raw_sources = list(source_objects) if source_objects is not None else list(getattr(doc, "Objects", []) or [])
    source_list = _expand_source_objects(raw_sources)
    _log_debug(
        "CGE scan started: raw_sources="
        + str(len(raw_sources))
        + ", expanded_sources="
        + str(len(source_list))
    )
    if debug_records is not None:
        debug_records.append(
            {
                "event": "cge_scan_started",
                "raw_source_count": len(raw_sources),
                "expanded_source_count": len(source_list),
                "document_object_count": len(list(getattr(doc, "Objects", []) or [])),
            }
        )
    entries: List[PointLightData] = []
    seen_sources: set[str] = set()
    for obj in source_list:
        if obj is None or _is_auxiliary_object(obj):
            continue
        source_name = getattr(obj, "Name", "")
        if source_name in seen_sources:
            continue
        seen_sources.add(source_name)
        master = resolve_master_object(obj)
        master_has_props = master is not None and has_cge_light_properties(master)
        if _is_link(obj) or master_has_props:
            _log_debug(
                "CGE candidate: source="
                + _object_ref(obj)
                + ", master="
                + _object_ref(master)
                + ", master_has_props="
                + str(bool(master_has_props))
            )
            if debug_records is not None:
                debug_records.append(
                    {
                        "event": "cge_candidate",
                        "source": _debug_object_info(obj),
                        "master": _debug_object_info(master),
                        "master_has_props": bool(master_has_props),
                    }
                )
        if master is None or not master_has_props:
            continue
        if not _is_link(obj) and count_links_to_master(doc, master) > 0 and not _is_visible(obj):
            _log_debug("CGE candidate skipped hidden library master: " + _object_ref(obj))
            continue
        definition = resolve_light_definition(obj)
        if definition is None or not bool(definition.light_properties.get("enabled", False)):
            _log_debug("CGE candidate skipped disabled light: " + _object_ref(obj))
            continue
        entries.extend(generate_light_points_for_definition(definition, debug_records))
    _log_debug("CGE scan finished: generated_entries=" + str(len(entries)))
    if debug_records is not None:
        debug_records.append({"event": "cge_scan_finished", "generated_entries": len(entries)})
    return entries


def gather_auto_luminaire_data(
    doc,
    source_objects: Optional[Iterable[object]] = None,
    debug_records: Optional[List[Dict[str, object]]] = None,
) -> List[PointLightData]:
    """Generate one default PointLight for each unconfigured 3D luminaire Link."""
    if doc is None:
        return []
    raw_sources = list(source_objects) if source_objects is not None else list(getattr(doc, "Objects", []) or [])
    source_list = _expand_source_objects(raw_sources)
    entries: List[PointLightData] = []
    seen_sources = set()

    for obj in source_list:
        if obj is None or not _is_link(obj) or _is_auxiliary_object(obj):
            continue
        source_name = str(getattr(obj, "Name", "") or "")
        if not source_name or source_name in seen_sources:
            continue
        seen_sources.add(source_name)
        master = resolve_master_object(obj)
        if master is None or has_cge_light_properties(master):
            continue
        if not _looks_like_luminaire(obj, master):
            continue

        # Requiring a real solid prevents Draft symbols, wires, and planar
        # annotations from becoming lights merely because their labels match.
        if _get_solid_bbox(master) is None:
            _log_debug("Auto luminaire rejected without 3D solid: " + _object_ref(obj))
            continue

        definition = LightDefinition(
            master_obj=master,
            source_obj=obj,
            effective_placement=get_global_placement(obj),
            light_properties={
                "enabled": True,
                "type": "Point",
                "pattern": "Single",
                "direction": "Down",
                "origin_mode": "AutoFaceCenter",
                "offset_mm": AUTO_LUMINAIRE_OFFSET_MM,
                "intensity": AUTO_LUMINAIRE_INTENSITY,
                "lumens": DEFAULT_LUMENS,
                "beam_angle_deg": DEFAULT_BEAM_ANGLE_DEG,
                "cct_kelvin": DEFAULT_CCT_K,
                "photometric_configured": False,
                "range_m": AUTO_LUMINAIRE_RADIUS_M,
                "color": AUTO_LUMINAIRE_COLOR,
                "rows": 1,
                "cols": 1,
                "count": 1,
            },
        )
        generated = generate_light_points_for_definition(definition, debug_records)
        entries.extend(generated)
        if debug_records is not None:
            debug_records.append(
                {
                    "event": "auto_luminaire_detected",
                    "source": _debug_object_info(obj),
                    "master": _debug_object_info(master),
                    "generated_entries": len(generated),
                }
            )

    _log_info("Auto-detected 3D luminaires: " + str(len(entries)))
    return entries


def generate_light_points_for_definition(
    definition: LightDefinition,
    debug_records: Optional[List[Dict[str, object]]] = None,
) -> List[PointLightData]:
    props = definition.light_properties
    local_points = _generate_local_light_points(definition.master_obj, props)
    if not local_points:
        return []
    placement = definition.effective_placement
    results: List[PointLightData] = []
    label = getattr(definition.source_obj, "Label", "") or getattr(definition.source_obj, "Name", "Light")
    source_name = getattr(definition.source_obj, "Name", "Light")
    total_intensity = max(0.0, float(props.get("intensity", 1.0)))
    point_intensity = total_intensity / float(len(local_points))
    point_lumens = max(0.0, float(props.get("lumens", DEFAULT_LUMENS))) / float(len(local_points))
    for index, local_point in enumerate(local_points):
        world_point = _placement_mult_vec(placement, local_point)
        _log_debug(
            "CGE point: source="
            + _object_ref(definition.source_obj)
            + ", master="
            + _object_ref(definition.master_obj)
            + ", local="
            + _format_xyz(local_point)
            + ", placement_base="
            + _format_placement_base(placement)
            + ", world="
            + _format_xyz(world_point)
        )
        if debug_records is not None:
            debug_records.append(
                {
                    "event": "cge_point",
                    "source": _debug_object_info(definition.source_obj),
                    "master": _debug_object_info(definition.master_obj),
                    "origin_mode": str(props.get("origin_mode", "")),
                    "direction": str(props.get("direction", "")),
                    "local_point_mm": _vector_tuple(local_point),
                    "placement_base_mm": _placement_base_tuple(placement),
                    "world_point_mm": _vector_tuple(world_point),
                    "intensity": point_intensity,
                    "total_intensity": total_intensity,
                    "range_m": float(props.get("range_m", 8.0)),
                }
            )
        results.append(
            PointLightData(
                name=f"{source_name}_CGE_{index + 1}",
                label=f"{label} CGE {index + 1}",
                position_mm=(world_point.x, world_point.y, world_point.z),
                intensity=point_intensity,
                color_rgb=tuple(props.get("color", (1.0, 0.95, 0.85))),
                radius=float(props.get("range_m", 8.0)),
                lumens=point_lumens,
                beam_angle_deg=float(props.get("beam_angle_deg", DEFAULT_BEAM_ANGLE_DEG)),
                cct_kelvin=float(props.get("cct_kelvin", DEFAULT_CCT_K)),
                photometric_configured=bool(props.get("photometric_configured", True)),
            )
        )
    _log_debug("Light points generated: " + str(len(results)) + " per instance")
    return results


def remove_temp_light_preview(doc) -> None:
    if doc is None:
        return
    names = []
    for obj in getattr(doc, "Objects", []) or []:
        name = getattr(obj, "Name", "")
        label = getattr(obj, "Label", "")
        if name.startswith(PREVIEW_GROUP_NAME) or label.startswith(PREVIEW_GROUP_NAME):
            names.append(name)
    for name in reversed(names):
        try:
            doc.removeObject(name)
        except Exception:
            pass


def create_temp_light_preview(doc, entries: Sequence[PointLightData]) -> int:
    if doc is None:
        return 0
    remove_temp_light_preview(doc)
    if not entries:
        return 0
    FreeCAD = __import__("FreeCAD")
    Part = __import__("Part")
    group = doc.addObject("App::DocumentObjectGroup", PREVIEW_GROUP_NAME)
    group.Label = PREVIEW_GROUP_NAME
    created = 0
    for index, entry in enumerate(entries[:MAX_POINTS_PER_LUMINAIRE]):
        obj = doc.addObject("Part::Feature", PREVIEW_GROUP_NAME + "_Point")
        obj.Label = PREVIEW_GROUP_NAME + "_Point_" + str(index + 1)
        center = FreeCAD.Vector(entry.position_mm[0], entry.position_mm[1], entry.position_mm[2])
        obj.Shape = Part.makeSphere(25.0, center)
        try:
            obj.ViewObject.ShapeColor = (1.0, 0.85, 0.0)
            obj.ViewObject.Transparency = 15
        except Exception:
            pass
        try:
            group.addObject(obj)
        except Exception:
            pass
        created += 1
    try:
        doc.recompute()
    except Exception:
        pass
    return created


def _generate_local_light_points(master, props: Dict[str, object]):
    bbox = _get_local_bbox(master)
    if bbox is None and props.get("origin_mode") != "ManualLocalPoint":
        _log_warn("Master has no valid Shape BoundingBox: " + (getattr(master, "Name", "") or "Unknown"))
        return []
    direction_name = str(props.get("direction", "Down"))
    direction = _local_direction_vector(direction_name)
    offset = float(props.get("offset_mm", 50.0))
    origin_mode = str(props.get("origin_mode", "AutoFaceCenter"))
    if origin_mode == "ReferenceMarker":
        _log_warn("Reference marker not found; using AutoFaceCenter")
        origin_mode = "AutoFaceCenter"
    if origin_mode == "ManualLocalPoint":
        local = props.get("local_point", (0.0, 0.0, 0.0))
        point = _vector(local[0], local[1], local[2])
        return [_vector_add(point, _vector_scale(direction, offset))]

    pattern = _effective_pattern(props)
    if pattern == "Grid":
        points = _grid_points(bbox, direction, int(props.get("rows", 2)), int(props.get("cols", 2)))
    elif pattern == "Line":
        points = _line_points(bbox, direction, int(props.get("count", 6)))
    elif pattern == "Ring":
        points = _ring_points(bbox, direction, int(props.get("count", 6)))
    else:
        points = [_face_center(bbox, direction)]
    points = [_vector_add(point, _vector_scale(direction, offset)) for point in points]
    if len(points) > MAX_POINTS_PER_LUMINAIRE:
        _log_warn("Light distribution limited to " + str(MAX_POINTS_PER_LUMINAIRE) + " points")
        points = points[:MAX_POINTS_PER_LUMINAIRE]
    return points


def _effective_pattern(props: Dict[str, object]) -> str:
    light_type = str(props.get("type", "Point"))
    pattern = str(props.get("pattern", "Single"))
    if light_type == "RectPanel" or pattern == "Grid":
        return "Grid"
    if light_type == "Linear" or pattern == "Line":
        return "Line"
    if light_type == "Circular" or pattern == "Ring":
        return "Ring"
    return "Single"


def _get_local_bbox(obj):
    try:
        shape = getattr(obj, "Shape", None)
        if shape is None or (hasattr(shape, "isNull") and shape.isNull()):
            return None
        solid_bbox = _get_solid_bbox(obj)
        if solid_bbox is not None:
            bbox = solid_bbox
            whole_bbox = shape.BoundBox
            name = str(getattr(obj, "Name", "") or "")
            if name and name not in _SOLID_BBOX_LOGGED and _bbox_differs(whole_bbox, bbox):
                _SOLID_BBOX_LOGGED.add(name)
                _log_debug(
                    "Using solid-only light bbox to ignore 2D geometry: "
                    + _object_ref(obj)
                    + ", whole_z="
                    + _format_range(whole_bbox.ZMin, whole_bbox.ZMax)
                    + ", solid_z="
                    + _format_range(bbox.ZMin, bbox.ZMax)
                )
        else:
            bbox = shape.BoundBox
        if bbox is None:
            return None
        return bbox
    except Exception:
        return None


class _Bounds:
    """Minimal immutable bounds object used by light point generators."""

    def __init__(self, x_min, y_min, z_min, x_max, y_max, z_max):
        self.XMin = float(x_min)
        self.YMin = float(y_min)
        self.ZMin = float(z_min)
        self.XMax = float(x_max)
        self.YMax = float(y_max)
        self.ZMax = float(z_max)


def _get_solid_bbox(obj):
    """Return bounds of positive-volume solids, excluding 2D edges and faces."""
    try:
        shape = getattr(obj, "Shape", None)
        if shape is None or (hasattr(shape, "isNull") and shape.isNull()):
            return None
        solid_boxes = []
        for solid in list(getattr(shape, "Solids", []) or []):
            if float(getattr(solid, "Volume", 0.0) or 0.0) <= 1e-6:
                continue
            bbox = getattr(solid, "BoundBox", None)
            if bbox is not None:
                solid_boxes.append(bbox)
        if not solid_boxes:
            return None
        return _Bounds(
            min(float(box.XMin) for box in solid_boxes),
            min(float(box.YMin) for box in solid_boxes),
            min(float(box.ZMin) for box in solid_boxes),
            max(float(box.XMax) for box in solid_boxes),
            max(float(box.YMax) for box in solid_boxes),
            max(float(box.ZMax) for box in solid_boxes),
        )
    except Exception:
        return None


def _bbox_differs(first, second, tolerance: float = 1e-6) -> bool:
    for name in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax"):
        if abs(float(getattr(first, name)) - float(getattr(second, name))) > tolerance:
            return True
    return False


def _format_range(minimum, maximum) -> str:
    return "{0:.3f}..{1:.3f}".format(float(minimum), float(maximum))


def _looks_like_luminaire(obj, master) -> bool:
    for candidate in (obj, master):
        for property_name in AUTO_LUMINAIRE_BOOL_PROPERTIES:
            try:
                if hasattr(candidate, property_name) and bool(
                    getattr(candidate, property_name)
                ):
                    return True
            except Exception:
                pass

    text_parts = []
    for candidate in (obj, master):
        text_parts.extend(
            (
                str(getattr(candidate, "Name", "") or ""),
                str(getattr(candidate, "Label", "") or ""),
            )
        )
        for property_name in AUTO_LUMINAIRE_ROLE_PROPERTIES:
            try:
                if hasattr(candidate, property_name):
                    text_parts.append(str(getattr(candidate, property_name) or ""))
            except Exception:
                pass
    text = " ".join(text_parts)
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return any(keyword in normalized for keyword in AUTO_LUMINAIRE_KEYWORDS)


def _face_center(bbox, direction):
    x = (bbox.XMin + bbox.XMax) * 0.5
    y = (bbox.YMin + bbox.YMax) * 0.5
    z = (bbox.ZMin + bbox.ZMax) * 0.5
    axis = _direction_axis(direction)
    if axis == 0:
        x = bbox.XMax if direction.x > 0 else bbox.XMin
    elif axis == 1:
        y = bbox.YMax if direction.y > 0 else bbox.YMin
    else:
        z = bbox.ZMax if direction.z > 0 else bbox.ZMin
    return _vector(x, y, z)


def _grid_points(bbox, direction, rows: int, cols: int):
    rows = max(1, rows)
    cols = max(1, cols)
    axes = _plane_axes(direction)
    points = []
    for row in range(rows):
        for col in range(cols):
            values = _face_center_values(bbox, direction)
            values[axes[0]] = _interp_axis(bbox, axes[0], row, rows)
            values[axes[1]] = _interp_axis(bbox, axes[1], col, cols)
            points.append(_vector(values[0], values[1], values[2]))
    return points


def _line_points(bbox, direction, count: int):
    count = max(1, count)
    axes = _plane_axes(direction)
    axis = max(axes, key=lambda item: _axis_length(bbox, item))
    points = []
    for idx in range(count):
        values = _face_center_values(bbox, direction)
        values[axis] = _interp_axis(bbox, axis, idx, count)
        points.append(_vector(values[0], values[1], values[2]))
    return points


def _ring_points(bbox, direction, count: int):
    count = max(1, count)
    axes = _plane_axes(direction)
    center = _face_center_values(bbox, direction)
    radius = min(_axis_length(bbox, axes[0]), _axis_length(bbox, axes[1])) * 0.35
    points = []
    for idx in range(count):
        angle = (math.pi * 2.0 * idx) / float(count)
        values = list(center)
        values[axes[0]] += math.cos(angle) * radius
        values[axes[1]] += math.sin(angle) * radius
        points.append(_vector(values[0], values[1], values[2]))
    return points


def _face_center_values(bbox, direction):
    point = _face_center(bbox, direction)
    return [point.x, point.y, point.z]


def _interp_axis(bbox, axis: int, index: int, count: int) -> float:
    minimum, maximum = _axis_min_max(bbox, axis)
    if count <= 1:
        return (minimum + maximum) * 0.5
    return minimum + ((index + 1.0) / (count + 1.0)) * (maximum - minimum)


def _axis_min_max(bbox, axis: int) -> Tuple[float, float]:
    if axis == 0:
        return float(bbox.XMin), float(bbox.XMax)
    if axis == 1:
        return float(bbox.YMin), float(bbox.YMax)
    return float(bbox.ZMin), float(bbox.ZMax)


def _axis_length(bbox, axis: int) -> float:
    minimum, maximum = _axis_min_max(bbox, axis)
    return abs(maximum - minimum)


def _direction_axis(direction) -> int:
    values = [abs(direction.x), abs(direction.y), abs(direction.z)]
    return values.index(max(values))


def _plane_axes(direction) -> List[int]:
    axis = _direction_axis(direction)
    return [idx for idx in (0, 1, 2) if idx != axis]


def _local_direction_vector(name: str):
    mapping = {
        "Right": (1.0, 0.0, 0.0),
        "Left": (-1.0, 0.0, 0.0),
        "Front": (0.0, 1.0, 0.0),
        "Back": (0.0, -1.0, 0.0),
        "Up": (0.0, 0.0, 1.0),
        "Down": (0.0, 0.0, -1.0),
        "Custom": (0.0, 0.0, -1.0),
    }
    return _vector(*mapping.get(name, (0.0, 0.0, -1.0)))


def _placement_mult_vec(placement, vector):
    if placement is not None:
        try:
            return placement.multVec(vector)
        except Exception:
            pass
    return vector


def _expand_source_objects(objects: Iterable[object]) -> List[object]:
    expanded: List[object] = []
    seen: set[str] = set()

    def add(obj) -> None:
        if obj is None:
            return
        key = _object_key(obj)
        if key in seen:
            return
        seen.add(key)
        expanded.append(obj)
        for child in getattr(obj, "OutList", []) or []:
            add(child)

    for obj in objects:
        add(obj)
    return expanded


def _global_placement_from_parent_chain(obj, seen: Optional[set[str]] = None):
    if obj is None:
        return None
    seen = seen or set()
    name = getattr(obj, "Name", repr(obj))
    if name in seen:
        _log_warn("Placement parent cycle detected while resolving " + str(name))
        return getattr(obj, "Placement", None)
    seen.add(name)
    placement = getattr(obj, "Placement", None)
    parent = _parent_geo_feature_group(obj)
    if parent is None:
        return placement
    parent_placement = _global_placement_from_parent_chain(parent, seen)
    return _placement_multiply(parent_placement, placement)


def _parent_geo_feature_group(obj):
    if obj is None:
        return None
    try:
        method = getattr(obj, "getParentGeoFeatureGroup", None)
        if callable(method):
            parent = method()
            if parent is not None:
                return parent
    except Exception:
        pass
    for parent in getattr(obj, "InList", []) or []:
        if _is_geo_placement_parent(parent):
            return parent
    return None


def _is_geo_placement_parent(obj) -> bool:
    type_id = str(getattr(obj, "TypeId", "") or "")
    if type_id.startswith("App::Part") or type_id.startswith("PartDesign::Body"):
        return True
    if type_id.startswith("App::LinkGroup"):
        return True
    return hasattr(obj, "Placement") and hasattr(obj, "OutList")


def _placement_multiply(parent_placement, child_placement):
    if parent_placement is None:
        return child_placement
    if child_placement is None:
        return parent_placement
    try:
        return parent_placement.multiply(child_placement)
    except Exception:
        return child_placement


def _object_key(obj) -> str:
    if obj is None:
        return "None"
    document = getattr(obj, "Document", None)
    doc_name = getattr(document, "Name", "")
    return str(doc_name) + "::" + str(getattr(obj, "Name", repr(obj)))


def _object_ref(obj) -> str:
    if obj is None:
        return "None"
    name = str(getattr(obj, "Name", "") or "Unknown")
    label = str(getattr(obj, "Label", "") or "")
    type_id = str(getattr(obj, "TypeId", "") or "")
    if label and label != name:
        return name + " (" + label + ") [" + type_id + "]"
    return name + " [" + type_id + "]"


def _debug_object_info(obj):
    if obj is None:
        return None
    placement = getattr(obj, "Placement", None)
    global_placement = get_global_placement(obj)
    return {
        "name": str(getattr(obj, "Name", "") or ""),
        "label": str(getattr(obj, "Label", "") or ""),
        "type_id": str(getattr(obj, "TypeId", "") or ""),
        "is_link": bool(_is_link(obj)),
        "has_cge_light_properties": bool(has_cge_light_properties(obj)),
        "local_base_mm": _placement_base_tuple(placement),
        "global_base_mm": _placement_base_tuple(global_placement),
    }


def _format_xyz(vector) -> str:
    values = _vector_tuple(vector)
    if values is None:
        return "None"
    return "({:.3f}, {:.3f}, {:.3f})".format(values[0], values[1], values[2])


def _format_placement_base(placement) -> str:
    values = _placement_base_tuple(placement)
    if values is None:
        return "None"
    return "({:.3f}, {:.3f}, {:.3f})".format(values[0], values[1], values[2])


def _format_tuple(values) -> str:
    if values is None or len(values) < 3:
        return "None"
    return "({:.3f}, {:.3f}, {:.3f})".format(float(values[0]), float(values[1]), float(values[2]))


def _vector_tuple(vector):
    if vector is None:
        return None
    return [
        float(getattr(vector, "x", 0.0)),
        float(getattr(vector, "y", 0.0)),
        float(getattr(vector, "z", 0.0)),
    ]


def _placement_base_tuple(placement):
    if placement is None:
        return None
    return _vector_tuple(getattr(placement, "Base", None))


def _vector(x: float, y: float, z: float):
    FreeCAD = __import__("FreeCAD")
    return FreeCAD.Vector(float(x), float(y), float(z))


def _vector_add(a, b):
    return _vector(a.x + b.x, a.y + b.y, a.z + b.z)


def _vector_scale(vector, scale: float):
    return _vector(vector.x * scale, vector.y * scale, vector.z * scale)


def _is_link(obj) -> bool:
    if str(getattr(obj, "TypeId", "") or "") == "App::Link":
        return True
    try:
        return getattr(obj, "LinkedObject", None) is not None
    except Exception:
        return False


def _same_object(first, second) -> bool:
    if first is None or second is None:
        return False
    return getattr(first, "Name", None) == getattr(second, "Name", None) and getattr(first, "Document", None) is getattr(
        second, "Document", None
    )


def _is_visible(obj) -> bool:
    try:
        view = getattr(obj, "ViewObject", None)
        if view is not None and hasattr(view, "Visibility"):
            return bool(view.Visibility)
    except Exception:
        pass
    return True


def _is_auxiliary_object(obj) -> bool:
    name = getattr(obj, "Name", "") or ""
    label = getattr(obj, "Label", "") or ""
    return (
        name.startswith(PREVIEW_GROUP_NAME)
        or label.startswith(PREVIEW_GROUP_NAME)
        or name.startswith(REFERENCE_MARKER_PREFIX)
        or label.startswith(REFERENCE_MARKER_PREFIX)
    )


def _ensure_enum_property(obj, name: str, options: Sequence[str], default: str) -> None:
    current = _enum_value(getattr(obj, name, default), default, options)
    added = _ensure_property_in_group(obj, "App::PropertyEnumeration", name, name)
    try:
        setattr(obj, name, list(options))
    except Exception:
        pass
    _set_enum_value(obj, name, options, default if added else current)


def _set_enum_value(obj, name: str, options: Sequence[str], value: str) -> None:
    clean = value if value in options else options[0]
    try:
        setattr(obj, name, clean)
    except Exception:
        pass


def _enum_value(value, default: str, options: Sequence[str]) -> str:
    text = str(value)
    return text if text in options else default


def _ensure_property_in_group(obj, property_type: str, name: str, description: str) -> bool:
    if not hasattr(obj, "PropertiesList") or name in (getattr(obj, "PropertiesList", []) or []):
        return False
    try:
        obj.addProperty(property_type, name, CGE_PROPERTY_GROUP, description)
        return True
    except Exception:
        return False


def _as_float(value, default: float) -> float:
    try:
        if hasattr(value, "Value"):
            return float(value.Value)
        return float(value)
    except Exception:
        return float(default)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


__all__: List[str] = [
    "CGE_LIGHT_DIRECTIONS",
    "CGE_LIGHT_ORIGINS",
    "CGE_LIGHT_PATTERNS",
    "CGE_LIGHT_TYPES",
    "LightDefinition",
    "PointLightData",
    "apply_light_names",
    "count_links_to_master",
    "create_temp_light_preview",
    "ensure_cge_light_properties",
    "gather_cge_light_data",
    "gather_auto_luminaire_data",
    "gather_point_light_data",
    "generate_light_points_for_definition",
    "get_global_placement",
    "get_light_properties",
    "has_effective_cge_light",
    "has_cge_light_properties",
    "list_point_lights",
    "read_cge_light_properties",
    "remove_temp_light_preview",
    "resolve_light_definition",
    "resolve_master_object",
    "set_light_properties",
    "tag_selection_as_light",
    "untag_selection_as_light",
    "write_cge_light_properties",
]
