"""FreeCAD helper utilities for Game Engine Export WB.

Descripcion rapida: utilidades compartidas para logs, seleccion y rutas.
Fecha y hora: 2025-10-13 13:54 UTC.
Instrucciones clave:
- Centralizar logs con prefijo [GAMEEXPORT].
- Proveer validaciones futuras para nombres ASCII y existencia de GameStart.
"""

from __future__ import annotations

from typing import Iterable, List


def log_info(message: str) -> None:
    """Print info messages with the required prefix."""
    FreeCAD = __import__("FreeCAD")
    FreeCAD.Console.PrintMessage(f"[GAMEEXPORT] {message}\n")


def log_error(message: str) -> None:
    """Print error messages with the required prefix."""
    FreeCAD = __import__("FreeCAD")
    FreeCAD.Console.PrintError(f"[GAMEEXPORT] ERROR: {message}\n")


def selection_labels(selection: Iterable[object]) -> List[str]:
    """Return labels for selected objects (placeholder)."""
    return [getattr(obj, "Label", "") for obj in selection]


__all__: List[str] = ["log_info", "log_error", "selection_labels"]
