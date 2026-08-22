"""Tests for solid-only luminaire light origins."""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from GameEngineExportWB.core import lights


class _Vector:
    def __init__(self, x, y, z):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)


class _Placement:
    @staticmethod
    def multVec(vector):
        return vector


class _Console:
    @staticmethod
    def PrintMessage(_message):
        return None

    @staticmethod
    def PrintWarning(_message):
        return None


class _Box:
    def __init__(self, x_min, y_min, z_min, x_max, y_max, z_max):
        self.XMin = x_min
        self.YMin = y_min
        self.ZMin = z_min
        self.XMax = x_max
        self.YMax = y_max
        self.ZMax = z_max


class _Solid:
    def __init__(self, bbox, volume=1.0):
        self.BoundBox = bbox
        self.Volume = volume


class _Shape:
    def __init__(self, whole_bbox, solids):
        self.BoundBox = whole_bbox
        self.Solids = solids

    @staticmethod
    def isNull():
        return False


class LightGeometryTests(unittest.TestCase):
    def test_downward_origin_uses_3d_solid_not_embedded_2d_symbol(self):
        whole_bbox = _Box(-300, -300, 0, 300, 300, 2740)
        solid_bbox = _Box(-300, -300, 2640, 300, 300, 2740)
        master = types.SimpleNamespace(
            Name="LuminaireMaster",
            Label="Luminaire master with 2D symbol",
            TypeId="Part::FeaturePython",
            Shape=_Shape(whole_bbox, [_Solid(solid_bbox, 34954488.0)]),
        )
        fake_freecad = types.SimpleNamespace(Vector=_Vector, Console=_Console())

        with mock.patch.dict(sys.modules, {"FreeCAD": fake_freecad}):
            bbox = lights._get_local_bbox(master)
            point = lights._face_center(bbox, lights._local_direction_vector("Down"))

        self.assertEqual(2640.0, bbox.ZMin)
        self.assertEqual(2740.0, bbox.ZMax)
        self.assertEqual(2640.0, point.z)

    def test_object_without_positive_volume_solid_has_no_solid_bbox(self):
        bbox = _Box(-10, -10, 0, 10, 10, 0)
        obj = types.SimpleNamespace(Shape=_Shape(bbox, [_Solid(bbox, 0.0)]))

        self.assertIsNone(lights._get_solid_bbox(obj))

    def test_panel_total_intensity_is_shared_between_generated_points(self):
        bbox = _Box(-300, -300, 2640, 300, 300, 2740)
        master = types.SimpleNamespace(
            Name="PanelMaster",
            Label="Luminaire panel",
            TypeId="Part::Feature",
            Shape=_Shape(bbox, [_Solid(bbox, 100.0)]),
        )
        source = types.SimpleNamespace(
            Name="PanelLink",
            Label="Luminaire panel instance",
            TypeId="App::Link",
        )
        definition = lights.LightDefinition(
            master_obj=master,
            source_obj=source,
            effective_placement=_Placement(),
            light_properties={
                "type": "RectPanel",
                "pattern": "Grid",
                "direction": "Down",
                "origin_mode": "AutoFaceCenter",
                "offset_mm": 0.0,
                "intensity": 1.0,
                "range_m": 6.0,
                "color": (1.0, 1.0, 1.0),
                "rows": 2,
                "cols": 2,
            },
        )
        fake_freecad = types.SimpleNamespace(Vector=_Vector, Console=_Console())

        with mock.patch.dict(sys.modules, {"FreeCAD": fake_freecad}):
            entries = lights.generate_light_points_for_definition(definition)

        self.assertEqual(4, len(entries))
        self.assertTrue(all(entry.intensity == 0.25 for entry in entries))
        self.assertAlmostEqual(1.0, sum(entry.intensity for entry in entries))

    def test_luminaire_detection_uses_standard_semantic_metadata(self):
        source = types.SimpleNamespace(
            Name="Instance42",
            Label="Instance 42",
            TypeId="App::Link",
            IfcType="IfcLightFixture",
        )
        master = types.SimpleNamespace(
            Name="LibraryObject7",
            Label="Library object 7",
            TypeId="Part::Feature",
        )

        self.assertTrue(lights._looks_like_luminaire(source, master))

    def test_luminaire_detection_accepts_explicit_boolean_role(self):
        source = types.SimpleNamespace(
            Name="Instance99",
            Label="Instance 99",
            TypeId="App::Link",
            IsGameExportLuminaire=True,
        )
        master = types.SimpleNamespace(
            Name="GenericMaster",
            Label="Generic master",
            TypeId="Part::Feature",
        )

        self.assertTrue(lights._looks_like_luminaire(source, master))


if __name__ == "__main__":
    unittest.main()
