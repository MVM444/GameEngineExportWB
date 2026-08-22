"""Pure XML tests for GameEngineExport texture/mirror decoration helpers.

Name: test_exporter_material_effects.py
Purpose: verify physical UV generation, polished material and Castle mirror nodes without FreeCAD GUI.
Version: 2026-08-19-v1
Date and time: 2026-08-19 17:35 -06:00
"""

import xml.etree.ElementTree as ET
import unittest

from GameEngineExportWB.core import exporter_x3d as ex


class ExporterMaterialEffectsTests(unittest.TestCase):
    @staticmethod
    def make_group():
        group = ET.Element("Group")
        shape = ET.SubElement(group, "Shape")
        app = ET.SubElement(shape, "Appearance")
        ET.SubElement(app, "Material", {"diffuseColor": "0.7 0.7 0.7"})
        ifs = ET.SubElement(shape, "IndexedFaceSet", {"coordIndex": "0 1 2 3 -1"})
        ET.SubElement(ifs, "Coordinate", {"point": "0 0 0 1000 0 0 1000 2000 0 0 2000 0"})
        return group, shape, app, ifs

    def test_physical_uv_xy(self):
        group, shape, app, ifs = self.make_group()
        changed = ex._generate_physical_planar_uv_for_shape(shape, lambda x: x, "XY", 500.0, 1000.0)
        self.assertTrue(changed)
        tex = next(child for child in ifs if ex._local_name(child.tag) == "TextureCoordinate")
        values = [float(v) for v in tex.attrib["point"].split()]
        self.assertEqual(max(values[0::2]), 2.0)
        self.assertEqual(max(values[1::2]), 2.0)

    def test_true_mirror_nodes(self):
        group, shape, app, ifs = self.make_group()
        count = ex._apply_mirror_to_shapes(group, lambda x: x, 512)
        self.assertEqual(count, 1)
        tags = [ex._local_name(child.tag) for child in app]
        self.assertIn("RenderedTexture", tags)
        rendered = next(child for child in app if ex._local_name(child.tag) == "RenderedTexture")
        self.assertEqual(rendered.attrib["dimensions"], "512 512 3")
        self.assertTrue(any(ex._local_name(child.tag) == "ViewpointMirror" for child in rendered))
        self.assertTrue(any(
            ex._local_name(child.tag) == "TextureCoordinateGenerator" and child.attrib.get("mode") == "MIRROR-PLANE"
            for child in ifs
        ))

    def test_polished_material(self):
        group, shape, app, ifs = self.make_group()
        count = ex._apply_polished_material_to_shapes(group, lambda x: x, 0.6)
        self.assertEqual(count, 1)
        material = next(child for child in app if ex._local_name(child.tag) == "Material")
        self.assertGreater(float(material.attrib["shininess"]), 0.5)
        self.assertIn("specularColor", material.attrib)


if __name__ == "__main__":
    unittest.main()
