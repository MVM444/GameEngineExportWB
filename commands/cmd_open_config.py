"""Command to open the configuration TaskPanel.

Descripcion rapida: comando para ajustar rutas y preferencias globales.
Fecha y hora: 2025-10-13 19:00 UTC.
Instrucciones clave:
- Mostrar panel de configuracion aun sin documento activo.
- Usar logs con prefijo [GAMEEXPORT].
- Mantener cadenas ASCII.
"""

import os

import FreeCAD
import FreeCADGui

from ..ui import panel_config

ICON_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "resources", "icons", "gameexport.svg")
).replace(os.sep, "/")


class CommandClass:
    """FreeCAD command wrapper for the configuration TaskPanel."""

    CommandName = "GameEngineExport_Config"

    def GetResources(self):  # noqa: N802 (FreeCAD API)
        return {
            "MenuText": "Configuracion",
            "ToolTip": "Ajustar rutas y preferencias de exportacion",
            "Pixmap": ICON_PATH,
        }

    def Activated(self):  # noqa: N802
        FreeCAD.Console.PrintMessage("[GAMEEXPORT] Opening configuration panel\n")
        FreeCADGui.Control.showDialog(panel_config.ConfigTaskPanel())

    def IsActive(self):  # noqa: N802
        return True
