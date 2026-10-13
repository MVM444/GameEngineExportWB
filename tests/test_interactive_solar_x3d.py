"""Tests for the CastleScript day/year solar controller."""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import xml.etree.ElementTree as ET

from freecad.GameEngineExportWB.core import exporter_x3d
from freecad.GameEngineExportWB.core import solar


class SolarSnapshotFilterTests(unittest.TestCase):
    def test_export_filters_only_when_interactive_solar_is_enabled(self):
        owner = SimpleNamespace(Proxy=type("SunProperties", (), {
            "__module__": "freecad.Solar.SunProperties"})(), Group=[])
        sphere = SimpleNamespace(Name="SunLight", TypeId="Part::Sphere", InList=[owner])
        owner.Group = [sphere]
        building = SimpleNamespace(Name="Building")
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, {
            "FreeCAD": SimpleNamespace(), "FreeCADGui": SimpleNamespace()}):
            for enabled in (False, True):
                config = {"global": {"enabled": True, "interactive_solar": {"enabled": enabled}}}
                with patch.object(exporter_x3d, "diagnose_export_candidates", side_effect=RuntimeError("stop")) as diagnose:
                    with self.assertRaisesRegex(RuntimeError, "stop"):
                        exporter_x3d.export_to_x3d([building, sphere], Path(tmp)/"test.x3d", lighting_cfg=config)
                    self.assertEqual([building] if enabled else [building, sphere], diagnose.call_args.args[0])

    def test_requires_real_solar_ownership_and_specific_helper_name(self):
        owner = SimpleNamespace(Proxy=type("SunProperties", (), {
            "__module__": "freecad.Solar.SunProperties"})(), Group=[])
        sphere = SimpleNamespace(Name="SunLight", TypeId="Part::Sphere", InList=[])
        self.assertFalse(exporter_x3d._is_solar_representation(sphere))
        sphere.InList = [owner]
        owner.Group = [sphere]
        self.assertTrue(exporter_x3d._is_solar_representation(sphere))
        sphere.Name = "UserSphere"
        self.assertFalse(exporter_x3d._is_solar_representation(sphere))

    def test_preserves_unrelated_wire_inside_solar_group(self):
        wire = SimpleNamespace(Name="Line", Proxy=type("Wire", (), {
            "__module__": "draftobjects.wire"})())
        owner = SimpleNamespace(Proxy=type("SunProperties", (), {
            "__module__": "freecad.Solar.SunProperties"})(), Group=[wire])
        wire.InList = [owner]
        self.assertTrue(exporter_x3d._is_solar_representation(wire))
        wire.Name = "UserBoundary"
        self.assertFalse(exporter_x3d._is_solar_representation(wire))


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
    def test_initial_night_hides_sun_and_ray_without_waiting_for_key(self):
        config = _lighting_config()
        config["global"]["interactive_solar"]["initial_hour"] = 0
        scene = ET.Element("Scene")
        scene.append(exporter_x3d._make_directional_light(lambda t:t, config["global"]))
        exporter_x3d._insert_interactive_solar_controller(scene, lambda t:t, config)
        for name in ("GameExport_SolarSunMaterial", "GameExport_SolarRayMaterial"):
            material = next(n for n in scene.iter() if n.attrib.get("DEF") == name)
            self.assertEqual("1", material.attrib["transparency"])

    def test_initial_hud_azimuth_remains_true_when_model_north_is_rotated(self):
        config = _lighting_config()
        config["global"]["interactive_solar"]["north_deg"] = 90.0
        scene = ET.Element("Scene")
        scene.append(
            exporter_x3d._make_directional_light(
                lambda tag: tag,
                config["global"],
            )
        )
        self.assertTrue(
            exporter_x3d._insert_interactive_solar_controller(
                scene, lambda tag: tag, config
            )
        )
        text = next(
            node
            for node in scene.iter()
            if node.attrib.get("DEF") == "GameExport_SolarHUDText"
        ).attrib["string"]
        true_sun = solar.approximate_sun_position(
            80, 12, 9.9281, -84.0907, -6.0, 0.0
        )
        expected_azimuth = round(
            math.degrees(math.atan2(true_sun[0], true_sun[1])) % 360.0
        )
        self.assertIn("AZ {} deg".format(expected_azimuth), text)

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
        sun_node = next(n for n in scene.iter() if n.attrib.get("DEF") == "GameExport_SolarSunTransform")
        radius = exporter_x3d._solar_visualization_config(config)["radius_m"]
        initial_position = tuple(float(v) for v in sun_node.attrib["translation"].split())
        for actual, direction in zip(initial_position, expected_direction):
            self.assertAlmostEqual(actual, -direction * radius, places=5)
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
        self.assertIn("GameExport_SolarHUDHelpSwitch", defs)

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
                "GameExport_SolarCalculator",
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
                "GameExport_SolarController",
                "help_changed",
                "GameExport_SolarHUDHelpSwitch",
                "whichChoice",
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
        self.assertIn("week_step", script)
        self.assertIn("state_changed", script)
        self.assertIn("value = 'H'", script)

        hud_help = next(
            node
            for node in scene.iter()
            if node.attrib.get("DEF") == "GameExport_SolarHUDHelpLanguageSwitch"
        )
        help_texts = [node.attrib["string"] for node in hud_help.iter("Text")]
        self.assertEqual(2, len(help_texts))
        self.assertIn("J/L  15 MIN", help_texts[0])
        self.assertIn("C  DIAGRAM", help_texts[0])
        self.assertIn("I  LANGUAGE", help_texts[0])
        self.assertIn("J/L  15 MIN", help_texts[1])
        self.assertIn("C  DIAGRAMA", help_texts[1])
        self.assertIn("I  IDIOMA", help_texts[1])

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
        self.assertIn("altitude_deg", calculator_script.attrib["url"])
        self.assertIn("azimuth_deg", calculator_script.attrib["url"])
        self.assertIn("label_changed", calculator_script.attrib["url"])

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
        self.assertEqual(-0.5, panel_translation[2])
        self.assertEqual((0.0, 0.0), panel_translation[:2])
        panel_scale = tuple(float(value) for value in hud_panel.attrib["scale"].split())
        self.assertEqual((0.025, 0.025, 0.025), panel_scale)
        effect = hud_panel.find("Effect/EffectPart")
        self.assertIsNotNone(effect)
        self.assertIn("castle_ProjectionMatrix", effect.attrib["url"])
        self.assertIn("max(projection.x, projection.y)", effect.attrib["url"])
        self.assertIn("local * 0.44 * ratio", effect.attrib["url"])
        self.assertIn("near_clip", effect.attrib["url"])

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
        self.assertEqual((0.0, 0.0), compass_translation[:2])
        self.assertEqual((0.006, 0.006, 0.006), compass_scale)
        self.assertIsNotNone(hud_compass.find("Effect/EffectPart"))

        visualization_switch = next(
            node
            for node in scene.iter()
            if node.attrib.get("DEF") == "GameExport_SolarVisualizationSwitch"
        )
        help_switch = next(
            node
            for node in scene.iter()
            if node.attrib.get("DEF") == "GameExport_SolarHUDHelpSwitch"
        )
        self.assertEqual("-1", visualization_switch.attrib["whichChoice"])
        self.assertFalse(any(n.attrib.get("DEF") == "GameExport_SolarSunTransform"
                             for n in visualization_switch.iter()))
        self.assertEqual(1, sum(n.attrib.get("DEF") == "GameExport_SolarSunTransform"
                                for n in scene.iter()))
        self.assertEqual("-1", help_switch.attrib["whichChoice"])

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
