import gzip
import tempfile
import unittest
from pathlib import Path

try:
    from GameEngineExportWB.core import x3d_analyzer
except ImportError:
    import x3d_analyzer


SAMPLE = '''<?xml version="1.0" encoding="UTF-8"?>
<X3D version="3.2"><Scene>
  <Transform DEF="PotLink001"><Shape><IndexedFaceSet DEF="PotMesh" coordIndex="0 1 2 -1 0 2 3 -1"><Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/></IndexedFaceSet></Shape></Transform>
  <Transform DEF="PotLink002"><Shape><IndexedFaceSet DEF="PotMesh_2" coordIndex="0 1 2 -1 0 2 3 -1"><Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/></IndexedFaceSet></Shape></Transform>
  <PointLight DEF="Light1" radius="6" intensity="0.5"/>
  <PointLight DEF="Light2" radius="6" intensity="0.5"/>
</Scene></X3D>'''


class X3DAnalyzerTests(unittest.TestCase):
    def _assert_report(self, report):
        self.assertEqual(report["summary"]["shapes"], 2)
        self.assertEqual(report["summary"]["geometry_nodes"], 2)
        self.assertEqual(report["summary"]["vertices"], 8)
        self.assertEqual(report["summary"]["triangles_approx"], 4)
        self.assertEqual(report["summary"]["duplicate_geometry_groups"], 1)
        self.assertEqual(report["lights"]["counts"]["PointLight"], 2)
        self.assertEqual(report["lights"]["radius"]["PointLight"]["average"], 6.0)
        self.assertEqual(report["summary"]["duplicate_def_names"], 0)

    def test_plain_x3d(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.x3d"
            path.write_text(SAMPLE, encoding="utf-8")
            original = path.read_bytes()
            report = x3d_analyzer.analyze_x3d(path)
            self._assert_report(report)
            json_path, md_path = x3d_analyzer.write_reports(report, path)
            self.assertTrue(json_path.is_file())
            self.assertTrue(md_path.is_file())
            markdown = md_path.read_text(encoding="utf-8")
            self.assertIn("PotLink001", markdown)
            self.assertIn("Radio PointLight: promedio 6.000 m", markdown)
            self.assertIn("enlaces exportados como copias completas", markdown)
            self.assertEqual(path.read_bytes(), original)

    def test_gzip_x3dz(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.x3dz"
            path.write_bytes(gzip.compress(SAMPLE.encode("utf-8")))
            report = x3d_analyzer.analyze_x3d(path)
            self._assert_report(report)
            self.assertTrue(report["file"]["gzip"])

    def test_duplicate_defs_and_unresolved_use(self):
        payload = '''<X3D><Scene><Group DEF="Same"/><Group DEF="Same"/><Group USE="Missing"/></Scene></X3D>'''
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.x3d"
            path.write_text(payload, encoding="utf-8")
            report = x3d_analyzer.analyze_x3d(path)
            self.assertEqual(report["summary"]["duplicate_def_names"], 1)
            self.assertEqual(report["unresolved_uses"][0]["name"], "Missing")


if __name__ == "__main__":
    unittest.main()
