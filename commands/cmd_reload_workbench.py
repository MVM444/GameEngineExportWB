"""Reload GameEngineExportWB commands and export modules without restarting.

Name: commands/cmd_reload_workbench.py
Purpose: refresh live command handlers during development without restarting FreeCAD.
Main behavior: reloads every registered GameEngineExportWB command and the export panel runtime.
Modification notes: keep this list synchronized with InitGui.py, including Help and Castle Diagnostics.
Version: 2026-08-21-privacy-safe-runtime-logs-v1
Date and time: 2026-08-21 08:24 -06:00
"""

import importlib
import os
import sys

import FreeCAD
import FreeCADGui

from .. import i18n

ICON_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "resources",
        "icons",
        "reload_workbench.svg",
    )
).replace(os.sep, "/")

COMMAND_MODULE_NAMES = (
    "GameEngineExportWB.commands.cmd_open_panel",
    "GameEngineExportWB.commands.cmd_export_and_launch",
    "GameEngineExportWB.commands.cmd_help",
    "GameEngineExportWB.commands.cmd_analyze_x3d",
    "GameEngineExportWB.commands.cmd_castle_diagnostics",
    "GameEngineExportWB.commands.cmd_add_light_properties",
    "GameEngineExportWB.commands.cmd_quick_examples",
    "GameEngineExportWB.commands.cmd_import_json_example",
    "GameEngineExportWB.commands.cmd_bim_doors_windows",
    "GameEngineExportWB.commands.cmd_roof_quick_example",
)


def _reload_or_import(module_name):
    """Reload a live module or import it again after a loader purge."""
    module = sys.modules.get(module_name)
    if module is None:
        return importlib.import_module(module_name), "imported"
    return importlib.reload(module), "reloaded"


def reload_workbench_runtime():
    """Replace registered command handlers and reload the export runtime."""
    try:
        if hasattr(FreeCADGui.Control, "activeDialog") and FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
    except Exception as exc:
        FreeCAD.Console.PrintWarning(
            "[GAMEEXPORT][WARN] Could not close active dialog before reload: "
            + str(exc)
            + "\n"
        )

    importlib.invalidate_caches()
    current_i18n, i18n_action = _reload_or_import("GameEngineExportWB.i18n")
    try:
        current_i18n.install_translation_path()
    except Exception:
        pass
    FreeCAD.Console.PrintMessage(
        "[GAMEEXPORT] i18n " + i18n_action + ": GameEngineExportWB.i18n\n"
    )
    current_json_ai, json_ai_action = _reload_or_import("GameEngineExportWB.core.json_ai")
    FreeCAD.Console.PrintMessage(
        "[GAMEEXPORT] AI JSON core "
        + json_ai_action
        + ": GameEngineExportWB.core.json_ai\n"
    )
    current_materials, materials_action = _reload_or_import(
        "GameEngineExportWB.core.material_assignments"
    )
    FreeCAD.Console.PrintMessage(
        "[GAMEEXPORT] Material core "
        + materials_action
        + ": GameEngineExportWB.core.material_assignments\n"
    )
    current_open_panel = None
    for module_name in COMMAND_MODULE_NAMES:
        current, action = _reload_or_import(module_name)
        command = current.CommandClass()
        FreeCADGui.addCommand(command.CommandName, command)
        FreeCAD.Console.PrintMessage(
            "[GAMEEXPORT] Command "
            + action
            + ": "
            + command.CommandName
            + " | module="
            + module_name
            + "\n"
        )
        if module_name.endswith(".cmd_open_panel"):
            current_open_panel = current

    if current_open_panel is None:
        current_open_panel, _ = _reload_or_import(
            "GameEngineExportWB.commands.cmd_open_panel"
        )
    current_panel = current_open_panel._reload_export_runtime()
    FreeCAD.Console.PrintMessage(
        "[GAMEEXPORT] Workbench runtime reload complete: panel="
        + str(getattr(current_panel, "DEBUG_VERSION", "unversioned"))
        + "\n"
    )
    return True


class CommandClass:
    """FreeCAD command wrapper for a runtime-only Workbench reload."""

    CommandName = "GameEngineExport_ReloadWorkbench"

    def GetResources(self):  # noqa: N802
        return {
            "MenuText": i18n.tr("Reload Workbench"),
            "ToolTip": i18n.tr("Reload GameEngineExportWB code without restarting FreeCAD"),
            "Pixmap": ICON_PATH,
        }

    def Activated(self):  # noqa: N802
        FreeCAD.Console.PrintMessage("[GAMEEXPORT] Workbench runtime reload requested\n")
        try:
            reload_workbench_runtime()
        except Exception as exc:
            FreeCAD.Console.PrintError(
                "[GAMEEXPORT] Workbench runtime reload failed: " + str(exc) + "\n"
            )

    def IsActive(self):  # noqa: N802
        return True
