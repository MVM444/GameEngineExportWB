"""Static distribution contract for the modern FreeCAD Addon source."""

from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "freecad" / "GameEngineExportWB"
NS = {"p": "https://wiki.freecad.org/Package_Metadata"}
TEXT_SUFFIXES = {".py", ".FCMacro", ".md", ".xml", ".txt", ".ts", ".json", ".svg", ".toml"}
PUBLIC_ROOT_FILES = ("package.xml", "pyproject.toml", "README.md", "LICENSE", ".gitignore")
PACKAGE_DIRS = ("commands", "core", "ui", "adapters", "macros", "resources")

class AddonDistributionTests(unittest.TestCase):
    def test_modern_namespace_layout_exists(self):
        for name in PUBLIC_ROOT_FILES:
            self.assertTrue((ROOT / name).is_file(), name)
        self.assertTrue((ROOT / "freecad").is_dir())
        self.assertFalse((ROOT / "freecad" / "__init__.py").exists())
        self.assertTrue((PACKAGE / "__init__.py").is_file())
        self.assertTrue((PACKAGE / "init_gui.py").is_file())
        for name in PACKAGE_DIRS:
            self.assertTrue((PACKAGE / name).is_dir(), name)
        self.assertFalse((ROOT / "Init.py").exists())
        self.assertFalse((ROOT / "InitGui.py").exists())

    def test_package_metadata_matches_freecad_113_contract(self):
        package = ET.parse(ROOT / "package.xml").getroot()
        self.assertEqual(package.tag, "{" + NS["p"] + "}package")
        self.assertEqual(package.findtext("p:name", namespaces=NS), "GameEngineExportWB")
        self.assertRegex(package.findtext("p:version", namespaces=NS) or "", r"^\d+\.\d+\.\d+$")
        license_node = package.find("p:license", NS)
        self.assertIsNotNone(license_node)
        self.assertEqual(license_node.text, "MIT")
        self.assertEqual(license_node.attrib.get("file"), "LICENSE")
        workbench = package.find("p:content/p:workbench", NS)
        self.assertIsNotNone(workbench)
        self.assertEqual(workbench.findtext("p:classname", namespaces=NS), "GameEngineExportWorkbench")
        self.assertEqual(workbench.findtext("p:freecadmin", namespaces=NS), "1.1.3")
        icon = package.findtext("p:icon", namespaces=NS)
        self.assertTrue((ROOT / str(icon)).is_file())

    def test_gui_entrypoint_is_namespaced_and_has_no_path_hack(self):
        source = (PACKAGE / "init_gui.py").read_text(encoding="utf-8")
        self.assertIn("from .ui.workbench import register_workbench", source)
        self.assertIn("_register_workbench()", source)
        self.assertNotIn("sys.path", source)
        self.assertNotIn("GameEngineExportWB.ui", source)

    def test_runtime_has_no_legacy_package_imports_or_sys_path_mutation(self):
        for folder in (PACKAGE / "commands", PACKAGE / "core", PACKAGE / "ui", PACKAGE / "adapters", PACKAGE / "macros"):
            for path in folder.rglob("*"):
                if not path.is_file() or path.suffix not in {".py", ".FCMacro"}:
                    continue
                source = path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("from GameEngineExportWB", source, str(path))
                self.assertNotIn('"GameEngineExportWB.', source, str(path))
                self.assertNotIn("sys.path.insert", source, str(path))

    def test_gui_smoke_uses_namespaced_translation_directory(self):
        smoke_source = (ROOT / "tests" / "freecad_gui_addon_smoke.py").read_text(encoding="utf-8")
        self.assertIn(' / "resources" / "translations" / ', smoke_source)
        self.assertNotIn('.parent / "translations"', smoke_source)

    def test_toolbar_contract_and_reload_menu_only(self):
        source = (PACKAGE / "ui" / "workbench.py").read_text(encoding="utf-8")
        self.assertIn("main_commands = [", source)
        self.assertIn("scene_ai_commands = [", source)
        self.assertIn("diagnostic_commands = [", source)
        self.assertIn("+ [reload_command.CommandName]", source)
        self.assertEqual(source.count("self.appendToolbar("), 3)

    def test_export_cache_excludes_pointer_backed_shape_material(self):
        source = (PACKAGE / "commands" / "cmd_export_and_launch.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        skipped = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "SKIPPED_PROPERTIES" for target in node.targets):
                skipped = ast.literal_eval(node.value)
                break
        self.assertIsNotNone(skipped)
        self.assertIn("ShapeMaterial", skipped)
        self.assertNotIn("Placement", skipped)

    def test_command_icons_translations_and_runtime_macros_exist(self):
        required = (
            "resources/icons/gameexport.svg", "resources/icons/gameexport_help.svg",
            "resources/icons/quick_example.svg", "resources/icons/export_launch_x3d.svg",
            "resources/icons/analyze_x3d.svg", "resources/icons/castle_diagnostics.svg",
            "resources/icons/add_light_properties.svg", "resources/icons/import_json_example.svg",
            "resources/icons/bim_doors_windows.svg", "resources/icons/quick_example_roof.svg",
            "resources/icons/reload_workbench.svg", "resources/translations/GameEngineExportWB_es-ES.qm",
            "macros/AgregarPuertasVentanasBIM_QuickExample.FCMacro",
            "macros/AgregarTechoBIM_QuickExample.FCMacro", "AI_CONTEXT.md",
        )
        for relative in required:
            self.assertTrue((PACKAGE / relative).is_file(), relative)

    def test_runtime_assets_are_real_not_staging_placeholders(self):
        icons = sorted((PACKAGE / "resources" / "icons").glob("*.svg"))
        textures = sorted((PACKAGE / "resources" / "textures").glob("*.png"))
        self.assertGreaterEqual(len(icons), 11)
        self.assertGreaterEqual(len(textures), 7)
        for icon in icons:
            image_xml = ET.parse(icon).getroot()
            self.assertTrue(image_xml.tag.endswith("svg"), str(icon))
        for texture in textures:
            self.assertEqual(texture.read_bytes()[:8], b"\x89PNG\r\n\x1a\n", str(texture))
        qm = PACKAGE / "resources" / "translations" / "GameEngineExportWB_es-ES.qm"
        self.assertEqual(qm.read_bytes()[:4], bytes.fromhex("3cb86418"))

    def test_public_text_has_no_user_paths_unc_or_email(self):
        paths = [ROOT / name for name in PUBLIC_ROOT_FILES]
        for folder in (PACKAGE, ROOT / "examples", ROOT / "tests"):
            paths.extend(path for path in folder.rglob("*")
                         if path.is_file() and path.suffix in TEXT_SUFFIXES
                         and "__pycache__" not in path.parts
                         and ".bak" not in path.name and not path.name.startswith("pre_"))
        patterns = (
            re.compile(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s]+", re.IGNORECASE),
            re.compile("/" + "Users/" + r"[^/\s]+"),
            re.compile("/" + "home/" + r"[^/\s]+"),
            re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        )
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in patterns:
                self.assertIsNone(pattern.search(text), str(path.relative_to(ROOT)))

    def test_internal_material_is_excluded_by_default(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for entry in ("/notes/", "/ADDON_DISTRIBUTION.md", "/ESTADO_PROYECTO.md",
                      "/FREECAD_MACRO_RULES.md", "/RESULTADO_CODEX.md", "/TAREA_ACTUAL.md"):
            self.assertIn(entry, ignore)
        for pattern in ("__pycache__/", "*.py[cod]", "*.bak.*", "*.backup-*", "*.pre_*.bak.py"):
            self.assertIn(pattern, ignore)

if __name__ == "__main__":
    unittest.main()
