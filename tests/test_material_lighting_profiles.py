"""Regression tests for color-aware X3D material lighting profiles."""

import unittest

from GameEngineExportWB.core import exporter_x3d


class MaterialLightingProfileTests(unittest.TestCase):
    def test_emissive_color_preserves_diffuse_hue(self):
        source = '<Material DEF="Wall" diffuseColor="0.8 0.4 0.2" />'
        result, count = exporter_x3d.apply_x3d_material_lighting_profile(
            source, "Architectural"
        )
        self.assertEqual(count, 1)
        self.assertIn('diffuseColor="0.8 0.4 0.2"', result)
        self.assertIn('emissiveColor="0.120000 0.060000 0.030000"', result)

    def test_default_diffuse_color_retains_previous_neutral_lift(self):
        source = '<Material DEF="DefaultWall" />'
        result, count = exporter_x3d.apply_x3d_material_lighting_profile(
            source, "Soft"
        )
        self.assertEqual(count, 1)
        self.assertIn('emissiveColor="0.060000 0.060000 0.060000"', result)

    def test_use_emitter_and_ground_materials_are_not_rewritten(self):
        source = """<Material USE="Wall" />
<Material DEF="GameExport_Emitter_0_0_Light" diffuseColor="1 1 1" />
<Material DEF="GameExport_GroundTexture_Site" diffuseColor="0.5 0.5 0.5" />"""
        result, count = exporter_x3d.apply_x3d_material_lighting_profile(
            source, "Bright"
        )
        self.assertEqual(count, 0)
        self.assertEqual(result, source)


if __name__ == "__main__":
    unittest.main()
