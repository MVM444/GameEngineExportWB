"""Tests for X3D walk-navigation defaults."""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
import math
import sys
import types
from unittest import mock

from GameEngineExportWB.core import exporter_x3d
from GameEngineExportWB.core import gamestart


class _Vector:
    def __init__(self, x, y, z):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)


class _Rotation:
    def __init__(self, axis, angle_deg):
        self.axis = axis
        self.angle_rad = math.radians(float(angle_deg))

    def multVec(self, vector):
        axis_length = math.sqrt(
            (self.axis.x * self.axis.x)
            + (self.axis.y * self.axis.y)
            + (self.axis.z * self.axis.z)
        )
        x = self.axis.x / axis_length
        y = self.axis.y / axis_length
        z = self.axis.z / axis_length
        cosine = math.cos(self.angle_rad)
        sine = math.sin(self.angle_rad)
        dot = (x * vector.x) + (y * vector.y) + (z * vector.z)
        return _Vector(
            (vector.x * cosine) + ((y * vector.z - z * vector.y) * sine) + (x * dot * (1.0 - cosine)),
            (vector.y * cosine) + ((z * vector.x - x * vector.z) * sine) + (y * dot * (1.0 - cosine)),
            (vector.z * cosine) + ((x * vector.y - y * vector.x) * sine) + (z * dot * (1.0 - cosine)),
        )


class _Console:
    def __init__(self):
        self.messages = []

    def PrintMessage(self, message):
        self.messages.append(message)


