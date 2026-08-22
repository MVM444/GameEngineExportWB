"""Tests for automatic 3D scene selection."""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from GameEngineExportWB.core import exporter_x3d


class _Console:
    @staticmethod
    def PrintMessage(_message):
        return None


class _Shape:
    def __init__(self, solid=False, faces=0, edges=0):
        self.Solids = [types.SimpleNamespace(Volume=100.0)] if solid else []
        self.Faces = [object() for _index in range(faces)]
        self.Edges = [object() for _index in range(edges)]

    @staticmethod
    def isNull():
        return False


class _ParentVisibility:
    def __init__(self, visible, child_view):
        self._visible = bool(visible)
        self._child_view = child_view

    @property
    def Visibility(self):
        return self._visible

    @Visibility.setter
    def Visibility(self, value):
        self._visible = bool(value)
        self._child_view.Visibility = bool(value)


def _object(name, type_id, shape=None, visible=True, label=None, linked=None):
    values = {
        "Name": name,
        "Label": label or name,
        "TypeId": type_id,
        "ViewObject": types.SimpleNamespace(Visibility=visible),
    }
    if shape is not None:
        values["Shape"] = shape
    if linked is not None:
        values["LinkedObject"] = linked
    return types.SimpleNamespace(**values)


class SceneSelectionTests(unittest.TestCase):
    def test_temporary_export_visibility_restores_objects_and_parents(self):
        sibling = _object("VisibleSibling", "Part::Feature", _Shape(solid=True), visible=True)
        parent = _object("HiddenGroup", "App::DocumentObjectGroup", visible=False)
        parent.ViewObject = _ParentVisibility(False, sibling.ViewObject)
        device = _object("HiddenDevice", "Part::Feature", _Shape(solid=True), visible=False)
        device.InList = [parent]
        doc = types.SimpleNamespace(Objects=[device, sibling, parent])
        device.Document = doc
        sibling.Document = doc
        parent.Document = doc
        fake_freecad = types.SimpleNamespace(Console=_Console())

        with mock.patch.dict(sys.modules, {"FreeCAD": fake_freecad}):
            with self.assertRaises(RuntimeError):
                with exporter_x3d._temporary_export_visibility([device]):
                    self.assertTrue(device.ViewObject.Visibility)
                    self.assertTrue(parent.ViewObject.Visibility)
                    raise RuntimeError("export failed")

        self.assertFalse(device.ViewObject.Visibility)
        self.assertFalse(parent.ViewObject.Visibility)
        self.assertTrue(sibling.ViewObject.Visibility)

    def test_complete_scene_keeps_devices_and_rejects_2d_helpers(self):
        wall = _object("Wall", "Part::Feature", _Shape(solid=True), visible=True)
        hidden_wall = _object("HiddenWall", "Part::Feature", _Shape(solid=True), visible=False)
        hidden_ceiling = _object(
            "Ceiling001",
            "Part::Feature",
            _Shape(solid=True),
            visible=False,
            label="Ceiling",
        )
        master = _object(
            "LuminaireMaster",
            "Part::FeaturePython",
            _Shape(solid=True),
            visible=False,
        )
        luminaire = _object(
            "LuminaireLink001",
            "App::Link",
            _Shape(solid=True),
            visible=False,
            label="Luminaria pasillo",
            linked=master,
        )
        symbol = _object(
            "LuminaireSymbol",
            "Part::Part2DObjectPython",
            _Shape(faces=1, edges=4),
            visible=True,
        )
        wire = _object("CircuitLines", "Part::Feature", _Shape(edges=8), visible=True)
        hvac_master = _object(
            "HVAC_EvapMaster_Pared_18000",
            "Part::Feature",
            _Shape(solid=True),
            visible=False,
        )
        hvac = _object(
            "DeviceInstance42",
            "App::Link",
            _Shape(solid=True),
            visible=False,
            label="Mechanical instance 42",
            linked=hvac_master,
        )
        hvac_2d = _object(
            "HVAC_Evap2D",
            "Part::Feature",
            _Shape(faces=2),
            visible=True,
            label="HVAC_2D_EVAP_AC-SRV-01",
        )
        generic_symbol_master = _object(
            "LibraryObject2",
            "Part::Feature",
            _Shape(faces=1),
            visible=False,
        )
        generic_symbol = _object(
            "Instance43",
            "App::Link",
            _Shape(faces=1),
            visible=False,
            label="Generic linked instance",
            linked=generic_symbol_master,
        )
        doc = types.SimpleNamespace(
            Objects=[
                wall,
                hidden_wall,
                hidden_ceiling,
                master,
                luminaire,
                symbol,
                wire,
                hvac_master,
                hvac,
                hvac_2d,
                generic_symbol_master,
                generic_symbol,
            ]
        )
        fake_freecad = types.SimpleNamespace(Console=_Console())

        with mock.patch.dict(sys.modules, {"FreeCAD": fake_freecad}):
            selected = exporter_x3d.collect_default_scene_objects(doc)

        self.assertEqual([wall, hidden_wall, hidden_ceiling, luminaire, hvac], selected)

    def test_hidden_3d_object_policy_can_be_disabled(self):
        master = _object("LibraryObject", "Part::Feature", _Shape(solid=True), visible=False)
        instance = _object(
            "Instance001",
            "App::Link",
            _Shape(solid=True),
            visible=False,
            linked=master,
        )
        doc = types.SimpleNamespace(Objects=[master, instance])
        fake_freecad = types.SimpleNamespace(Console=_Console())

        with mock.patch.dict(sys.modules, {"FreeCAD": fake_freecad}):
            selected = exporter_x3d.collect_default_scene_objects(
                doc, include_hidden_objects=False
            )

        self.assertEqual([], selected)

    def test_automatic_scene_ignores_stale_explicit_master_and_2d_entries(self):
        wall = _object("Wall", "Part::Feature", _Shape(solid=True), visible=True)
        master = _object(
            "LuminaireMaster",
            "Part::Feature",
            _Shape(solid=True),
            visible=False,
        )
        instance = _object(
            "Luminaire001",
            "App::Link",
            _Shape(solid=True),
            visible=False,
            linked=master,
        )
        symbol = _object(
            "Luminaire_2D",
            "Part::Feature",
            _Shape(solid=True),
            visible=False,
        )
        doc = types.SimpleNamespace(Objects=[wall, master, instance, symbol])
        fake_freecad = types.SimpleNamespace(Console=_Console())

        with mock.patch.dict(sys.modules, {"FreeCAD": fake_freecad}):
            selected = exporter_x3d.resolve_scene_objects(
                doc,
                [master, symbol],
                automatic_3d_scene=True,
                include_hidden_objects=True,
            )

        self.assertEqual([wall, instance], selected)

    def test_explicit_scene_is_completed_with_hidden_3d_geometry(self):
        explicit_wall = _object(
            "Wall",
            "Part::Feature",
            _Shape(solid=True),
            visible=True,
        )
        visible_column = _object(
            "Column",
            "Part::Feature",
            _Shape(solid=True),
            visible=True,
        )
        hidden_ceiling = _object(
            "Ceiling",
            "Part::Feature",
            _Shape(solid=True),
            visible=False,
        )
        hidden_symbol = _object(
            "CeilingSymbol_2D",
            "Part::Feature",
            _Shape(solid=True),
            visible=False,
        )
        doc = types.SimpleNamespace(
            Objects=[explicit_wall, visible_column, hidden_ceiling, hidden_symbol]
        )
        fake_freecad = types.SimpleNamespace(Console=_Console())

        with mock.patch.dict(sys.modules, {"FreeCAD": fake_freecad}):
            selected = exporter_x3d.complete_scene_objects_with_hidden_3d(
                doc,
                [explicit_wall],
            )

        self.assertEqual([explicit_wall, hidden_ceiling], selected)

    def test_hidden_parent_group_makes_child_effectively_hidden(self):
        ceiling = _object(
            "Ceiling",
            "Part::Feature",
            _Shape(solid=True),
            visible=True,
        )
        group = _object(
            "Ceilings",
            "App::DocumentObjectGroup",
            visible=False,
        )
        group.Group = [ceiling]
        ceiling.InList = [group]
        doc = types.SimpleNamespace(Objects=[group, ceiling])
        fake_freecad = types.SimpleNamespace(Console=_Console())

        with mock.patch.dict(sys.modules, {"FreeCAD": fake_freecad}):
            selected = exporter_x3d.complete_scene_objects_with_hidden_3d(doc, [])

        self.assertEqual([ceiling], selected)

    def test_explicit_include_and_exclude_override_default_visibility(self):
        forced = _object("ForcedObject", "Part::Feature", _Shape(solid=True), visible=False)
        forced.GameExportInclude = True
        rejected = _object("RejectedObject", "Part::Feature", _Shape(solid=True), visible=True)
        rejected.GameExportExclude = True
        doc = types.SimpleNamespace(Objects=[forced, rejected])
        fake_freecad = types.SimpleNamespace(Console=_Console())

        with mock.patch.dict(sys.modules, {"FreeCAD": fake_freecad}):
            selected = exporter_x3d.collect_default_scene_objects(doc)

        self.assertEqual([forced], selected)

    def test_face_only_model_surface_remains_exportable(self):
        surface = _object("TerrainSurface", "Part::Feature", _Shape(faces=1), visible=True)

        self.assertEqual((True, ""), exporter_x3d._is_exportable_object(surface))

    def test_planar_named_surface_is_not_exportable(self):
        symbol = _object(
            "AirConditioner_2D",
            "Part::Feature",
            _Shape(faces=1),
            visible=True,
            label="Aire acondicionado (Plano)",
        )

        ok, reason = exporter_x3d._is_exportable_object(symbol)

        self.assertFalse(ok)
        self.assertIn("2D", reason)

    def test_named_2d_helper_with_artificial_solid_is_not_exportable(self):
        symbol = _object(
            "HVAC_2D_Instance",
            "Part::Feature",
            _Shape(solid=True),
            visible=False,
            label="Plan symbol with artificial thickness",
        )

        ok, reason = exporter_x3d._is_exportable_object(symbol)

        self.assertFalse(ok)
        self.assertIn("2D", reason)

    def test_hidden_library_master_is_excluded_but_hidden_ceiling_is_kept(self):
        library_master = _object(
            "GenericMaster",
            "Part::Feature",
            _Shape(solid=True),
            visible=False,
        )
        library_group = _object(
            "AssetLibrary",
            "App::DocumentObjectGroup",
            visible=False,
            label="Asset Library",
        )
        library_group.Group = [library_master]
        library_master.InList = [library_group]

        ceiling = _object(
            "Ceiling",
            "Part::Feature",
            _Shape(solid=True),
            visible=False,
        )
        ceiling_group = _object(
            "Ceilings",
            "App::DocumentObjectGroup",
            visible=False,
            label="Suspended ceilings",
        )
        ceiling_group.Group = [ceiling]
        ceiling.InList = [ceiling_group]
        doc = types.SimpleNamespace(
            Objects=[library_group, library_master, ceiling_group, ceiling]
        )
        fake_freecad = types.SimpleNamespace(Console=_Console())

        with mock.patch.dict(sys.modules, {"FreeCAD": fake_freecad}):
            selected = exporter_x3d.collect_default_scene_objects(doc)

        self.assertEqual([ceiling], selected)


if __name__ == "__main__":
    unittest.main()
