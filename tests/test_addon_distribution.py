"""Static distribution contract for the dedicated FreeCAD Addon source."""

from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
NS = {"p": "https://wiki.freecad.org/Package_Metadata"}
TEXT_SUFFIXES = {".py", ".FCMacro", ".md", ".xml", ".txt", ".ts", ".json", ".svg"}
PUBLIC_DIRS = (
    "commands",
    "core",
    "ui",
    "macros",
    "resources",
    "translations",
    "examples",
    "tests",
)
PUBLIC_ROOT_FILES = (
    "Init.py",
    "InitGui.py",
    "__init__.py",
    "i18n.py",
    "package.xml",
    "README.md",
    "AI_CONTEXT.md",
    "LICENSE",
    ".gitignore",
)


class AddonDistributionTests(unittest.TestCase):
    def test_required_root_files_exist(self):
        for name in PUBLIC_ROOT_FILES:
            self.assertTrue((ROOT / name).is_file(), name)

    def test_package_metadata_matches_freecad_113_contract(self):
        package = ET.parse(ROOT / "package.xml").getroot()
        self.assertEqual(package.tag, "{" + NS["p"] + "}package")
        self.assertEqual(package.findtext("p:name", namespaces=NS), "GameEngineExportWB")
        self.assertRegex(
            package.findtext("p:version", namespaces=NS) or "",
            r"^\d+\.\d+\.\d+$",
        )
        license_node = package.find("p:license", NS)
        self.assertIsNotNone(license_node)
        self.assertEqual(license_node.text, "MIT")
        self.assertEqual(license_node.attrib.get("file"), "LICENSE")
        workbench = package.find("p:content/p:workbench", NS)
        self.assertIsNotNone(workbench)
        self.assertEqual(workbench.findtext("p:name", namespaces=NS), "GameEngineExportWB")
        self.assertEqual(
            workbench.findtext("p:classname", namespaces=NS),
            "GameEngineExportWorkbench",
        )
        self.assertEqual(workbench.findtext("p:subdirectory", namespaces=NS), "./")
        self.assertEqual(workbench.findtext("p:freecadmin", namespaces=NS), "1.1.3")
        icon = package.findtext("p:icon", namespaces=NS)
        self.assertTrue((ROOT / str(icon)).is_file())

    def test_headless_init_does_not_load_gui(self):
        source = (ROOT / "Init.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
                imported.extend(alias.name for alias in node.names)
        joined = " ".join(imported)
        self.assertNotIn("InitGui", joined)
        self.assertNotIn("FreeCADGui", joined)
        self.assertIn("_ensure_package_parent_on_sys_path", source)
        self.assertIn("sys.path.insert(0, parent)", source)

    def test_gui_init_uses_package_imports_and_module_resource_path(self):
        source = (ROOT / "InitGui.py").read_text(encoding="utf-8")
        self.assertNotIn("from .", source)
        self.assertIn(
            "from GameEngineExportWB.ui.workbench import register_workbench",
            source,
        )
        self.assertIn("_register_workbench()", source)
        self.assertNotIn("os.path.dirname(__file__)", source)
        self.assertIn("_ensure_package_parent_on_sys_path", source)

        workbench_source = (ROOT / "ui" / "workbench.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("i18n.__file__", workbench_source)
        self.assertIn("class GameEngineExportWorkbench", workbench_source)

    def test_toolbar_contract_and_reload_menu_only(self):
        source = (ROOT / "ui" / "workbench.py").read_text(encoding="utf-8")
        self.assertIn("main_commands = [", source)
        self.assertIn("scene_ai_commands = [", source)
        self.assertIn("diagnostic_commands = [", source)
        self.assertIn("+ [reload_command.CommandName]", source)
        self.assertEqual(source.count("self.appendToolbar("), 3)
        toolbar_region = source[source.index("main_commands = [") : source.index("menu_commands = (")]
        self.assertNotIn("reload_command.CommandName", toolbar_region)

    def test_export_cache_excludes_pointer_backed_shape_material(self):
        source = (ROOT / "commands" / "cmd_export_and_launch.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        skipped = None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(
                isinstance(target, ast.Name)
                and target.id == "SKIPPED_PROPERTIES"
                for target in node.targets
            ):
                skipped = ast.literal_eval(node.value)
                break
        self.assertIsNotNone(skipped)
        self.assertIn("ShapeMaterial", skipped)
        self.assertNotIn("Placement", skipped)

    def test_command_icons_and_runtime_macros_exist(self):
        required = (
            "resources/icons/gameexport.svg",
            "resources/icons/gameexport_help.svg",
            "resources/icons/quick_example.svg",
            "resources/icons/export_launch_x3d.svg",
            "resources/icons/analyze_x3d.svg",
            "resources/icons/castle_diagnostics.svg",
            "resources/icons/add_light_properties.svg",
            "resources/icons/import_json_example.svg",
            "resources/icons/bim_doors_windows.svg",
            "resources/icons/quick_example_roof.svg",
            "resources/icons/reload_workbench.svg",
            "macros/AgregarPuertasVentanasBIM_QuickExample.FCMacro",
            "macros/AgregarTechoBIM_QuickExample.FCMacro",
            "AI_CONTEXT.md",
        )
        for relative in required:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_public_text_has_no_user_paths_unc_or_email(self):
        paths = [ROOT / name for name in PUBLIC_ROOT_FILES]
        for folder in PUBLIC_DIRS:
            paths.extend(
                path
                for path in (ROOT / folder).rglob("*")
                if path.is_file()
                and path.suffix in TEXT_SUFFIXES
                and "__pycache__" not in path.parts
                and ".bak" not in path.name
                and not path.name.startswith("pre_")
            )
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
        for entry in (
            "/notes/",
            "/ADDON_DISTRIBUTION.md",
            "/ESTADO_PROYECTO.md",
            "/FREECAD_MACRO_RULES.md",
            "/RESULTADO_CODEX.md",
            "/TAREA_ACTUAL.md",
        ):
            self.assertIn(entry, ignore)
        for pattern in (
            "__pycache__/",
            "*.py[cod]",
            "*.bak.*",
            "*.backup-*",
            "*.pre_*.bak.py",
        ):
            self.assertIn(pattern, ignore)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("Macros-de-Freecad/GameEngineExportWB", readme)


if __name__ == "__main__":
    unittest.main()
