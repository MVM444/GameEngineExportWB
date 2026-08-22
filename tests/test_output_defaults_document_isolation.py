"""Regression tests for project-isolated X3D output defaults."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "ui" / "output_defaults.py"
SPEC = importlib.util.spec_from_file_location("gee_output_defaults_test", MODULE_PATH)
output_defaults = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(output_defaults)


class FakeParams:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def GetString(self, key, default=""):
        return self.values.get(key, default)

    def SetString(self, key, value):
        self.values[key] = value


class OutputDefaultsDocumentIsolationTests(unittest.TestCase):
    def test_unsaved_document_uses_isolated_temporary_folder(self):
        with tempfile.TemporaryDirectory() as previous_dir:
            params = FakeParams(
                {"output_dir": previous_dir, "base_name": "Previous_Project"}
            )
            folder, base, key = output_defaults.compute_output_defaults(
                params, None, unsaved_name="Untitled scene"
            )
        expected = (
            Path(tempfile.gettempdir())
            / "GameEngineExportWB"
            / "Untitled_scene"
        )
        self.assertEqual(Path(folder), expected)
        self.assertEqual(base, "Untitled_scene")
        self.assertEqual(key, "")

    def test_saved_document_uses_its_own_folder_and_name(self):
        with tempfile.TemporaryDirectory() as project_dir:
            doc_path = Path(project_dir) / "Current Project.FCStd"
            params = FakeParams(
                {"output_dir": "X:/old", "base_name": "Previous_Project"}
            )
            folder, base, key = output_defaults.compute_output_defaults(params, doc_path)
            self.assertEqual(folder, project_dir)
            self.assertEqual(base, "Current_Project")
            self.assertEqual(key, str(doc_path))

    def test_unsaved_export_does_not_overwrite_saved_preferences(self):
        params = FakeParams(
            {"output_dir": "X:/SavedProject", "base_name": "Saved_Project"}
        )
        output_defaults.persist_output_settings(
            params, "X:/Temporary", "Untitled", doc_path=None
        )
        self.assertEqual(params.values["output_dir"], "X:/SavedProject")
        self.assertEqual(params.values["base_name"], "Saved_Project")


if __name__ == "__main__":
    unittest.main()
