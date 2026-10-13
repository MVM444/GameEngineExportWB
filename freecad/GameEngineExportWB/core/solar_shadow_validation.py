"""Independent reference geometry for the Solar shadow validation example.

This module intentionally does not import :mod:`core.solar` or the Solar
Workbench adapter.  It is a small reference calculation used to catch sign,
axis, north-rotation and shadow-length regressions in the production path.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Tuple


Vector3 = Tuple[float, float, float]


@dataclass(frozen=True)
class ShadowPreset:
    """One easy-to-inspect solar validation case."""

    key: str
    label: str
    altitude_deg: float
    azimuth_deg: float
    north_deg: float
    expected_shadow_axis: str


PRESETS = (
    ShadowPreset(
        "01_east_alt45",
        "Sol Este 45 deg - sombra Oeste",
        45.0,
        90.0,
        0.0,
        "-X (Oeste)",
    ),
    ShadowPreset(
        "02_south_alt30",
        "Sol Sur 30 deg - sombra Norte",
        30.0,
        180.0,
        0.0,
        "+Y (Norte)",
    ),
    ShadowPreset(
        "03_west_alt60",
        "Sol Oeste 60 deg - sombra Este",
        60.0,
        270.0,
        0.0,
        "+X (Este)",
    ),
    ShadowPreset(
        "04_rotated_north_alt30",
        "Azimut 315 + Norte 45 - sombra Sur",
        30.0,
        315.0,
        45.0,
        "-Y (Sur)",
    ),
)


def observer_to_sun_vector(
    altitude_deg: float,
    azimuth_deg: float,
    north_deg: float,
) -> Vector3:
    """Calculate the observer-to-sun unit vector without production helpers.

    Solar azimuth is clockwise from its configured north.  FreeCAD model north
    is +Y, east is +X and up is +Z.
    """
    altitude = _checked_altitude(altitude_deg)
    model_azimuth = math.radians(float(azimuth_deg) + float(north_deg))
    horizontal = math.cos(altitude)
    return (
        horizontal * math.sin(model_azimuth),
        horizontal * math.cos(model_azimuth),
        math.sin(altitude),
    )


def theoretical_shadow_endpoint(
    pole_height: float,
    altitude_deg: float,
    azimuth_deg: float,
    north_deg: float,
) -> Vector3:
    """Return a ground-plane shadow endpoint from the independent formula."""
    height = _checked_height(pole_height)
    altitude = _checked_altitude(altitude_deg)
    model_azimuth = math.radians(float(azimuth_deg) + float(north_deg))
    shadow_length = height / math.tan(altitude)
    return (
        -math.sin(model_azimuth) * shadow_length,
        -math.cos(model_azimuth) * shadow_length,
        0.0,
    )


def ray_shadow_endpoint(
    pole_height: float,
    light_ray_direction: Vector3,
) -> Vector3:
    """Intersect the production light-ray direction with the Z=0 plane."""
    height = _checked_height(pole_height)
    try:
        x_value, y_value, z_value = (
            float(light_ray_direction[0]),
            float(light_ray_direction[1]),
            float(light_ray_direction[2]),
        )
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError("Light direction must contain three finite coordinates") from exc
    if not all(math.isfinite(value) for value in (x_value, y_value, z_value)):
        raise ValueError("Light direction must contain three finite coordinates")
    if z_value >= -1e-9:
        raise ValueError("Light ray must point down toward the ground plane")
    parameter = -height / z_value
    return (parameter * x_value, parameter * y_value, 0.0)


def horizontal_length(vector: Vector3) -> float:
    """Return the XY length of a vector or endpoint."""
    return math.hypot(float(vector[0]), float(vector[1]))


def _checked_height(value: float) -> float:
    height = float(value)
    if not math.isfinite(height) or height <= 0.0:
        raise ValueError("Pole height must be a positive finite value")
    return height


def _checked_altitude(value: float) -> float:
    altitude_deg = float(value)
    if not math.isfinite(altitude_deg) or not 0.0 < altitude_deg < 90.0:
        raise ValueError("Solar altitude must be strictly between 0 and 90 degrees")
    return math.radians(altitude_deg)


__all__ = [
    "PRESETS",
    "ShadowPreset",
    "horizontal_length",
    "observer_to_sun_vector",
    "ray_shadow_endpoint",
    "theoretical_shadow_endpoint",
]
