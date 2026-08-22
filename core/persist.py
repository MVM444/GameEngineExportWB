"""Persistence helpers for Game Engine Export WB.

Descripcion rapida: manejo de ParamGet y sidecar JSON.
Fecha y hora: 2025-10-13 13:54 UTC.
Instrucciones clave:
- Guardar configuracion global en User parameter:BaseApp/Preferences/GameEngineExport.
- Manejar sidecar <DocStem>.gee.json en la carpeta del documento.
- Mantener logs con prefijo [GAMEEXPORT].
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


PREF_GROUP = "User parameter:BaseApp/Preferences/GameEngineExport"


def load_global_prefs(param_get) -> Dict[str, object]:
    """Placeholder for reading global preferences."""
    FreeCAD = __import__("FreeCAD")
    FreeCAD.Console.PrintMessage("[GAMEEXPORT] load_global_prefs placeholder\n")
    return {}


def save_global_prefs(param_get, data: Dict[str, object]) -> None:
    """Placeholder for writing global preferences."""
    FreeCAD = __import__("FreeCAD")
    FreeCAD.Console.PrintMessage("[GAMEEXPORT] save_global_prefs placeholder\n")


def load_sidecar(doc_path: Path) -> Dict[str, object]:
    """Read sidecar JSON if present."""
    FreeCAD = __import__("FreeCAD")
    sidecar = doc_path.with_suffix(".gee.json")
    FreeCAD.Console.PrintMessage(
        f"[GAMEEXPORT] load_sidecar checking {sidecar.name}\n"
    )
    if not sidecar.exists():
        return {}
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - placeholder handling
        FreeCAD.Console.PrintError(f"[GAMEEXPORT] Failed to read sidecar: {exc}\n")
        return {}


def save_sidecar(doc_path: Path, data: Dict[str, object]) -> Path:
    """Write sidecar JSON."""
    sidecar = doc_path.with_suffix(".gee.json")
    FreeCAD = __import__("FreeCAD")
    sidecar.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    FreeCAD.Console.PrintMessage(f"[GAMEEXPORT] Sidecar saved: {sidecar.name}\n")
    return sidecar


__all__: List[str] = ["PREF_GROUP", "load_global_prefs", "save_global_prefs", "load_sidecar", "save_sidecar"]
