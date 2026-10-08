"""Tests for the CastleScript day/year solar controller."""

from __future__ import annotations

import math
import unittest
import xml.etree.ElementTree as ET

from freecad.GameEngineExportWB.core import exporter_x3d
from freecad.GameEngineExportWB.core import solar


def _lighting_config():
    return {
        "global": {
            "enabled": True,
            "direction_freecad": (0.1, 0.2, -0.9),
            "intensity": 1.2,
            "ambient_intensity": 0.12,
            "shadows": True,
            "interactive_solar": {
                "enabled": True,
                "year": 2026,
                "days_in_year": 365,
                "initial_day_of_year": 80,
                "initial_hour": 12,
                "latitude_deg": 9.9281,
                "longitude_deg": -84.0907,
                "timezone_hours": -6.0,
                "north_deg": 0.0,
                "day_step": 1,
                "week_step_days": 7,
                "visualization": {
                    "enabled": True,
                    "center_freecad_mm": (1000.0, 2000.0, 300.0),
                    "radius_mm": 30000.0,
                    "sun_radius_mm": 700.0,
                    "sun_color": (1.0, 0.8, 0.0),
                    "diagram_color": (0.2, 0.4, 0.8),
                },
            },
        }
    }


class InteractiveSolarX3DTests(unittest.TestCase):
    def test_shadow_projection_uses_freecad_geometry_bounds(self):
        scene = ET.Element("Scene")
        transform = ET.SubElement(
            scene,
            "Transform",
            {"DEF": "FreeCAD_mm_to_m"},
        )
        shape = ET.SubElement(transform, "Shape")
        geometry = ET.SubElement(shape, "IndexedFaceSet")
        ET.SubElement(
            geometry,
            "Coordinate",
            {"point": "0 0 0, 2000 4000 6000"},
        )

        projection = exporter_x3d._solar_shadow_projection_config(
            scene,
            lambda tag: tag,
            {"center_x3d_m": (50.0, 50.0, 50.0), "radius_m": 30.0},
        )

        self.assertEqual((1.0, 3.0, -2.0), projection["center"])
        expected_radius = math.sqrt(14.0) * 1.15 + 0.25
        self.assertAlmostEqual(expected_radius, projection["radius"])
        self.assertAlmostEqual(expected_radius * 2.0, projection["distance"])
        self.assertAlmostEqual(expected_radius, projection["near"])
        self.assertAlmostEqual(expected_radius * 3.0, projection["far"])

    def test_initial_light_matches_controller_state_before_castle_load(self):
        scene = ET.Element("Scene")
        light = exporter_x3d._make_directional_light(
            lambda tag: tag,
            _lighting_config()["global"],
        )
        scene.append(light)

        self.assertTrue(
            exporter_x3d._insert_interactive_solar_controller(
                scene,
                lambda tag: tag,
                _lighting_config(),
            )
        )

        config = _lighting_config()["global"]["interactive_solar"]
        sun = solar.approximate_sun_position(
            config["initial_day_of_year"],
            config["initial_hour"],
            config["latitude_deg"],
            config["longitude_deg"],
            config["timezone_hours"],
            config["north_deg"],
        )
        expected_direction = (-sun[0], -sun[2], sun[1])
        actual_direction = tuple(float(value) for value in light.attrib["direction"].split())
        for actual, expected in zip(actual_direction, expected_direction):
            self.assertAlmostEqual(expected, actual, places=6)
        self.assertGreater(float(light.attrib["intensity"]), 0.0)

        location = tuple(
            float(value) for value in light.attrib["projectionLocation"].split()
        )
        direction_to_center = tuple(-value for value in expected_direction)
        displacement = tuple(location[index] - value for index, value in enumerate((1.0, 0.3, -2.0)))
        self.assertGreater(
            sum(displacement[index] * direction_to_center[index] for index in range(3)),
            0.0,
        )

        up = tuple(float(value) for value in light.attrib["up"].split())
        self.assertAlmostEqual(
            0.0,
            sum(up[index] * expected_direction[index] for index in range(3)),
            places=5,
        )

    def test_controller_routes_keys_to_directional_light_and_hud(self):
        scene = ET.Element("Scene")
        scene.append(
            exporter_x3d._make_directional_light(
                lambda tag: tag,
                _lighting_config()["global"],
            )
        )

        inserted = exporter_x3d._insert_interactive_solar_controller(
            scene,
            lambda tag: tag,
            _lighting_config(),
        )

        self.assertTrue(inserted)
        defs = {node.attrib.get("DEF") for node in scene.iter() if node.attrib.get("DEF")}
        self.assertIn("GameExport_SolarKeySensor", defs)
        self.assertIn("GameExport_SolarController", defs)
        self.assertIn("GameExport_SolarCalculator", defs)
        self.assertIn("GameExport_SolarHUDText", defs)
        self.assertIn("GameExport_SolarVisualizationSwitch", defs)
        self.assertIn("GameExport_SolarSunTransform", defs)
        self.assertIn("GameExport_SolarSunMaterial", defs)
        self.assertIn("GameExport_SolarRayTransform", defs)
        self.assertIn("GameExport_SolarRayMaterial", defs)
        self.assertIn("GameExport_SolarHUDCompass", defs)
        self.assertIn("GameExport_SolarHUDCompassDial", defs)
        self.assertIn("GameExport_SolarHUDCompassScript", defs)

        routes = {
            (
                node.attrib.get("fromNode"),
                node.attrib.get("fromField"),
                node.attrib.get("toNode"),
                node.attrib.get("toField"),
            )
            for node in scene.findall("ROUTE")
        }
        self.assertIn(
            (
                "GameExport_SolarCalculator",
                "direction_changed",
                "GameExport_SunLight",
                "direction",
            ),
            routes,
        )
        self.assertIn(
            (
                "GameExport_SolarCalculator",
                "shadow_projection_location_changed",
                "GameExport_SunLight",
                "projectionLocation",
            ),
            routes,
        )
        self.assertIn(
            (
                "GameExport_SolarCalculator",
                "shadow_up_changed",
                "GameExport_SunLight",
                "up",
            ),
            routes,
        )
        self.assertIn(
            (
                "GameExport_SolarCalculator",
                "shadow_near_changed",
                "GameExport_SunLight",
                "projectionNear",
            ),
            routes,
        )
        self.assertIn(
            (
                "GameExport_SolarCalculator",
                "shadow_far_changed",
                "GameExport_SunLight",
                "projectionFar",
            ),
            routes,
        )
        self.assertIn(
            (
                "GameExport_SolarController",
                "label_changed",
                "GameExport_SolarHUDText",
                "string",
            ),
            routes,
        )
        self.assertIn(
            (
                "GameExport_SolarHUDSensor",
                "orientation_changed",
                "GameExport_SolarHUDCompassScript",
                "camera_orientation",
            ),
            routes,
        )
        self.assertIn(
            (
                "GameExport_SolarHUDCompassScript",
                "rotation_changed",
                "GameExport_SolarHUDCompassDial",
                "rotation",
            ),
            routes,
        )
        self.assertIn(
            (
                "GameExport_SolarCalculator",
                "sun_position_changed",
                "GameExport_SolarSunTransform",
                "translation",
            ),
            routes,
        )
        self.assertIn(
            (
                "GameExport_SolarCalculator",
                "ray_translation_changed",
                "GameExport_SolarRayTransform",
                "translation",
            ),
            routes,
        )
        self.assertIn(
            (
                "GameExport_SolarCalculator",
                "ray_rotation_changed",
                "GameExport_SolarRayTransform",
                "rotation",
            ),
            routes,
        )
        self.assertIn(
            (
                "GameExport_SolarController",
                "diagram_changed",
                "GameExport_SolarVisualizationSwitch",
                "whichChoice",
            ),
            routes,
        )

        controller = next(
            node
            for node in scene.findall("Script")
            if node.attrib.get("DEF") == "GameExport_SolarController"
        )
        script = controller.attrib["url"]
        self.assertIn("SOLAR ", script)
        self.assertIn("week_step", script)
        self.assertIn("state_changed", script)

        hud_help = next(
            node
            for node in scene.iter()
            if node.attrib.get("DEF") == "GameExport_SolarHUDHelp"
        )
        self.assertIn("J/L  HORA", hud_help.attrib["string"])
        self.assertIn("C  DIAGRAMA", hud_help.attrib["string"])

        compass_script = next(
            node
            for node in scene.findall("Script")
            if node.attrib.get("DEF") == "GameExport_SolarHUDCompassScript"
        )
        self.assertIn("orientation_to_direction", compass_script.attrib["url"])
        self.assertIn("rotation_changed", compass_script.attrib["url"])

        calculator_script = next(
            node
            for node in scene.findall("Script")
            if node.attrib.get("DEF") == "GameExport_SolarCalculator"
        )
        self.assertIn("orientation_from_direction_up", calculator_script.attrib["url"])
        self.assertIn("ray_translation_changed", calculator_script.attrib["url"])
        self.assertIn(
            "shadow_projection_location_changed",
            calculator_script.attrib["url"],
        )
        self.assertIn("shadow_up_changed", calculator_script.attrib["url"])
        self.assertIn("shadow_near_changed", calculator_script.attrib["url"])
        self.assertIn("shadow_far_changed", calculator_script.attrib["url"])

        light = next(
            node
            for node in scene.iter()
            if node.attrib.get("DEF") == "GameExport_SunLight"
        )
        self.assertIn("projectionLocation", light.attrib)
        self.assertIn("projectionRectangle", light.attrib)
        self.assertIn("projectionNear", light.attrib)
        self.assertIn("projectionFar", light.attrib)
        self.assertIn("up", light.attrib)
        self.assertLess(float(light.attrib["projectionNear"]), float(light.attrib["projectionFar"]))

        hud_panel = next(
            node
            for node in scene.iter()
            if node.attrib.get("DEF") == "GameExport_SolarHUDPanel"
        )
        panel_translation = tuple(
            float(value) for value in hud_panel.attrib["translation"].split()
        )
        self.assertGreater(panel_translation[2], -0.2)
        self.assertLess(panel_translation[2], -0.05)
        self.assertLess(panel_translation[0], -0.12)
        self.assertGreater(panel_translation[1], 0.08)
        panel_scale = tuple(float(value) for value in hud_panel.attrib["scale"].split())
        self.assertEqual((0.04125, 0.04125, 0.04125), panel_scale)

        hud_compass = next(
            node
            for node in scene.iter()
            if node.attrib.get("DEF") == "GameExport_SolarHUDCompass"
        )
        compass_translation = tuple(
            float(value) for value in hud_compass.attrib["translation"].split()
        )
        compass_scale = tuple(
            float(value) for value in hud_compass.attrib["scale"].split()
        )
        self.assertGreater(compass_translation[0], 0.11)
        self.assertGreater(compass_translation[1], 0.08)
        self.assertEqual((0.010875, 0.010875, 0.010875), compass_scale)

        self.assertGreaterEqual(
            sum(1 for node in scene.iter() if node.tag == "UnlitMaterial"),
            10,
        )
        self.assertGreaterEqual(
            sum(1 for node in scene.iter() if node.tag == "LineProperties"),
            3,
        )

        root = next(
            node
            for node in scene.iter()
            if node.attrib.get("DEF") == "GameExport_SolarVisualizationRoot"
        )
        self.assertEqual(
            (1.0, 0.3, -2.0),
            tuple(float(value) for value in root.attrib["translation"].split()),
        )
        self.assertGreaterEqual(
            sum(1 for node in scene.iter() if node.tag == "IndexedLineSet"),
            4,
        )
        self.assertEqual(1, sum(1 for node in scene.iter() if node.tag == "Cylinder"))
        self.assertEqual(1, sum(1 for node in scene.iter() if node.tag == "Cone"))

    def test_controller_cleanup_is_idempotent(self):
        scene = ET.Element("Scene")
        scene.append(
            exporter_x3d._make_directional_light(
                lambda tag: tag,
                _lighting_config()["global"],
            )
        )
        exporter_x3d._insert_interactive_solar_controller(
            scene,
            lambda tag: tag,
            _lighting_config(),
        )

        exporter_x3d._remove_interactive_solar_nodes(scene)

        self.assertFalse(
            any(
                str(node.attrib.get("DEF", "")).startswith("GameExport_Solar")
                for node in scene.iter()
            )
        )
        self.assertFalse(
            any(
                str(node.attrib.get("fromNode", "")).startswith("GameExport_Solar")
                or str(node.attrib.get("toNode", "")).startswith("GameExport_Solar")
                for node in scene.iter()
            )
        )


if __name__ == "__main__":
    unittest.main()
