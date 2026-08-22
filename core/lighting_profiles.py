"""Reusable lighting profiles for the GameEngineExport panel.

The module is intentionally independent from FreeCAD and Qt so profiles can
be validated and regression-tested outside the application.
"""

from __future__ import annotations

import copy
import json
from collections import OrderedDict
from typing import Dict, Mapping


PROFILE_SCHEMA_VERSION = 1
DEFAULT_PROFILE_NAME = "Arquitectonico equilibrado"
CUSTOM_PROFILES_PARAM = "lighting_profiles_json"


def _profile(
    *,
    global_enabled: bool,
    global_intensity: float,
    global_shadows: bool,
    camera_fill_enabled: bool,
    camera_fill_intensity: float,
    light_mode: str,
    local_shadows: bool,
    max_shadows: int,
    falloff: str,
    materials_enabled: bool,
    material_mode: str,
) -> Dict:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "scene": {
            "automatic_3d_scene": True,
            "include_hidden_3d_objects": True,
        },
        "global": {
            "enabled": bool(global_enabled),
            "yaw": -30.0,
            "pitch": -45.0,
            "intensity": float(global_intensity),
            "color": [1.0, 0.95, 0.85],
            "shadows": bool(global_shadows),
        },
        "navigation": {
            "camera_fill_enabled": bool(camera_fill_enabled),
            "camera_fill_intensity": float(camera_fill_intensity),
        },
        "local": {
            "manual_lights": False,
            "auto_detect_luminaires": True,
            "light_mode": str(light_mode),
            "shadows": bool(local_shadows),
            "max_shadow_lights": int(max_shadows),
            "falloff": str(falloff),
            "lumens": 3600.0,
            "beam_angle_deg": 120.0,
            "cct_kelvin": 4000.0,
        },
        "materials": {
            "enabled": bool(materials_enabled),
            "mode": str(material_mode),
        },
    }


BUILTIN_PROFILES = OrderedDict(
    (
        (
            "Arquitectonico equilibrado",
            _profile(
                global_enabled=True,
                global_intensity=0.32,
                global_shadows=True,
                camera_fill_enabled=True,
                camera_fill_intensity=0.45,
                light_mode="SpotNoShadows",
                local_shadows=False,
                max_shadows=2,
                falloff="Interior",
                materials_enabled=True,
                material_mode="Architectural",
            ),
        ),
        (
            "Fotometrico realista",
            _profile(
                global_enabled=False,
                global_intensity=0.0,
                global_shadows=False,
                camera_fill_enabled=False,
                camera_fill_intensity=0.0,
                light_mode="PhotometricSpot",
                local_shadows=False,
                max_shadows=0,
                falloff="Interior",
                materials_enabled=False,
                material_mode="None",
            ),
        ),
        (
            "Fotometrico visible",
            _profile(
                global_enabled=True,
                global_intensity=0.10,
                global_shadows=False,
                camera_fill_enabled=False,
                camera_fill_intensity=0.0,
                light_mode="PhotometricSpot",
                local_shadows=False,
                max_shadows=0,
                falloff="Interior",
                materials_enabled=True,
                material_mode="Soft",
            ),
        ),
        (
            "Presentacion brillante",
            _profile(
                global_enabled=True,
                global_intensity=0.45,
                global_shadows=True,
                camera_fill_enabled=True,
                camera_fill_intensity=0.55,
                light_mode="SpotNoShadows",
                local_shadows=False,
                max_shadows=2,
                falloff="Interior",
                materials_enabled=True,
                material_mode="Bright",
            ),
        ),
        (
            "Sombras limitadas",
            _profile(
                global_enabled=True,
                global_intensity=0.22,
                global_shadows=True,
                camera_fill_enabled=True,
                camera_fill_intensity=0.20,
                light_mode="SpotShadowMap",
                local_shadows=False,
                max_shadows=2,
                falloff="Interior",
                materials_enabled=True,
                material_mode="Soft",
            ),
        ),
    )
)


def builtin_profile_names():
    return list(BUILTIN_PROFILES.keys())


def get_builtin_profile(name: str):
    profile = BUILTIN_PROFILES.get(str(name or ""))
    return copy.deepcopy(profile) if profile is not None else None


def clean_profile_name(name: str) -> str:
    return " ".join(str(name or "").strip().split())[:80]


def normalize_profile(profile: Mapping) -> Dict:
    """Return a JSON-safe profile with the supported top-level sections."""
    if not isinstance(profile, Mapping):
        raise ValueError("Lighting profile must be an object")
    normalized = {"schema_version": PROFILE_SCHEMA_VERSION}
    for section in ("scene", "global", "navigation", "local", "materials"):
        value = profile.get(section, {})
        normalized[section] = copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}
    return normalized


def loads_custom_profiles(text: str) -> Dict[str, Dict]:
    if not str(text or "").strip():
        return {}
    try:
        payload = json.loads(str(text))
    except (TypeError, ValueError):
        return {}
    raw_profiles = payload.get("profiles", payload) if isinstance(payload, dict) else {}
    if not isinstance(raw_profiles, dict):
        return {}
    result = {}
    for raw_name, raw_profile in raw_profiles.items():
        name = clean_profile_name(raw_name)
        if not name or name in BUILTIN_PROFILES or not isinstance(raw_profile, Mapping):
            continue
        try:
            result[name] = normalize_profile(raw_profile)
        except ValueError:
            continue
    return result


def dumps_custom_profiles(profiles: Mapping[str, Mapping]) -> str:
    cleaned = {}
    for raw_name, raw_profile in dict(profiles or {}).items():
        name = clean_profile_name(raw_name)
        if not name or name in BUILTIN_PROFILES:
            continue
        cleaned[name] = normalize_profile(raw_profile)
    payload = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profiles": dict(sorted(cleaned.items(), key=lambda item: item[0].casefold())),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "BUILTIN_PROFILES",
    "CUSTOM_PROFILES_PARAM",
    "DEFAULT_PROFILE_NAME",
    "PROFILE_SCHEMA_VERSION",
    "builtin_profile_names",
    "clean_profile_name",
    "dumps_custom_profiles",
    "get_builtin_profile",
    "loads_custom_profiles",
    "normalize_profile",
]
