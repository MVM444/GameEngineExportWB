"""Tests for the optional Solar Workbench adapter."""

from __future__ import annotations

import math
import types
import unittest

from freecad.GameEngineExportWB.adapters import solar_adapter
from freecad.GameEngineExportWB.core import exporter_x3d, solar


class _Document:
    def __init__(self, objects):
        self.Objects = list(objects)

    def getObject(self, name):
        for obj in self.Objects:
            if getattr(obj, "Name", "") == name:
                return obj
        return None


def _solar_object(**overrides):
    values = {
        "Name": "SunProperties",
        "PropertiesList": [
            "SunLightPosition",
            "Altitude",
            "Azimuth",
            "North",
        ],
        "SunLightPosition": types.SimpleNamespace(x=10.0, y=0.0, z=10.0),
        "Altitude": 45.0,
        "Azimuth": 90.0,
        "North": 0.0,
        "City": "San Jose",
        "DiagPosition": types.SimpleNamespace(x=1000.0, y=2000.0, z=300.0),
        "Distance": 30000.0,
        "Radius": 700.0,
        "SunLightColor": (255.0, 204.0, 0.0),
        "DiagColor": (64.0, 96.0, 192.0),
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


class SolarAdapterTests(unittest.TestCase):
    def test_missing_workbench_keeps_adapter_inactive(self):
        result = solar_adapter.discover_sun_environment(
            _Document([_solar_object()]), availability_probe=lambda: False
        )

        self.assertIsNone(result.environment)
        self.assertFalse(result.workbench_available)

    def test_reads_persisted_solar_vector_without_importing_solar(self):
        result = solar_adapter.discover_sun_environment(
            _Document([_solar_object()]), availability_probe=lambda: True
        )

        self.assertIsNotNone(result.environment)
        self.assertEqual("Solar Workbench", result.environment.source)
        self.assertAlmostEqual(-math.sqrt(0.5), result.environment.direction_freecad[0])
        self.assertAlmostEqual(0.0, result.environment.direction_freecad[1])
        self.assertAlmostEqual(-math.sqrt(0.5), result.environment.direction_freecad[2])
        self.assertEqual("San Jose", result.environment.metadata["City"])
        self.assertEqual(
            (1000.0, 2000.0, 300.0),
            result.environment.metadata["DiagramPositionFreeCAD"],
        )
        self.assertEqual(30000.0, result.environment.metadata["DiagramRadiusMM"])

    def test_falls_back_to_altitude_azimuth_when_vector_is_null(self):
        obj = _solar_object(
            SunLightPosition=(0.0, 0.0, 0.0),
            Altitude=30.0,
            Azimuth=90.0,
        )
        result = solar_adapter.discover_sun_environment(
            _Document([obj]), availability_probe=lambda: True
        )

        self.assertIsNotNone(result.environment)
        expected = solar.direction_from_altitude_azimuth(30.0, 90.0)
        for actual, wanted in zip(result.environment.direction_freecad, expected):
            self.assertAlmostEqual(wanted, actual)

    def test_rejects_sun_below_horizon(self):
        result = solar_adapter.discover_sun_environment(
            _Document([_solar_object(Altitude=-2.0)]), availability_probe=lambda: True
        )

        self.assertIsNone(result.environment)
        self.assertIn("horizon", result.reason)

    def test_interactive_control_can_start_below_horizon(self):
        result = solar_adapter.discover_sun_environment(
            _Document([_solar_object(Altitude=-2.0)]),
            availability_probe=lambda: True,
            allow_below_horizon=True,
        )

        self.assertIsNotNone(result.environment)
        self.assertEqual(-2.0, result.environment.altitude_deg)

    def test_exporter_prefers_neutral_direction_over_manual_angles(self):
        node = exporter_x3d._make_directional_light(
            lambda tag: tag,
            {
                "direction_freecad": (-1.0, 0.0, -1.0),
                "yaw": 0.0,
                "pitch": 0.0,
            },
        )

        direction = tuple(float(value) for value in node.attrib["direction"].split())
        self.assertAlmostEqual(-math.sqrt(0.5), direction[0], places=6)
        self.assertAlmostEqual(-math.sqrt(0.5), direction[1], places=6)
        self.assertAlmostEqual(0.0, direction[2], places=6)

    def test_interactive_control_uses_solar_calendar_and_location(self):
        environment = solar.SunEnvironment(
            direction_freecad=(0.0, 0.0, -1.0),
            source="Solar Workbench",
            metadata={
                "Latitude": 9.9281,
                "Longitude": -84.0907,
                "TimeZone": -6,
                "North": 12.0,
                "Year": 2026,
                "Month": 3,
                "Day": 21,
                "Hour": 14,
                "DaylightSaving": False,
                "DiagramPositionFreeCAD": (1000.0, 2000.0, 300.0),
                "DiagramRadiusMM": 25000.0,
                "SunRadiusMM": 600.0,
                "SunColor": (1.0, 0.8, 0.0),
                "DiagramColor": (0.2, 0.3, 0.7),
            },
        )

        config = solar.interactive_sun_control_config(environment)

        self.assertTrue(config["enabled"])
        self.assertEqual(2026, config["year"])
        self.assertEqual(365, config["days_in_year"])
        self.assertEqual(80, config["initial_day_of_year"])
        self.assertEqual(14, config["initial_hour"])
        self.assertEqual(7, config["week_step_days"])
        self.assertEqual(
            (1000.0, 2000.0, 300.0),
            config["visualization"]["center_freecad_mm"],
        )
        self.assertEqual(25000.0, config["visualization"]["radius_mm"])

    def test_approximate_sun_position_is_above_horizon_at_local_noon(self):
        position = solar.approximate_sun_position(
            80,
            12.0,
            9.9281,
            -84.0907,
            -6.0,
        )

        self.assertAlmostEqual(1.0, math.sqrt(sum(value * value for value in position)))
        self.assertGreater(position[2], 0.8)

    def test_interactive_control_requires_complete_solar_metadata(self):
        environment = solar.SunEnvironment(
            direction_freecad=(0.0, 0.0, -1.0),
            source="Solar Workbench",
            metadata={"Year": 2026, "Month": 3, "Day": 21},
        )

        with self.assertRaisesRegex(ValueError, "Latitude"):
            solar.interactive_sun_control_config(environment)


if __name__ == "__main__":
    unittest.main()
