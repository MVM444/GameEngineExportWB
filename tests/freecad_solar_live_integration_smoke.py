"""FreeCADCmd smoke test using the installed Solar Workbench implementation."""

from __future__ import annotations

import math
from pathlib import Path
import sys

import FreeCAD
import FreeCADGui

if not hasattr(FreeCADGui, "addLanguagePath"):
    # FreeCADCmd omits this GUI-only registration helper. Solar uses it at
    # import time, but it is unrelated to solar-position calculations.
    FreeCADGui.addLanguagePath = lambda _path: None

try:
    DEV_REPO_ROOT = str(Path(__file__).resolve().parents[1])
except NameError:
    DEV_REPO_ROOT = str(Path.cwd())
if DEV_REPO_ROOT in sys.path:
    sys.path.remove(DEV_REPO_ROOT)
sys.path.insert(0, DEV_REPO_ROOT)

from freecad.GameEngineExportWB.adapters import solar_adapter
from freecad.Solar import SunProperties as solar_properties


def main() -> None:
    document = FreeCAD.newDocument("GEE_SolarLiveIntegrationSmoke")
    try:
        sun = document.addObject("App::DocumentObjectGroupPython", "SunProperties")
        solar_properties.SunProperties(sun)
        sun.City = "San Jose"
        sun.Country = "CR"
        sun.Latitude = 9.9281
        sun.Longitude = -84.0907
        sun.Elevation = 1172.0
        sun.TimeZone = -6
        sun.North = 0.0
        sun.Year = 2026
        sun.Month = 3
        sun.Day = 21
        sun.Hour = 12
        sun.Min = 0
        sun.DaylightSaving = False

        solar_properties.get_sun_position(sun)
        result = solar_adapter.discover_sun_environment(document)
        assert result.workbench_available
        assert result.environment is not None, result.reason
        assert result.environment.altitude_deg is not None
        assert result.environment.altitude_deg > 0.0
        direction = result.environment.direction_freecad
        assert math.isclose(
            math.sqrt(sum(component * component for component in direction)),
            1.0,
            abs_tol=1e-9,
        )
        assert direction[2] < 0.0
        print(
            "[GAMEEXPORT] Solar live integration smoke: PASS "
            f"altitude={result.environment.altitude_deg:.3f} "
            f"azimuth={result.environment.azimuth_deg:.3f} "
            f"direction={direction}"
        )
    finally:
        FreeCAD.closeDocument(document.Name)


if __name__ == "__main__":
    main()
