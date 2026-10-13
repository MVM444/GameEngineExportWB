"""FreeCADCmd smoke test for the optional static Solar adapter."""

from __future__ import annotations

import math
from pathlib import Path
import sys

import FreeCAD

try:
    DEV_REPO_ROOT = str(Path(__file__).resolve().parents[1])
except NameError:
    # FreeCADCmd console ``exec`` does not define __file__.
    DEV_REPO_ROOT = str(Path.cwd())
if DEV_REPO_ROOT in sys.path:
    sys.path.remove(DEV_REPO_ROOT)
sys.path.insert(0, DEV_REPO_ROOT)

from freecad.GameEngineExportWB.adapters import solar_adapter
from freecad.GameEngineExportWB.core import solar


def main() -> None:
    document = FreeCAD.newDocument("GEE_SolarAdapterSmoke")
    try:
        sun = document.addObject("App::FeaturePython", "SunProperties")
        sun.addProperty("App::PropertyVector", "SunLightPosition")
        sun.addProperty("App::PropertyFloat", "Altitude")
        sun.addProperty("App::PropertyFloat", "Azimuth")
        sun.addProperty("App::PropertyAngle", "North")
        sun.addProperty("App::PropertyVector", "DiagPosition")
        sun.addProperty("App::PropertyLength", "Distance")
        sun.addProperty("App::PropertyLength", "Radius")
        sun.addProperty("App::PropertyColor", "SunLightColor")
        sun.addProperty("App::PropertyColor", "DiagColor")
        for name in ("Year", "Month", "Day", "Hour"):
            sun.addProperty("App::PropertyInteger", name)
        sun.addProperty("App::PropertyFloat", "Latitude")
        sun.addProperty("App::PropertyFloat", "Longitude")
        sun.addProperty("App::PropertyInteger", "TimeZone")
        sun.addProperty("App::PropertyBool", "DaylightSaving")
        sun.SunLightPosition = FreeCAD.Vector(100.0, 0.0, 100.0)
        sun.Altitude = 45.0
        sun.Azimuth = 90.0
        sun.North = 0.0
        sun.DiagPosition = FreeCAD.Vector(1000.0, 2000.0, 300.0)
        sun.Distance = 30000.0
        sun.Radius = 700.0
        sun.SunLightColor = (1.0, 0.8, 0.0)
        sun.DiagColor = (0.2, 0.4, 0.8)
        sun.Latitude = 9.9281
        sun.Longitude = -84.0907
        sun.TimeZone = -6
        sun.Year = 2026
        sun.Month = 3
        sun.Day = 21
        sun.Hour = 12
        sun.DaylightSaving = False

        result = solar_adapter.discover_sun_environment(
            document, availability_probe=lambda: True
        )
        assert result.environment is not None
        direction = result.environment.direction_freecad
        assert math.isclose(direction[0], -math.sqrt(0.5), abs_tol=1e-9)
        assert math.isclose(direction[1], 0.0, abs_tol=1e-9)
        assert math.isclose(direction[2], -math.sqrt(0.5), abs_tol=1e-9)
        control = solar.interactive_sun_control_config(result.environment)
        assert control["visualization"]["center_freecad_mm"] == (
            1000.0,
            2000.0,
            300.0,
        )
        assert control["visualization"]["radius_mm"] == 30000.0

        unavailable = solar_adapter.discover_sun_environment(
            document, availability_probe=lambda: False
        )
        assert unavailable.environment is None
        FreeCAD.Console.PrintMessage("[GAMEEXPORT] Solar adapter FreeCAD smoke: PASS\n")
        print("[GAMEEXPORT] Solar adapter FreeCAD smoke: PASS")
    finally:
        FreeCAD.closeDocument(document.Name)


if __name__ == "__main__":
    main()
