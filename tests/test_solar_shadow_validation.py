"""Tests for the independent Solar shadow reference calculation."""

from __future__ import annotations

import math
import unittest

from freecad.GameEngineExportWB.core import solar
from freecad.GameEngineExportWB.core import solar_shadow_validation as reference
from freecad.GameEngineExportWB.core import exporter_x3d


class SolarShadowValidationTest(unittest.TestCase):
    def test_four_presets_check_axes_north_and_lengths(self):
        pole_height = 3000.0
        expected = {
            "01_east_alt45": ((-3000.0, 0.0), 3000.0),
            "02_south_alt30": ((0.0, 3000.0 * math.sqrt(3.0)), 3000.0 * math.sqrt(3.0)),
            "03_west_alt60": ((3000.0 / math.sqrt(3.0), 0.0), 3000.0 / math.sqrt(3.0)),
            "04_rotated_north_alt30": ((0.0, -3000.0 * math.sqrt(3.0)), 3000.0 * math.sqrt(3.0)),
        }
        for preset in reference.PRESETS:
            with self.subTest(preset=preset.key):
                endpoint = reference.theoretical_shadow_endpoint(
                    pole_height,
                    preset.altitude_deg,
                    preset.azimuth_deg,
                    preset.north_deg,
                )
                expected_xy, expected_length = expected[preset.key]
                self.assertAlmostEqual(expected_xy[0], endpoint[0], places=8)
                self.assertAlmostEqual(expected_xy[1], endpoint[1], places=8)
                self.assertAlmostEqual(
                    expected_length,
                    reference.horizontal_length(endpoint),
                    places=8,
                )

    def test_independent_formula_matches_production_ray_intersection(self):
        pole_height = 3000.0
        for preset in reference.PRESETS:
            with self.subTest(preset=preset.key):
                production_ray = solar.direction_from_altitude_azimuth(
                    preset.altitude_deg,
                    preset.azimuth_deg,
                    preset.north_deg,
                )
                from_ray = reference.ray_shadow_endpoint(pole_height, production_ray)
                theoretical = reference.theoretical_shadow_endpoint(
                    pole_height,
                    preset.altitude_deg,
                    preset.azimuth_deg,
                    preset.north_deg,
                )
                for actual, expected in zip(from_ray, theoretical):
                    self.assertAlmostEqual(expected, actual, places=8)

    def test_reference_sun_vector_is_opposite_production_ray(self):
        for preset in reference.PRESETS:
            with self.subTest(preset=preset.key):
                toward_sun = reference.observer_to_sun_vector(
                    preset.altitude_deg,
                    preset.azimuth_deg,
                    preset.north_deg,
                )
                production_ray = solar.direction_from_altitude_azimuth(
                    preset.altitude_deg,
                    preset.azimuth_deg,
                    preset.north_deg,
                )
                for sun_component, ray_component in zip(toward_sun, production_ray):
                    self.assertAlmostEqual(sun_component, -ray_component, places=8)

    def test_invalid_geometry_is_rejected(self):
        with self.assertRaises(ValueError):
            reference.theoretical_shadow_endpoint(3000.0, 0.0, 90.0, 0.0)
        with self.assertRaises(ValueError):
            reference.ray_shadow_endpoint(3000.0, (0.0, 0.0, 1.0))

    def test_directional_shadow_uses_baseline_shadow_map_flag_only(self):
        node = exporter_x3d._make_directional_light(
            lambda tag: tag,
            {"direction_freecad": (0.0, 0.0, -1.0), "shadows": True},
        )
        self.assertEqual("true", node.attrib["shadows"])
        self.assertNotIn("shadowVolumes", node.attrib)
        self.assertNotIn("shadowVolumesMain", node.attrib)
        self.assertNotIn("shadowMapSize", node.attrib)
        self.assertNotIn("defaultShadowMap", node.attrib)


if __name__ == "__main__":
    unittest.main()