class NavigationTests(unittest.TestCase):
    def test_walk_navigation_is_locked_and_uses_human_step_height(self):
        cfg = exporter_x3d._normalize_navigation_cfg(
            {"navigation": {"speed": 2.0, "eye_height_mm": 1600.0}}
        )
        scene = ET.Element("Scene")
        exporter_x3d._ensure_navigation(scene, lambda tag: tag, cfg)

        navigation = scene.find("NavigationInfo")
        self.assertIsNotNone(navigation)
        self.assertEqual('"WALK"', navigation.attrib["type"])
        self.assertEqual("0.25 1.600 0.350", navigation.attrib["avatarSize"])

    def test_walk_lock_can_be_disabled_explicitly(self):
        cfg = exporter_x3d._normalize_navigation_cfg(
            {"navigation": {"walk_only": False, "step_height_mm": 200.0}}
        )
        scene = ET.Element("Scene")
        exporter_x3d._ensure_navigation(scene, lambda tag: tag, cfg)

        navigation = scene.find("NavigationInfo")
        self.assertEqual('"WALK" "ANY"', navigation.attrib["type"])
        self.assertEqual("0.25 1.600 0.200", navigation.attrib["avatarSize"])

    def test_gamestart_keeps_freecad_rotation_angle_in_radians(self):
        axis = types.SimpleNamespace(Length=1.0, x=1.0, y=0.0, z=0.0)
        placement = types.SimpleNamespace(
            Rotation=types.SimpleNamespace(Axis=axis, Angle=math.pi / 2.0)
        )

        orientation = gamestart._placement_orientation(placement)

        self.assertAlmostEqual(math.pi / 2.0, orientation[3])

    def test_gamestart_metadata_exposes_yaw_pitch_roll(self):
        axis = types.SimpleNamespace(Length=1.0, x=1.0, y=0.0, z=0.0)
        placement = types.SimpleNamespace(
            Base=types.SimpleNamespace(x=10.0, y=20.0, z=30.0),
            Rotation=types.SimpleNamespace(Axis=axis, Angle=math.pi / 2.0),
        )
        obj = types.SimpleNamespace(
            Placement=placement,
            Yaw=15.0,
            Pitch=-5.0,
            Roll=2.0,
            FOV=60.0,
            HeightOffset=1600.0,
            Label="GameStart",
            Document=types.SimpleNamespace(Name="TestDocument"),
        )
        fake_freecad = types.SimpleNamespace(Version=lambda: [1, 1, 0])

        with mock.patch.dict(sys.modules, {"FreeCAD": fake_freecad}):
            metadata = gamestart.get_metadata(obj)

        self.assertEqual(15.0, metadata["yaw_deg"])
        self.assertEqual(-5.0, metadata["pitch_deg"])
        self.assertEqual(2.0, metadata["roll_deg"])

    def test_zero_yaw_pitch_roll_writes_identity_viewpoint(self):
        console = _Console()
        fake_freecad = types.SimpleNamespace(Vector=_Vector, Rotation=_Rotation, Console=console)
        scene = ET.Element("Scene")
        meta = {
            "position_mm": (1000.0, 2000.0, 3000.0),
            "orientation": (1.0, 0.0, 0.0, math.pi / 2.0),
            "yaw_deg": 0.0,
            "pitch_deg": 0.0,
            "roll_deg": 0.0,
        }

        with mock.patch.dict(sys.modules, {"FreeCAD": fake_freecad}):
            exporter_x3d._insert_viewpoint(
                scene,
                lambda tag: tag,
                meta,
                {"eye_height_mm": 1600.0},
            )

        viewpoint = scene.find("Viewpoint")
        self.assertEqual("0.000000 0.000000 1.000000 0.000000", viewpoint.attrib["orientation"])
        log_text = "".join(console.messages)
        self.assertIn("Yaw=0.000000 deg, Pitch=0.000000 deg, Roll=0.000000 deg", log_text)
        self.assertIn("0.000000 0.000000 1.000000 0.000000", log_text)

    def test_freecad_yaw_converts_to_x3d_y_axis(self):
        axis_x, axis_y, axis_z, angle_rad = exporter_x3d._convert_gamestart_orientation_to_x3d(
            (0.0, 1.0, 0.0, 0.0),
            (90.0, 0.0, 0.0),
        )

        self.assertAlmostEqual(0.0, axis_x, places=7)
        self.assertAlmostEqual(1.0, axis_y, places=7)
        self.assertAlmostEqual(0.0, axis_z, places=7)
        self.assertAlmostEqual(math.pi / 2.0, angle_rad, places=7)

    def test_walk_ground_proxy_is_invisible_and_matches_model_bounds(self):
        scene = ET.Element("Scene")
        transform = ET.SubElement(
            scene,
            "Transform",
            {"DEF": exporter_x3d.TRANSFORM_DEF},
        )
        ET.SubElement(
            transform,
            "Coordinate",
            {"point": "1000 2000 -150, 5000 8000 3000"},
        )
        cfg = exporter_x3d._normalize_navigation_cfg(
            {"navigation": {"ground_margin_mm": 0.0}}
        )

        exporter_x3d._ensure_walk_ground_collision(scene, lambda tag: tag, cfg)

        collision = scene.find("Collision")
        self.assertIsNotNone(collision)
        self.assertEqual(exporter_x3d.GROUND_COLLISION_DEF, collision.attrib["DEF"])
        proxy = collision.find("Transform")
        self.assertEqual("proxy", proxy.attrib["containerField"])
        self.assertEqual("3.000000 -0.100000 -5.000000", proxy.attrib["translation"])
        self.assertEqual("4.000000 0.200000 6.000000", proxy.find("Shape/Box").attrib["size"])

    def test_walk_ground_proxy_is_idempotent(self):
        scene = ET.Element("Scene")
        transform = ET.SubElement(
            scene,
            "Transform",
            {"DEF": exporter_x3d.TRANSFORM_DEF},
        )
        ET.SubElement(transform, "Coordinate", {"point": "0 0 0, 1000 1000 0"})
        cfg = exporter_x3d._normalize_navigation_cfg(None)

        exporter_x3d._ensure_walk_ground_collision(scene, lambda tag: tag, cfg)
        exporter_x3d._ensure_walk_ground_collision(scene, lambda tag: tag, cfg)

        proxies = [
            node
            for node in scene.findall("Collision")
            if node.attrib.get("DEF") == exporter_x3d.GROUND_COLLISION_DEF
        ]
        self.assertEqual(1, len(proxies))


if __name__ == "__main__":
    unittest.main()
