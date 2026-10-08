"""Read a static sun state from the optional FreeCAD Solar Workbench.

The adapter consumes Solar's persisted ``SunProperties`` document object. It
does not import Ladybug, execute Solar commands or recompute the document.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import math
import sys
from typing import Callable, Iterable, Optional, Tuple

from ..core.solar import (
    SunEnvironment,
    direction_from_altitude_azimuth,
    normalize_direction,
)


SOLAR_MODULE_PREFIX = "freecad.Solar"
SOLAR_OBJECT_NAME = "SunProperties"


@dataclass(frozen=True)
class SolarDiscoveryResult:
    """Outcome of a non-mutating Solar discovery pass."""

    environment: Optional[SunEnvironment]
    workbench_available: bool
    reason: str
    object_name: str = ""


def solar_workbench_available() -> bool:
    """Return whether the Solar Python package is installed or already loaded."""
    if any(
        name == SOLAR_MODULE_PREFIX or name.startswith(SOLAR_MODULE_PREFIX + ".")
        for name in sys.modules
    ):
        return True
    try:
        return importlib.util.find_spec(SOLAR_MODULE_PREFIX) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def discover_sun_environment(
    document: object,
    availability_probe: Callable[[], bool] = solar_workbench_available,
    allow_below_horizon: bool = False,
) -> SolarDiscoveryResult:
    """Discover a valid static sun without changing the FreeCAD document."""
    available = bool(availability_probe())
    if not available:
        return SolarDiscoveryResult(None, False, "Solar Workbench is not installed")
    if document is None:
        return SolarDiscoveryResult(None, True, "There is no active document")

    candidates = list(_solar_candidates(document))
    if not candidates:
        return SolarDiscoveryResult(
            None,
            True,
            "The active document has no Solar SunProperties object",
        )

    invalid_reasons = []
    for candidate in candidates:
        try:
            environment = _environment_from_object(
                candidate,
                allow_below_horizon=allow_below_horizon,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            invalid_reasons.append(str(exc))
            continue
        return SolarDiscoveryResult(
            environment,
            True,
            "Solar static sun found",
            str(getattr(candidate, "Name", "") or ""),
        )

    reason = invalid_reasons[0] if invalid_reasons else "Solar data is not valid"
    return SolarDiscoveryResult(
        None,
        True,
        reason,
        str(getattr(candidates[0], "Name", "") or ""),
    )


def _solar_candidates(document: object) -> Iterable[object]:
    objects = list(getattr(document, "Objects", ()) or ())
    named = getattr(document, "getObject", None)
    if callable(named):
        exact = named(SOLAR_OBJECT_NAME)
        if exact is not None:
            yield exact
            objects = [obj for obj in objects if obj is not exact]
    for obj in objects:
        if _looks_like_solar_object(obj):
            yield obj


def _looks_like_solar_object(obj: object) -> bool:
    if str(getattr(obj, "Name", "") or "") == SOLAR_OBJECT_NAME:
        return True
    proxy = getattr(obj, "Proxy", None)
    module_name = str(getattr(type(proxy), "__module__", "") or "")
    properties = set(getattr(obj, "PropertiesList", ()) or ())
    return module_name.startswith(SOLAR_MODULE_PREFIX) and (
        "SunLightPosition" in properties or {"Altitude", "Azimuth"}.issubset(properties)
    )


def _environment_from_object(
    obj: object,
    *,
    allow_below_horizon: bool = False,
) -> SunEnvironment:
    altitude = _optional_float(getattr(obj, "Altitude", None))
    azimuth = _optional_float(getattr(obj, "Azimuth", None))
    if altitude is not None and altitude <= 0.0 and not allow_below_horizon:
        raise ValueError("Solar sun is at or below the horizon")

    direction = _direction_from_solar_vector(getattr(obj, "SunLightPosition", None))
    if direction is None:
        if altitude is None or azimuth is None:
            raise ValueError("Solar has neither a valid SunLightPosition nor valid angles")
        direction = direction_from_altitude_azimuth(
            altitude,
            azimuth,
            _optional_float(getattr(obj, "North", 0.0)) or 0.0,
        )

    color = _optional_color(getattr(obj, "SunLightColor", None))
    metadata = _metadata_from_object(obj)
    return SunEnvironment(
        direction_freecad=direction,
        source="Solar Workbench",
        source_object_name=str(getattr(obj, "Name", "") or SOLAR_OBJECT_NAME),
        altitude_deg=altitude,
        azimuth_deg=azimuth,
        color=color,
        metadata=metadata,
    )


def _direction_from_solar_vector(value: object) -> Optional[Tuple[float, float, float]]:
    vector = _vector_components(value)
    if vector is None:
        return None
    try:
        # Solar stores the observer-to-sun position. X3D needs the direction in
        # which the light rays travel, hence the sign reversal.
        return normalize_direction(tuple(-component for component in vector))
    except ValueError:
        return None


def _vector_components(value: object) -> Optional[Tuple[float, float, float]]:
    if value is None:
        return None
    if all(hasattr(value, axis) for axis in ("x", "y", "z")):
        raw = (getattr(value, "x"), getattr(value, "y"), getattr(value, "z"))
    elif isinstance(value, (list, tuple)) and len(value) == 3:
        raw = value
    else:
        return None
    try:
        result = tuple(float(component) for component in raw)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(component) for component in result):
        return None
    return result  # type: ignore[return-value]


def _optional_float(value: object) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _optional_color(value: object) -> Optional[Tuple[float, float, float]]:
    vector = _vector_components(value)
    if vector is None:
        return None
    scale = 255.0 if max(vector) > 1.0 else 1.0
    return tuple(max(0.0, min(1.0, component / scale)) for component in vector)  # type: ignore[return-value]


def _metadata_from_object(obj: object) -> dict:
    field_names = (
        "City",
        "Country",
        "Latitude",
        "Longitude",
        "Elevation",
        "TimeZone",
        "North",
        "Year",
        "Month",
        "Day",
        "Hour",
        "Min",
        "DaylightSaving",
    )
    metadata = {
        name: getattr(obj, name)
        for name in field_names
        if hasattr(obj, name) and getattr(obj, name) is not None
    }
    diagram_position = _vector_components(getattr(obj, "DiagPosition", None))
    if diagram_position is not None:
        metadata["DiagramPositionFreeCAD"] = diagram_position
    diagram_radius = _optional_float(getattr(obj, "Distance", None))
    if diagram_radius is not None and diagram_radius > 0.0:
        metadata["DiagramRadiusMM"] = diagram_radius
    sun_radius = _optional_float(getattr(obj, "Radius", None))
    if sun_radius is not None and sun_radius > 0.0:
        metadata["SunRadiusMM"] = sun_radius
    sun_color = _optional_color(getattr(obj, "SunLightColor", None))
    if sun_color is not None:
        metadata["SunColor"] = sun_color
    diagram_color = _optional_color(getattr(obj, "DiagColor", None))
    if diagram_color is not None:
        metadata["DiagramColor"] = diagram_color
    return metadata


__all__ = [
    "SolarDiscoveryResult",
    "discover_sun_environment",
    "solar_workbench_available",
]
