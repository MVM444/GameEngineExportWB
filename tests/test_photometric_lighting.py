"""Regression tests for the optional photometric light algorithm."""

import math
import unittest

from GameEngineExportWB.core import exporter_x3d


class PhotometricLightingTests(unittest.TestCase):
    def test_lumens_to_candela_uses_uniform_cone_solid_angle(self):
        expected = 3600.0 / math.pi  # 120-degree full cone => pi steradians
        self.assertAlmostEqual(
            exporter_x3d.photometric_candela(3600.0, 120.0), expected, places=6
        )

    def test_photometric_spot_uses_candela_and_inverse_square_falloff(self):
        light = exporter_x3d._make_spot_light(
            lambda name: name,
            {
                "name": "Calibration_3600lm",
                "position_mm": (1000.0, 2000.0, 2800.0),
                "radius": 6.0,
                "light_mode": exporter_x3d.LIGHT_MODE_PHOTOMETRIC,
                "lumens": 3600.0,
                "beam_angle_deg": 120.0,
                "cct_kelvin": 4000.0,
                "shadows": False,
            },
            0,
        )
        self.assertEqual(light.tag, "SpotLight")
        self.assertEqual(light.attrib["attenuation"], "0.000000 0.000000 1.000000")
        self.assertEqual(light.attrib["ambientIntensity"], "0.000000")
        self.assertAlmostEqual(float(light.attrib["intensity"]), 3600.0 / math.pi, places=5)
        self.assertAlmostEqual(float(light.attrib["cutOffAngle"]), math.pi / 3.0, places=5)
        self.assertNotIn("shadows", light.attrib)

    def test_legacy_modes_remain_accepted(self):
        for mode in (
            exporter_x3d.LIGHT_MODE_SPOT_NO_SHADOWS,
            exporter_x3d.LIGHT_MODE_SPOT_SHADOW_MAP,
            exporter_x3d.LIGHT_MODE_POINT_CLASSIC,
        ):
            self.assertEqual(exporter_x3d._light_export_mode({"light_mode": mode}), mode)


if __name__ == "__main__":
    unittest.main()
