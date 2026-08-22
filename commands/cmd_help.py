"""GameEngineExportWB Help command.

Name: commands/cmd_help.py
Purpose: open the generous Workbench help maintained by ui.panel_info.
Main behavior: uses the current FreeCAD language and never duplicates the manual text.
Modification notes: keep this command thin; help content belongs in panel_info.py.
Version: 2026-08-21-help-reload-privacy-v2
Date and time: 2026-08-21 08:24 -06:00
"""

from __future__ import annotations

import importlib
import os
import sys

import FreeCAD

from .. import i18n


LOG_PREFIX = "[GAMEEXPORT] "
ICON_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "resources", "icons", "gameexport_help.svg")
).replace(os.sep, "/")


class CommandClass:
    """FreeCAD command wrapper for the Workbench Help dialog."""

    CommandName = "GameEngineExport_Help"

    def GetResources(self):  # noqa: N802
        return {
            "MenuText": i18n.tr("Help"),
            "ToolTip": i18n.bi("Abrir primeros pasos, botones, IA/JSON e informacion", "Open Getting Started, Buttons, AI/JSON, and Information"),
            "Pixmap": ICON_PATH,
        }

    def Activated(self):  # noqa: N802
        # Do not keep a module object imported through ``from ..ui import`` here.
        # The development hot-restart purges GameEngineExportWB modules from
        # sys.modules, while Python packages may still retain an old module as
        # an attribute. importlib.reload(old_module) then raises:
        # "module ... not in sys.modules". Always resolve the canonical live
        # module by its fully-qualified name first.
        module_name = "GameEngineExportWB.ui.panel_info"
        importlib.invalidate_caches()
        current = sys.modules.get(module_name)
        if current is None:
            panel_info = importlib.import_module(module_name)
            action = "imported"
        else:
            panel_info = importlib.reload(current)
            action = "reloaded"
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Help UI "
            + action
            + ": "
            + module_name
            + "\n"
        )
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "Opening Help dialog\n")
        panel_info.show_help_dialog()

    def IsActive(self):  # noqa: N802
        return True
