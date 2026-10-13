"""Tests that GameExportExclude is a hard exclusion in every scene-selection path."""

import sys
from types import SimpleNamespace
from unittest import mock

from freecad.GameEngineExportWB.core import exporter_x3d


class Solid:
    Volume = 10.0


class Shape:
    Solids = [Solid()]
    Faces = []
    Edges = []

    def isNull(self):
        return False


class View:
    Visibility = True


class Obj:
    TypeId = "Part::Feature"

    def __init__(self, name, excluded=False):
        self.Name = name
        self.Label = name
        self.Shape = Shape()
        self.ViewObject = View()
        if excluded:
            self.GameExportExclude = True


class Doc:
    def __init__(self, objects):
        self.Objects = objects


def _freecad_stub():
    console = SimpleNamespace(PrintMessage=lambda *a, **k: None, PrintWarning=lambda *a, **k: None)
    return SimpleNamespace(Console=console)


def test_excluded_object_is_removed_from_automatic_and_explicit_paths():
    keep_a = Obj("KeepA")
    space = Obj("Space", excluded=True)
    keep_b = Obj("KeepB")
    doc = Doc([keep_a, space, keep_b])

    with mock.patch.dict(sys.modules, {"FreeCAD": _freecad_stub()}):
        assert exporter_x3d.collect_default_scene_objects(doc) == [keep_a, keep_b]
        assert exporter_x3d.resolve_scene_objects(
            doc,
            [keep_a, space, keep_b],
            automatic_3d_scene=False,
            include_hidden_objects=False,
        ) == [keep_a, keep_b]
        assert exporter_x3d.resolve_scene_objects(
            doc,
            [keep_a, space, keep_b],
            automatic_3d_scene=False,
            include_hidden_objects=True,
        ) == [keep_a, keep_b]


def test_final_exportability_gate_rejects_excluded_object():
    keep = Obj("Keep")
    space = Obj("Space", excluded=True)
    result = exporter_x3d.diagnose_export_candidates([keep, space])
    assert result["exportable"] == [keep]
    assert ("Space", "Part::Feature", "GameExportExclude=True") in result["skipped"]
