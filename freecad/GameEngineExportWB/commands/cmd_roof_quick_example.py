"""Command to add a simple roof to a generated/imported quick example."""

from __future__ import annotations

import os
import time

import FreeCAD
import FreeCADGui

from .. import i18n


LOG_PREFIX = "[GAMEEXPORT] "
COMMAND_VERSION = str(int(time.time()))
ICON_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "resources", "icons", "quick_example_roof.svg")
).replace(os.sep, "/")


def _macro_path() -> str:
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "macros", "AgregarTechoBIM_QuickExample.FCMacro")
    )


class CommandClass:
    """FreeCAD command wrapper for quick example roof insertion."""

    CommandName = "GameEngineExport_AddRoof_" + COMMAND_VERSION

    def GetResources(self):  # noqa: N802
        return {
            "MenuText": i18n.bi("Agregar techo", "Add Roof"),
            "ToolTip": i18n.bi("Agregar techo simple a dos aguas al ultimo Quick Example generado o importado desde JSON.", "Add a simple gable roof to the last Quick Example generated or imported from JSON."),
            "Pixmap": ICON_PATH,
        }

    def Activated(self):  # noqa: N802
        macro = _macro_path()
        if not os.path.exists(macro):
            FreeCAD.Console.PrintError(LOG_PREFIX + "Macro not found: " + os.path.basename(macro) + "\n")
            return
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "Running roof macro: " + os.path.basename(macro) + "\n")
        namespace = {"__name__": "__main__", "__file__": macro}
        with open(macro, "r", encoding="utf-8-sig") as handle:
            code = compile(handle.read(), macro, "exec")
        exec(code, namespace)

    def IsActive(self):  # noqa: N802
        return FreeCAD.ActiveDocument is not None


def register():
    command = CommandClass()
    FreeCADGui.addCommand(command.CommandName, command)
    return command
