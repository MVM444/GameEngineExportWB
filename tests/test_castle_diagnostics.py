import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from GameEngineExportWB.core import castle_diagnostics
from GameEngineExportWB.ui.output_defaults import (
    compute_output_defaults,
    temporary_output_directory,
)


class FakeParams:
    def __init__(self, **values):
        self.values = values

    def GetString(self, key, default=""):
        return self.values.get(key, default)


class FakeAnalyzer:
    @staticmethod
    def analyze_x3d(path, top_n=20, progress_callback=None):
        if progress_callback:
            progress_callback(1, 1)
        return {
            "summary": {
                "shapes": 10,
                "triangles_approx": 100,
                "duplicate_def_names": 0,
            },
            "lights": {"counts": {"SpotLight": 58}},
        }

    @staticmethod
    def write_reports(report, path):
        source = Path(path)
        base = source.with_suffix("")
        json_path = base.with_name(base.name + ".gee.analysis.json")
        md_path = base.with_name(base.name + ".gee.analysis.md")
        json_path.write_text("{}", encoding="utf-8")
        md_path.write_text("# test", encoding="utf-8")
        return json_path, md_path


class CastleDiagnosticsTests(unittest.TestCase):
    def _source(self, folder):
        x3d = Path(folder) / "scene.x3d"
        x3d.write_text("<X3D><Scene/></X3D>", encoding="utf-8")
        return x3d

    def _fake_viewer(self, folder):
        viewer = Path(folder) / "castle-model-viewer.exe"
        viewer.write_bytes(b"")
        return viewer

    def test_capture_command_uses_documented_options(self):
        command = castle_diagnostics.build_viewer_command(
            "castle-model-viewer.exe",
            "scene.x3d",
            mode="capture",
            viewpoint="GameStart",
            width=1600,
            height=900,
            anti_alias=4,
            screenshot_path="capture.png",
        )
        self.assertIn("--debug-log-shaders", command)
        self.assertEqual(command[command.index("--geometry") + 1], "1600x900")
        self.assertEqual(command[-3:], ["--screenshot", "0", "capture.png"])

    def test_diagnostic_paths_are_bounded_and_deterministic(self):
        with tempfile.TemporaryDirectory() as folder:
            long_parent = Path(folder) / ("nested_" + "a" * 80)
            source = long_parent / (("scene_" * 18) + ".x3d")
            run_id = "capture_" + "b" * 80
            first = castle_diagnostics.diagnostic_paths(source, run_id=run_id)
            second = castle_diagnostics.diagnostic_paths(source, run_id=run_id)

            self.assertEqual(first, second)
            self.assertEqual(first["folder"].name, "_castle_debug")
            derived_analysis = first["analysis_base"].with_suffix("").with_name(
                first["analysis_base"].with_suffix("").name + ".gee.analysis.json"
            )
            for path in tuple(first.values()) + (derived_analysis,):
                self.assertLessEqual(
                    len(str(path.absolute())),
                    castle_diagnostics.MAX_DIAGNOSTIC_PATH_CHARS,
                    str(path),
                )

    def test_analyze_mode_is_read_only_json_compatible_and_uses_debug_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            x3d = self._source(folder)
            before = x3d.read_bytes()
            manifest = castle_diagnostics.run_diagnostic(
                x3d,
                mode="analyze",
                validate=False,
                analyzer_module=FakeAnalyzer,
                run_id="test",
                document="SmallExample",
            )

            self.assertEqual(x3d.read_bytes(), before)
            self.assertTrue(manifest["success"])
            self.assertEqual(manifest["operation"], "castle_diagnostics")
            self.assertEqual(manifest["schema_version"], "1.0")
            self.assertEqual(manifest["document"], "SmallExample")
            self.assertTrue(manifest["source_unchanged"])
            self.assertEqual(manifest["validation"]["status"], "disabled")
            self.assertEqual(manifest["recommendations"][0]["suggested_value"], 8)
            json.dumps(manifest)

            debug_folder = Path(folder) / "_castle_debug"
            for key in ("analysis_json", "analysis_markdown", "manifest", "summary"):
                output = Path(folder) / manifest["outputs"][key]
                self.assertTrue(output.is_file())
                self.assertEqual(output.parent, debug_folder)
            serialized = (Path(folder) / manifest["outputs"]["manifest"]).read_text(
                encoding="utf-8"
            )
            self.assertNotIn(str(Path(folder).resolve()), serialized)
            self.assertEqual(manifest["x3d"], "scene.x3d")
            self.assertFalse((Path(folder) / "scene.gee.analysis.json").exists())

    def test_interactive_mode_launches_viewer_with_shader_log(self):
        with tempfile.TemporaryDirectory() as folder:
            x3d = self._source(folder)
            viewer = self._fake_viewer(folder)
            started = {"status": "started", "pid": 42, "command": [], "log": "test.log"}
            with mock.patch.object(castle_diagnostics, "_start_viewer", return_value=started) as launch:
                manifest = castle_diagnostics.run_diagnostic(
                    x3d,
                    viewer_path=viewer,
                    mode="interactive",
                    validate=False,
                    analyzer_module=FakeAnalyzer,
                    run_id="interactive",
                )
            command = launch.call_args.args[0]
            self.assertIn("--debug-log-shaders", command)
            self.assertNotIn("--screenshot", command)
            self.assertEqual(manifest["castle"]["pid"], 42)

    def test_capture_mode_exposes_expected_screenshot(self):
        with tempfile.TemporaryDirectory() as folder:
            x3d = self._source(folder)
            viewer = self._fake_viewer(folder)
            started = {"status": "started", "pid": 43, "command": [], "log": "test.log"}
            with mock.patch.object(castle_diagnostics, "_start_viewer", return_value=started) as launch:
                manifest = castle_diagnostics.run_diagnostic(
                    x3d,
                    viewer_path=viewer,
                    mode="capture",
                    validate=False,
                    analyzer_module=FakeAnalyzer,
                    run_id="capture",
                    viewpoint="GameStart",
                    width=1280,
                    height=720,
                    anti_alias=2,
                )
            command = launch.call_args.args[0]
            self.assertEqual(command[command.index("--geometry") + 1], "1280x720")
            self.assertEqual(command[command.index("--viewpoint") + 1], "GameStart")
            self.assertIn("--screenshot", command)
            screenshot = Path(folder) / manifest["outputs"]["screenshot"]
            self.assertEqual(screenshot.parent, Path(folder) / "_castle_debug")

    def test_viewer_logs_are_separate_and_manifest_completes(self):
        with tempfile.TemporaryDirectory() as folder:
            folder_path = Path(folder)
            manifest_path = folder_path / "manifest.json"
            summary_path = folder_path / "summary.md"
            stdout_path = folder_path / "stdout.log"
            native_path = folder_path / "native.log"
            screenshot_path = folder_path / "capture.png"
            source_native = folder_path / "castle-model-viewer.log"
            source_native.write_text("native castle log", encoding="utf-8")
            screenshot_path.write_bytes(b"png")
            manifest_path.write_text(
                json.dumps({
                    "castle": {"pid": 77, "status": "started", "stdout_log": str(stdout_path)},
                    "outputs": {},
                    "warnings": [],
                    "analysis": {},
                }),
                encoding="utf-8",
            )

            process = mock.Mock()
            process.pid = 77
            process.wait.return_value = 0
            castle_diagnostics._update_manifest_after_viewer_exit(
                process,
                source_native,
                native_path,
                None,
                manifest_path,
                summary_path,
                screenshot_path,
            )
            result = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(result["castle"]["status"], "completed")
            self.assertEqual(result["castle"]["return_code"], 0)
            self.assertTrue(result["castle"]["screenshot_exists"])
            self.assertEqual(native_path.read_text(encoding="utf-8"), "native castle log")
            self.assertNotEqual(str(native_path), str(stdout_path))


    def test_validation_command_uses_input_before_validate_option(self):
        with tempfile.TemporaryDirectory() as folder:
            x3d = self._source(folder)
            output = Path(folder) / "validation.txt"
            completed = mock.Mock(stdout="valid", returncode=0)
            with mock.patch.object(castle_diagnostics.subprocess, "run", return_value=completed) as run:
                result = castle_diagnostics._run_validation(
                    Path("castle-model-converter.exe"), x3d, output, 30
                )
            self.assertEqual(
                run.call_args.args[0],
                ["castle-model-converter.exe", str(x3d), "--validate"],
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(
                result["command"],
                ["castle-model-converter.exe", "scene.x3d", "--validate"],
            )
            self.assertEqual(output.read_text(encoding="utf-8"), "valid")

    def test_validation_log_redacts_known_private_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            x3d = self._source(folder)
            output = Path(folder) / "validation.txt"
            converter = Path(folder) / "castle-model-converter.exe"
            completed = mock.Mock(
                stdout="checking " + str(x3d) + " with " + str(converter),
                returncode=0,
            )
            with mock.patch.object(
                castle_diagnostics.subprocess, "run", return_value=completed
            ):
                castle_diagnostics._run_validation(
                    converter, x3d, output, 30, display_root=Path(folder)
                )
            log_text = output.read_text(encoding="utf-8")
            self.assertNotIn(str(Path(folder).resolve()), log_text)
            self.assertIn("<private-path>", log_text)

    def test_find_converter_beside_viewer(self):
        with tempfile.TemporaryDirectory() as folder:
            viewer = self._fake_viewer(folder)
            converter = Path(folder) / "castle-model-converter.exe"
            converter.write_bytes(b"")
            self.assertEqual(
                castle_diagnostics.find_castle_converter(viewer), converter.resolve()
            )

    def test_unsaved_document_never_reuses_previous_output_path(self):
        params = FakeParams(output_dir=r"C:\OtherComputer\OldProject", base_name="OldScene")
        output_dir, base_name, document_key = compute_output_defaults(params, None)
        self.assertEqual(output_dir, temporary_output_directory())
        self.assertEqual(base_name, "")
        self.assertEqual(document_key, "")

    def test_saved_document_uses_its_own_folder_and_stem(self):
        with tempfile.TemporaryDirectory() as folder:
            document = Path(folder) / "Current Project.FCStd"
            params = FakeParams(output_dir=r"C:\OtherComputer\OldProject", base_name="OldScene")
            output_dir, base_name, document_key = compute_output_defaults(params, document)
        self.assertEqual(Path(output_dir), document.parent)
        self.assertEqual(base_name, "Current_Project")
        self.assertEqual(document_key, str(document))


if __name__ == "__main__":
    unittest.main()
