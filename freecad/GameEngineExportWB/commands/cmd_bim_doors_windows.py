"""Command to add BIM doors/windows to a generated quick example."""

from __future__ import annotations

import os
import time

import FreeCAD
import FreeCADGui

from .. import i18n


LOG_PREFIX = "[GAMEEXPORT] "
COMMAND_VERSION = str(int(time.time()))
ICON_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "resources", "icons", "bim_doors_windows.svg")
).replace(os.sep, "/")


def _macro_path() -> str:
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "macros", "AgregarPuertasVentanasBIM_QuickExample.FCMacro")
    )


class CommandClass:
    """FreeCAD command wrapper for BIM doors/windows insertion."""

    CommandName = "GameEngineExport_AddBIMDoorsWindows_" + COMMAND_VERSION

    def GetResources(self):  # noqa: N802
        return {
            "MenuText": i18n.bi("Puertas y ventanas BIM", "BIM Doors and Windows"),
            "ToolTip": i18n.bi("Agregar puertas abiertas y ventanas BIM al ultimo Quick Example generado.", "Add open doors and BIM windows to the last generated Quick Example."),
            "Pixmap": ICON_PATH,
        }

    def Activated(self):  # noqa: N802
        macro = _macro_path()
        if not os.path.exists(macro):
            FreeCAD.Console.PrintError(LOG_PREFIX + "Macro not found: " + os.path.basename(macro) + "\n")
            return
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "Running BIM doors/windows macro: " + os.path.basename(macro) + "\n")
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
