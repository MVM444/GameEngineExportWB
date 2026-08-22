"""Tests for safe X3D DEF/USE geometry instancing.

Fecha y hora: 2026-08-13 18:20 America/Costa_Rica.
"""

import unittest
import xml.etree.ElementTree as ET

try:
    from GameEngineExportWB.core import exporter_x3d
except ImportError:
    import exporter_x3d


def _linked_object(translation, suffix, color="0.8 0.8 0.8"):
    transform = ET.Element("Transform", {"translation": translation})
    group = ET.SubElement(transform, "Group", {"DEF": "Object_" + suffix})
    switch = ET.SubElement(group, "Switch", {"whichChoice": "0"})

    points_shape = ET.SubElement(switch, "Shape")
    point_set = ET.SubElement(points_shape, "PointSet")
    ET.SubElement(
        point_set,
        "Coordinate",
        {
            "DEF": "Coordinates_" + suffix,
            "point": "0 0 0 1 0 0 1 1 0 0 1 0 " * 300,
        },
    )

    face_shape = ET.SubElement(switch, "Shape")
    appearance = ET.SubElement(face_shape, "Appearance")
    ET.SubElement(appearance, "Material", {"diffuseColor": color})
    indexed_faces = ET.SubElement(
        face_shape,
        "IndexedFaceSet",
        {"coordIndex": "0 1 2 -1 0 2 3 -1"},
    )
    ET.SubElement(indexed_faces, "Coordinate", {"USE": "Coordinates_" + suffix})
    return transform


class X3DInstancingTests(unittest.TestCase):
    def test_repeated_link_geometry_uses_first_definition(self):
        root = ET.Element("Transform", {"DEF": "FreeCAD_mm_to_m"})
        root.append(_linked_object("0 0 0", "A"))
        root.append(_linked_object("10 0 0", "B"))

        replacements = exporter_x3d._instance_repeated_x3d_subtrees(
            root,
            minimum_payload_chars=0,
        )

        self.assertGreaterEqual(replacements, 1)
        first_group = root[0][0]
        second_group = root[1][0]
        self.assertEqual(second_group.tag, "Group")
        self.assertEqual(second_group.attrib, {"USE": first_group.attrib["DEF"]})
        self.assertEqual(root[0].attrib["translation"], "0 0 0")
        self.assertEqual(root[1].attrib["translation"], "10 0 0")

    def test_visually_different_material_is_not_reused(self):
        root = ET.Element("Transform", {"DEF": "FreeCAD_mm_to_m"})
        root.append(_linked_object("0 0 0", "A", "0.8 0.8 0.8"))
        root.append(_linked_object("10 0 0", "B", "1 0 0"))

        exporter_x3d._instance_repeated_x3d_subtrees(
            root,
            minimum_payload_chars=0,
        )

        self.assertNotIn("USE", root[1][0].attrib)

    def test_use_nodes_have_no_children_or_extra_fields(self):
        root = ET.Element("Transform", {"DEF": "FreeCAD_mm_to_m"})
        root.append(_linked_object("0 0 0", "A"))
        root.append(_linked_object("10 0 0", "B"))
        exporter_x3d._instance_repeated_x3d_subtrees(root, 0)

        for node in root.iter():
            if "USE" not in node.attrib:
                continue
            self.assertEqual(len(list(node)), 0)
            self.assertTrue(set(node.attrib).issubset({"USE", "containerField"}))

    def test_classic_mode_is_preserved(self):
        self.assertEqual(
            exporter_x3d._geometry_export_mode({"mode": "Classic"}),
            "Classic",
        )
        self.assertEqual(
            exporter_x3d._geometry_export_mode({"mode": "Optimized"}),
            "Optimized",
        )


if __name__ == "__main__":
    unittest.main()
