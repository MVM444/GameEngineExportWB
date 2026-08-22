"""Regression tests for reusable and user-saved lighting profiles."""

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "core" / "lighting_profiles.py"
SPEC = importlib.util.spec_from_file_location("gee_lighting_profiles_test", MODULE_PATH)
lighting_profiles = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lighting_profiles)


class LightingProfileTests(unittest.TestCase):
    def test_builtin_profiles_cover_photometry_and_presentation(self):
        names = lighting_profiles.builtin_profile_names()
        self.assertIn("Arquitectonico equilibrado", names)
        self.assertIn("Fotometrico realista", names)
        self.assertIn("Fotometrico visible", names)
        self.assertIn("Presentacion brillante", names)

        realistic = lighting_profiles.get_builtin_profile("Fotometrico realista")
        self.assertEqual(realistic["local"]["light_mode"], "PhotometricSpot")
        self.assertFalse(realistic["materials"]["enabled"])

        visible = lighting_profiles.get_builtin_profile("Fotometrico visible")
        self.assertEqual(visible["materials"]["mode"], "Soft")

    def test_custom_profiles_round_trip_and_cannot_replace_builtin(self):
        custom = {
            "Mi perfil": lighting_profiles.get_builtin_profile("Fotometrico visible"),
            "Arquitectonico equilibrado": lighting_profiles.get_builtin_profile(
                "Presentacion brillante"
            ),
        }
        encoded = lighting_profiles.dumps_custom_profiles(custom)
        decoded = lighting_profiles.loads_custom_profiles(encoded)
        self.assertEqual(list(decoded), ["Mi perfil"])
        self.assertEqual(decoded["Mi perfil"]["local"]["lumens"], 3600.0)

    def test_invalid_json_is_safe(self):
        self.assertEqual(lighting_profiles.loads_custom_profiles("{bad json"), {})


if __name__ == "__main__":
    unittest.main()
