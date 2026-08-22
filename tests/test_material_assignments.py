"""Pure tests for GameEngineExport material assignments.

Name: test_material_assignments.py
Purpose: verify normalization, persistence reading and built-in texture resolution.
Version: 2026-08-19-v1
Date and time: 2026-08-19 17:35 -06:00
"""

from pathlib import Path
import unittest

from GameEngineExportWB.core import material_assignments as ma


class FakeObject:
    def __init__(self):
        self.Name = "Wall001"
        self.Label = "Wall 001"
        self.PropertiesList = [
            ma.PROP_ENABLED,
            ma.PROP_MODE,
            ma.PROP_TEXTURE_ID,
            ma.PROP_TEXTURE_PATH,
            ma.PROP_PROJECTION,
            ma.PROP_TILE_U_MM,
            ma.PROP_TILE_V_MM,
            ma.PROP_REFLECTIVITY,
            ma.PROP_MIRROR_SIZE,
        ]
        setattr(self, ma.PROP_ENABLED, True)
        setattr(self, ma.PROP_MODE, "Polished")
        setattr(self, ma.PROP_TEXTURE_ID, ma.TEXTURE_WOOD)
        setattr(self, ma.PROP_TEXTURE_PATH, "")
        setattr(self, ma.PROP_PROJECTION, "XZ")
        setattr(self, ma.PROP_TILE_U_MM, 1200.0)
        setattr(self, ma.PROP_TILE_V_MM, 180.0)
        setattr(self, ma.PROP_REFLECTIVITY, 0.55)
        setattr(self, ma.PROP_MIRROR_SIZE, 1024)


class MaterialAssignmentTests(unittest.TestCase):
    def test_normalize_assignment_bounds(self):
        cfg = ma.normalize_assignment(
            {"reflectivity": 4, "mirror_size": 99999, "projection": "bad"}
        )
        self.assertEqual(cfg["reflectivity"], 1.0)
        self.assertEqual(cfg["mirror_size"], 4096)
        self.assertEqual(cfg["projection"], ma.PROJECTION_AUTO)

    def test_read_object_assignment(self):
        cfg = ma.read_object_assignment(FakeObject())
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["mode"], ma.MODE_POLISHED)
        self.assertEqual(cfg["texture_id"], ma.TEXTURE_WOOD)
        self.assertEqual(cfg["projection"], ma.PROJECTION_XZ)
        self.assertEqual(cfg["object_name"], "Wall001")

    def test_collect_assignments_adds_index(self):
        cfgs = ma.collect_assignments([FakeObject()])
        self.assertEqual(len(cfgs), 1)
        self.assertEqual(cfgs[0]["object_index"], 0)

    def test_builtin_texture_resolution(self):
        path = ma.builtin_texture_path(ma.TEXTURE_CERAMIC)
        self.assertIsInstance(path, str)
        self.assertTrue(Path(path).is_file())


if __name__ == "__main__":
    unittest.main()
