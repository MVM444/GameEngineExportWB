"""Neutral solar environment model used by Game Engine Export.

This module deliberately has no dependency on FreeCAD, Ladybug or the Solar
Workbench. Optional integrations translate their data into ``SunEnvironment``
before the exporter sees it.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
import datetime
import math
from typing import Dict, Mapping, Optional, Tuple


Vector3 = Tuple[float, float, float]


def normalize_direction(value: object) -> Vector3:
    """Return a finite unit vector or raise ``ValueError``."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("A solar direction must contain three coordinates")
    vector = tuple(float(component) for component in value)
    if not all(math.isfinite(component) for component in vector):
        raise ValueError("A solar direction must contain finite coordinates")
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 1e-9:
        raise ValueError("A solar direction cannot be a null vector")
    return tuple(component / length for component in vector)  # type: ignore[return-value]


def direction_from_altitude_azimuth(
    altitude_deg: float,
    azimuth_deg: float,
    north_deg: float = 0.0,
) -> Vector3:
    """Return the FreeCAD light-ray direction from Solar-style angles.

    Solar/Ladybug azimuth is clockwise from model north (+Y). ``north_deg``
    rotates that north direction clockwise in the model. The returned vector
    points from the sun towards the scene, which is the convention used by an
    X3D ``DirectionalLight``.
    """
    altitude = math.radians(float(altitude_deg))
    azimuth = math.radians(float(azimuth_deg) + float(north_deg))
    horizontal = math.cos(altitude)
    toward_sun = (
        horizontal * math.sin(azimuth),
        horizontal * math.cos(azimuth),
        math.sin(altitude),
    )
    return normalize_direction(tuple(-component for component in toward_sun))


def direction_to_yaw_pitch(direction_freecad: object) -> Tuple[float, float]:
    """Convert a FreeCAD light-ray direction to the panel yaw/pitch values."""
    x_value, y_value, z_value = normalize_direction(direction_freecad)
    yaw = math.degrees(math.atan2(x_value, -y_value))
    yaw = ((yaw + 180.0) % 360.0) - 180.0
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, z_value))))
    return yaw, pitch


@dataclass(frozen=True)
class SunEnvironment:
    """Renderer-neutral description of one static sun state."""

    direction_freecad: Vector3
    source: str
    source_object_name: str = ""
    altitude_deg: Optional[float] = None
    azimuth_deg: Optional[float] = None
    color: Optional[Vector3] = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction_freecad", normalize_direction(self.direction_freecad))
        if self.color is not None:
            color = tuple(max(0.0, min(1.0, float(value))) for value in self.color)
            object.__setattr__(self, "color", color)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_directional_light_config(self, include_color: bool = False) -> Dict[str, object]:
        """Return the neutral fields understood by the X3D exporter."""
        result: Dict[str, object] = {
            "direction_freecad": self.direction_freecad,
            "environment_source": self.source,
            "environment_source_object": self.source_object_name,
        }
        if self.altitude_deg is not None:
            result["solar_altitude_deg"] = float(self.altitude_deg)
        if self.azimuth_deg is not None:
            result["solar_azimuth_deg"] = float(self.azimuth_deg)
        if self.metadata:
            result["environment_metadata"] = dict(self.metadata)
        if include_color and self.color is not None:
            result["color"] = self.color
        return result


def interactive_sun_control_config(
    environment: SunEnvironment,
    *,
    week_step_days: int = 7,
) -> Dict[str, object]:
    """Build renderer-neutral inputs for an in-game solar controller.

    The generated X3D performs the inexpensive sun-position approximation at
    runtime. FreeCAD and Solar remain the source of location, calendar and
    model-north metadata, but neither is required after export.
    """
    metadata = dict(environment.metadata)
    latitude = _metadata_float(metadata, "Latitude")
    longitude = _metadata_float(metadata, "Longitude")
    timezone_hours = _metadata_float(metadata, "TimeZone")
    north_deg = _metadata_float(metadata, "North", default=0.0)
    if bool(metadata.get("DaylightSaving", False)):
        timezone_hours += 1.0

    year = _metadata_int(metadata, "Year")
    month = _metadata_int(metadata, "Month")
    day = _metadata_int(metadata, "Day")
    hour = _metadata_int(metadata, "Hour", default=12)
    try:
        selected_date = datetime.date(year, month, day)
    except ValueError as exc:
        raise ValueError("Solar calendar date is not valid") from exc

    if not -90.0 <= latitude <= 90.0:
        raise ValueError("Solar latitude must be between -90 and 90 degrees")
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("Solar longitude must be between -180 and 180 degrees")
    if not -14.0 <= timezone_hours <= 14.0:
        raise ValueError("Solar time zone must be between -14 and 14 hours")

    return {
        "enabled": True,
        "year": year,
        "days_in_year": 366 if calendar.isleap(year) else 365,
        "initial_day_of_year": selected_date.timetuple().tm_yday,
        "initial_hour": max(0, min(23, hour)),
        "latitude_deg": latitude,
        "longitude_deg": longitude,
        "timezone_hours": timezone_hours,
        "north_deg": north_deg,
        "day_step": 1,
        "week_step_days": max(1, min(31, int(week_step_days))),
        "visualization": {
            "enabled": True,
            "center_freecad_mm": _metadata_vector3(
                metadata,
                "DiagramPositionFreeCAD",
                default=(0.0, 0.0, 0.0),
            ),
            "radius_mm": max(
                1000.0,
                min(
                    1000000.0,
                    _metadata_float(metadata, "DiagramRadiusMM", default=30000.0),
                ),
            ),
            "sun_radius_mm": max(
                50.0,
                min(
                    100000.0,
                    _metadata_float(metadata, "SunRadiusMM", default=700.0),
                ),
            ),
            "sun_color": _metadata_color3(
                metadata,
                "SunColor",
                default=(1.0, 0.82, 0.08),
            ),
            "diagram_color": _metadata_color3(
                metadata,
                "DiagramColor",
                default=(0.25, 0.45, 0.85),
            ),
        },
    }


