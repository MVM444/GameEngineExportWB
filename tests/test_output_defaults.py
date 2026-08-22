from pathlib import Path
import tempfile
import unittest
from unittest import mock

from GameEngineExportWB.ui.output_defaults import ensure_output_directory


class OutputDirectoryTests(unittest.TestCase):
    def test_existing_directory_is_reused_without_mkdir(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(Path, "mkdir", side_effect=PermissionError("mkdir must not run")) as mkdir:
                resolved, created = ensure_output_directory(folder)

            self.assertEqual(Path(resolved), Path(folder))
            self.assertFalse(created)
            mkdir.assert_not_called()

    def test_missing_directory_is_created(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "new" / "output"
            resolved, created = ensure_output_directory(str(target))

            self.assertEqual(Path(resolved), target)
            self.assertTrue(created)
            self.assertTrue(target.is_dir())

    def test_existing_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "output.x3d"
            target.write_text("x3d", encoding="ascii")

            with self.assertRaises(NotADirectoryError):
                ensure_output_directory(str(target))

    def test_outer_quotes_are_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            resolved, created = ensure_output_directory('"' + folder + '"')

            self.assertEqual(Path(resolved), Path(folder))
            self.assertFalse(created)


if __name__ == "__main__":
    unittest.main()
