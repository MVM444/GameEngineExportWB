"""Solar helper placeholder for Game Engine Export WB.

Descripcion rapida: calculos simples de direccion solar.
Fecha y hora: 2025-10-13 13:54 UTC.
Instrucciones clave:
- Convertir hora local y latitud a yaw/pitch aproximados.
- Mantener logs con prefijo [GAMEEXPORT].
"""

from __future__ import annotations

from typing import List, Tuple


def solar_angles(latitude: float, local_time: str) -> Tuple[float, float]:
    """Return dummy yaw and pitch values."""
    FreeCAD = __import__("FreeCAD")
    FreeCAD.Console.PrintMessage(
        f"[GAMEEXPORT] solar_angles placeholder for lat={latitude}, time={local_time}\n"
    )
    return 0.0, -45.0


__all__: List[str] = ["solar_angles"]
