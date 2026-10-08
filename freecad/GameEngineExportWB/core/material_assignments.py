"""GameEngineExport material assignment core.

Name: material_assignments.py
Purpose: keep language-independent, JSON-compatible material/texture/mirror settings for exported FreeCAD objects.
Main behavior: normalize assignment dictionaries, read persisted settings from document objects without importing FreeCADGui/Qt, resolve bundled texture identifiers, and collect assignments for exporters or future MCP use.
Modification notes: visible UI belongs in the FreeCAD adapter/UI. Keep identifiers ASCII and stable. Do not mutate document objects here.
Version: 2026-08-19-material-assignments-v1
Date and time: 2026-08-19 17:20 -06:00
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional


PROPERTY_GROUP = "Game Engine Export"
PROP_ENABLED = "GEE_MaterialEnabled"
PROP_MODE = "GEE_MaterialMode"
PROP_TEXTURE_ID = "GEE_TextureId"
PROP_TEXTURE_PATH = "GEE_TexturePath"
PROP_PROJECTION = "GEE_TextureProjection"
PROP_TILE_U_MM = "GEE_TextureTileUMm"
PROP_TILE_V_MM = "GEE_TextureTileVMm"
PROP_REFLECTIVITY = "GEE_Reflectivity"
PROP_MIRROR_SIZE = "GEE_MirrorSize"

MODE_TEXTURE = "Texture"
MODE_POLISHED = "Polished"
MODE_MIRROR = "Mirror"
VALID_MODES = (MODE_TEXTURE, MODE_POLISHED, MODE_MIRROR)

PROJECTION_AUTO = "Auto"
PROJECTION_XY = "XY"
PROJECTION_XZ = "XZ"
PROJECTION_YZ = "YZ"
VALID_PROJECTIONS = (PROJECTION_AUTO, PROJECTION_XY, PROJECTION_XZ, PROJECTION_YZ)

TEXTURE_NONE = "none"
TEXTURE_CUSTOM = "custom"
TEXTURE_CERAMIC = "ceramic_light"
TEXTURE_WOOD = "wood_oak"
TEXTURE_CONCRETE = "concrete"
TEXTURE_STONE = "stone"
TEXTURE_BRICK = "brick"
TEXTURE_CEILING = "ceiling_panel"
TEXTURE_METAL = "metal_brushed"

BUILTIN_TEXTURES = {
    TEXTURE_NONE: {
        "label_en": "None",
        "label_es": "Ninguna",
        "file": "",
        "tile_u_mm": 1000.0,
        "tile_v_mm": 1000.0,
    },
    TEXTURE_CUSTOM: {
        "label_en": "Custom file",
        "label_es": "Archivo personalizado",
        "file": "",
        "tile_u_mm": 1000.0,
        "tile_v_mm": 1000.0,
    },
    TEXTURE_CERAMIC: {
        "label_en": "Ceramic / porcelain",
        "label_es": "Ceramica / porcelanato",
        "file": "ceramic_light.png",
        "tile_u_mm": 600.0,
        "tile_v_mm": 600.0,
    },
    TEXTURE_WOOD: {
        "label_en": "Wood",
        "label_es": "Madera",
        "file": "wood_oak.png",
        "tile_u_mm": 1200.0,
        "tile_v_mm": 180.0,
    },
    TEXTURE_CONCRETE: {
        "label_en": "Concrete",
        "label_es": "Concreto",
        "file": "concrete.png",
        "tile_u_mm": 1000.0,
        "tile_v_mm": 1000.0,
    },
    TEXTURE_STONE: {
        "label_en": "Stone",
        "label_es": "Piedra",
        "file": "stone.png",
        "tile_u_mm": 600.0,
        "tile_v_mm": 400.0,
    },
    TEXTURE_BRICK: {
        "label_en": "Brick / block",
        "label_es": "Ladrillo / bloque",
        "file": "brick.png",
        "tile_u_mm": 400.0,
        "tile_v_mm": 200.0,
    },
    TEXTURE_CEILING: {
        "label_en": "Ceiling panel",
        "label_es": "Panel de cielo",
        "file": "ceiling_panel.png",
        "tile_u_mm": 600.0,
        "tile_v_mm": 600.0,
    },
    TEXTURE_METAL: {
        "label_en": "Brushed metal",
        "label_es": "Metal cepillado",
        "file": "metal_brushed.png",
        "tile_u_mm": 1000.0,
        "tile_v_mm": 1000.0,
    },
}


def _safe_float(value, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except Exception:
        number = float(default)
    return min(max(number, minimum), maximum)


def _safe_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = int(default)
    return min(max(number, minimum), maximum)


def normalize_mode(value: object) -> str:
    text = str(value or MODE_TEXTURE).strip().lower()
    aliases = {
        "texture": MODE_TEXTURE,
        "textured": MODE_TEXTURE,
        "polished": MODE_POLISHED,
        "reflective": MODE_POLISHED,
        "mirror": MODE_MIRROR,
    }
    return aliases.get(text, MODE_TEXTURE)


def normalize_projection(value: object) -> str:
    text = str(value or PROJECTION_AUTO).strip().upper()
    if text == "AUTO":
        return PROJECTION_AUTO
    if text in {PROJECTION_XY, PROJECTION_XZ, PROJECTION_YZ}:
        return text
    return PROJECTION_AUTO


def normalize_texture_id(value: object) -> str:
    text = str(value or TEXTURE_NONE).strip().lower()
    return text if text in BUILTIN_TEXTURES else TEXTURE_CUSTOM


def normalize_assignment(data: Optional[Dict[str, object]]) -> Dict[str, object]:
    source = dict(data or {})
    texture_id = normalize_texture_id(source.get("texture_id", TEXTURE_NONE))
    defaults = BUILTIN_TEXTURES.get(texture_id, BUILTIN_TEXTURES[TEXTURE_NONE])
    return {
        "enabled": bool(source.get("enabled", False)),
        "mode": normalize_mode(source.get("mode", MODE_TEXTURE)),
        "texture_id": texture_id,
        "texture_path": str(source.get("texture_path", "") or "").strip(),
        "projection": normalize_projection(source.get("projection", PROJECTION_AUTO)),
        "tile_u_mm": _safe_float(source.get("tile_u_mm", defaults["tile_u_mm"]), defaults["tile_u_mm"], 1.0, 100000.0),
        "tile_v_mm": _safe_float(source.get("tile_v_mm", defaults["tile_v_mm"]), defaults["tile_v_mm"], 1.0, 100000.0),
        "reflectivity": _safe_float(source.get("reflectivity", 0.35), 0.35, 0.0, 1.0),
        "mirror_size": _safe_int(source.get("mirror_size", 512), 512, 64, 4096),
    }


def builtin_texture_path(texture_id: object) -> str:
    texture_key = normalize_texture_id(texture_id)
    filename = str(BUILTIN_TEXTURES.get(texture_key, {}).get("file", "") or "")
    if not filename:
        return ""
    workbench_root = Path(__file__).resolve().parents[1]
    candidate = workbench_root / "resources" / "textures" / filename
    return str(candidate) if candidate.is_file() else ""


def resolve_texture_path(assignment: Dict[str, object]) -> str:
    cfg = normalize_assignment(assignment)
    if cfg["texture_id"] == TEXTURE_CUSTOM:
        return str(cfg["texture_path"] or "")
    return builtin_texture_path(cfg["texture_id"])


def read_object_assignment(obj: object) -> Dict[str, object]:
    """Read persisted GameEngineExport assignment from a FreeCAD-like object.

    The function intentionally uses duck typing and does not import FreeCAD,
    so it can be exercised in unit tests and reused by future MCP adapters.
    """
    if obj is None:
        return normalize_assignment(None)
    properties = set(getattr(obj, "PropertiesList", []) or [])
    enabled = bool(getattr(obj, PROP_ENABLED, False)) if PROP_ENABLED in properties else False
    raw = {
        "enabled": enabled,
        "mode": getattr(obj, PROP_MODE, MODE_TEXTURE) if PROP_MODE in properties else MODE_TEXTURE,
        "texture_id": getattr(obj, PROP_TEXTURE_ID, TEXTURE_NONE) if PROP_TEXTURE_ID in properties else TEXTURE_NONE,
        "texture_path": getattr(obj, PROP_TEXTURE_PATH, "") if PROP_TEXTURE_PATH in properties else "",
        "projection": getattr(obj, PROP_PROJECTION, PROJECTION_AUTO) if PROP_PROJECTION in properties else PROJECTION_AUTO,
        "tile_u_mm": getattr(obj, PROP_TILE_U_MM, 1000.0) if PROP_TILE_U_MM in properties else 1000.0,
        "tile_v_mm": getattr(obj, PROP_TILE_V_MM, 1000.0) if PROP_TILE_V_MM in properties else 1000.0,
        "reflectivity": getattr(obj, PROP_REFLECTIVITY, 0.35) if PROP_REFLECTIVITY in properties else 0.35,
        "mirror_size": getattr(obj, PROP_MIRROR_SIZE, 512) if PROP_MIRROR_SIZE in properties else 512,
    }
    cfg = normalize_assignment(raw)
    cfg["object_name"] = str(getattr(obj, "Name", "") or "")
    cfg["object_label"] = str(getattr(obj, "Label", "") or "")
    native_material = getattr(obj, "Material", None) if "Material" in properties else None
    cfg["native_material_name"] = str(getattr(native_material, "Label", "") or getattr(native_material, "Name", "") or "")
    return cfg


def collect_assignments(objects: Iterable[object], enabled_only: bool = True) -> List[Dict[str, object]]:
    assignments: List[Dict[str, object]] = []
    for index, obj in enumerate(list(objects or [])):
        cfg = read_object_assignment(obj)
        if enabled_only and not bool(cfg.get("enabled", False)):
            continue
        cfg["object_index"] = index
        assignments.append(cfg)
    return assignments


__all__ = [
    "BUILTIN_TEXTURES",
    "MODE_MIRROR",
    "MODE_POLISHED",
    "MODE_TEXTURE",
    "PROPERTY_GROUP",
    "PROP_ENABLED",
    "PROP_MIRROR_SIZE",
    "PROP_MODE",
    "PROP_PROJECTION",
    "PROP_REFLECTIVITY",
    "PROP_TEXTURE_ID",
    "PROP_TEXTURE_PATH",
    "PROP_TILE_U_MM",
    "PROP_TILE_V_MM",
    "PROJECTION_AUTO",
    "PROJECTION_XY",
    "PROJECTION_XZ",
    "PROJECTION_YZ",
    "TEXTURE_CUSTOM",
    "TEXTURE_NONE",
    "builtin_texture_path",
    "collect_assignments",
    "normalize_assignment",
    "normalize_mode",
    "normalize_projection",
    "normalize_texture_id",
    "read_object_assignment",
    "resolve_texture_path",
]