def approximate_sun_position(
    day_of_year: float,
    hour: float,
    latitude_deg: float,
    longitude_deg: float,
    timezone_hours: float,
    north_deg: float = 0.0,
) -> Vector3:
    """Return the observer-to-sun unit vector in FreeCAD coordinates.

    This intentionally mirrors the lightweight calculation embedded in the
    exported CastleScript controller.  The vector uses FreeCAD axes: X is
    model east, Y is model north and Z is up.  ``north_deg`` rotates true
    north clockwise in the model, matching Solar Workbench.
    """
    day = float(day_of_year)
    local_hour = float(hour)
    latitude = math.radians(float(latitude_deg))
    north = math.radians(float(north_deg))
    b_angle = (2.0 * math.pi / 365.0) * (day - 81.0)
    equation_time = (
        9.87 * math.sin(2.0 * b_angle)
        - 7.53 * math.cos(b_angle)
        - 1.5 * math.sin(b_angle)
    )
    declination = math.radians(23.45) * math.sin(
        (2.0 * math.pi / 365.0) * (284.0 + day)
    )
    solar_minutes = (
        local_hour * 60.0
        + equation_time
        + 4.0 * (float(longitude_deg) - 15.0 * float(timezone_hours))
    )
    hour_angle = math.radians(15.0) * (solar_minutes / 60.0 - 12.0)
    true_east = -math.cos(declination) * math.sin(hour_angle)
    true_north = (
        math.cos(latitude) * math.sin(declination)
        - math.sin(latitude) * math.cos(declination) * math.cos(hour_angle)
    )
    up = (
        math.sin(latitude) * math.sin(declination)
        + math.cos(latitude) * math.cos(declination) * math.cos(hour_angle)
    )
    model_east = true_east * math.cos(north) + true_north * math.sin(north)
    model_north = -true_east * math.sin(north) + true_north * math.cos(north)
    return normalize_direction((model_east, model_north, up))


def _metadata_float(
    metadata: Mapping[str, object],
    name: str,
    *,
    default: Optional[float] = None,
) -> float:
    value = metadata.get(name, default)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Solar metadata is missing " + name) from exc
    if not math.isfinite(result):
        raise ValueError("Solar metadata is not finite: " + name)
    return result


def _metadata_int(
    metadata: Mapping[str, object],
    name: str,
    *,
    default: Optional[int] = None,
) -> int:
    value = metadata.get(name, default)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Solar metadata is missing " + name) from exc


def _metadata_vector3(
    metadata: Mapping[str, object],
    name: str,
    *,
    default: Vector3,
) -> Vector3:
    value = metadata.get(name, default)
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return default
    try:
        vector = tuple(float(component) for component in value)
    except (TypeError, ValueError):
        return default
    if not all(math.isfinite(component) for component in vector):
        return default
    return vector  # type: ignore[return-value]


def _metadata_color3(
    metadata: Mapping[str, object],
    name: str,
    *,
    default: Vector3,
) -> Vector3:
    value = _metadata_vector3(metadata, name, default=default)
    return tuple(max(0.0, min(1.0, component)) for component in value)  # type: ignore[return-value]


__all__ = [
    "SunEnvironment",
    "direction_from_altitude_azimuth",
    "direction_to_yaw_pitch",
    "approximate_sun_position",
    "interactive_sun_control_config",
    "normalize_direction",
]
