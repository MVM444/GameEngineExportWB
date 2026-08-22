"""Workbench registration for the FreeCAD GUI adapter.

This module is imported normally by ``InitGui.py`` so the Workbench class and
its methods retain a standard package-global namespace under FreeCAD 1.1.
"""

import os

import FreeCAD
import FreeCADGui

from .. import i18n
from ..commands import cmd_add_light_properties
from ..commands import cmd_analyze_x3d
from ..commands import cmd_bim_doors_windows
from ..commands import cmd_castle_diagnostics
from ..commands import cmd_export_and_launch
from ..commands import cmd_help
from ..commands import cmd_import_json_example
from ..commands import cmd_open_panel
from ..commands import cmd_quick_examples
from ..commands import cmd_reload_workbench
from ..commands import cmd_roof_quick_example
from . import panel_info


LOG_PREFIX = "[GAMEEXPORT] "
WORKBENCH_ID = "GameEngineExportWorkbench"


class GameEngineExportWorkbench(FreeCADGui.Workbench):
    """Workbench definition for Game Engine Export WB."""

    MenuText = i18n.tr("Game Engine Export WB", i18n.WORKBENCH_CONTEXT)
    ToolTip = i18n.tr(
        "Export FreeCAD scenes to Castle Game Engine",
        i18n.WORKBENCH_CONTEXT,
    )
    _package_dir = os.path.dirname(os.path.abspath(i18n.__file__))
    _icon_path = os.path.join(
        _package_dir,
        "resources",
        "icons",
        "gameexport.svg",
    )
    Icon = _icon_path.replace(os.sep, "/")

    def Initialize(self):  # noqa: N802
        """Register commands and set up menus and toolbars."""
        i18n.install_translation_path()
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "Initializing workbench menus\n")
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX + "Workbench package: GameEngineExportWB\n"
        )
        export_command = cmd_open_panel.CommandClass()
        export_launch_command = cmd_export_and_launch.CommandClass()
        help_command = cmd_help.CommandClass()
        analyze_x3d_command = cmd_analyze_x3d.CommandClass()
        castle_diagnostics_command = cmd_castle_diagnostics.CommandClass()
        light_command = cmd_add_light_properties.CommandClass()
        quick_example_command = cmd_quick_examples.CommandClass()
        import_json_command = cmd_import_json_example.CommandClass()
        bim_doors_windows_command = cmd_bim_doors_windows.CommandClass()
        roof_command = cmd_roof_quick_example.CommandClass()
        reload_command = cmd_reload_workbench.CommandClass()

        registered = (
            export_command,
            export_launch_command,
            help_command,
            analyze_x3d_command,
            castle_diagnostics_command,
            light_command,
            quick_example_command,
            import_json_command,
            bim_doors_windows_command,
            roof_command,
            reload_command,
        )
        for command in registered:
            FreeCADGui.addCommand(command.CommandName, command)

        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Registered export command: "
            + export_command.CommandName
            + "\n"
        )
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Registered one-click export command: "
            + export_launch_command.CommandName
            + "\n"
        )
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Registered X3D analysis command: "
            + analyze_x3d_command.CommandName
            + "\n"
        )
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Registered Castle diagnostics command: "
            + castle_diagnostics_command.CommandName
            + "\n"
        )

        main_commands = [
            quick_example_command.CommandName,
            export_launch_command.CommandName,
            export_command.CommandName,
            help_command.CommandName,
        ]
        scene_ai_commands = [
            light_command.CommandName,
            import_json_command.CommandName,
            bim_doors_windows_command.CommandName,
            roof_command.CommandName,
        ]
        diagnostic_commands = [
            analyze_x3d_command.CommandName,
            castle_diagnostics_command.CommandName,
        ]
        menu_commands = (
            main_commands
            + scene_ai_commands
            + diagnostic_commands
            + [reload_command.CommandName]
        )

        self.appendToolbar(
            i18n.tr("Game Engine Export", i18n.WORKBENCH_CONTEXT),
            main_commands,
        )
        self.appendToolbar(
            i18n.bi(
                "Game Engine Export - Escena / IA",
                "Game Engine Export - Scene / AI",
            ),
            scene_ai_commands,
        )
        self.appendToolbar(
            i18n.bi(
                "Game Engine Export - Diagnostico",
                "Game Engine Export - Diagnostics",
            ),
            diagnostic_commands,
        )
        self.appendMenu(
            i18n.tr("Game Engine Export", i18n.WORKBENCH_CONTEXT),
            menu_commands,
        )
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Toolbars registered: main=4, scene_ai=4, diagnostics=2; "
            + "reload is menu-only\n"
        )

    def Activated(self):  # noqa: N802
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "Workbench activated\n")
        panel_info.schedule_startup_tips()

    def Deactivated(self):  # noqa: N802
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "Workbench deactivated\n")


def _ensure_clean_registration():
    """Remove an existing runtime registration before adding the Workbench."""
    try:
        workbenches = dict(
            getattr(FreeCADGui, "listWorkbenches", lambda: {})() or {}
        )
    except Exception:
        workbenches = {}

    if WORKBENCH_ID in workbenches and hasattr(FreeCADGui, "removeWorkbench"):
        try:
            try:
                FreeCADGui.activateWorkbench("StartWorkbench")
            except Exception:
                pass
            FreeCADGui.removeWorkbench(WORKBENCH_ID)
            FreeCAD.Console.PrintMessage(
                LOG_PREFIX + "Removed previous workbench registration\n"
            )
        except Exception as exc:  # pragma: no cover
            FreeCAD.Console.PrintWarning(
                LOG_PREFIX
                + "Could not remove previous workbench registration: "
                + str(exc)
                + "\n"
            )


def register_workbench():
    """Register the single current Workbench implementation."""
    _ensure_clean_registration()
    FreeCADGui.addWorkbench(GameEngineExportWorkbench())


__all__ = [
    "GameEngineExportWorkbench",
    "WORKBENCH_ID",
    "register_workbench",
]
