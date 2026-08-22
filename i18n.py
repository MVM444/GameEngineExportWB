"""Localization helpers for GameEngineExportWB.

Name: i18n.py
Purpose: integrate the Workbench with FreeCAD/Qt translations while keeping a small Spanish fallback during migration.
Main behavior: install the standard translations path, translate UI strings through FreeCAD.Qt.translate, and use stable language-independent identifiers in code.
Modification notes: native .qm translations take precedence. The fallback dictionary exists only so Spanish remains usable before the translation catalog is fully compiled.
Version: 2026-08-19-i18n-v1
Date and time: 2026-08-19 16:13 -06:00
"""

from __future__ import annotations

import os

import FreeCAD
import FreeCADGui


CONTEXT = "GameEngineExportWB"
WORKBENCH_CONTEXT = "Workbench"

# English source strings -> Spanish fallback. Keep this focused on visible UI.
_ES = {
    "Game Engine Export WB": "Game Engine Export WB",
    "Export FreeCAD scenes to Castle Game Engine": "Exportar escenas de FreeCAD a Castle Game Engine",
    "Game Engine Export": "Game Engine Export",
    "Export X3D": "Exportar X3D",
    "Select objects and export them to X3D": "Seleccionar objetos y exportarlos a X3D",
    "Quick Example": "Ejemplo rápido",
    "Generate a test house, office, photometric scene or maze.": "Generar una casa, oficina, escena fotométrica o laberinto de prueba.",
    "GameEngineExport - Quick Example": "GameEngineExport - Ejemplo rápido",
    "Type": "Tipo",
    "House": "Casa",
    "Office": "Oficina",
    "Photometric": "Fotometría",
    "Maze": "Laberinto",
    "Random": "Aleatorio",
    "Photometric creates two small rooms with calibrated luminaires and a main entrance. Maze creates a random Doom-like map and stores its geometry in JSON.": "Fotometría crea dos recintos pequeños con luminarias calibradas y acceso principal. Laberinto crea un mapa aleatorio tipo Doom y guarda su geometría en JSON.",
    "Maze: rows": "Laberinto: filas",
    "Maze: columns": "Laberinto: columnas",
    "Maze: cell width": "Laberinto: ancho celda",
    "Maze: include ceiling/roof": "Laberinto: incluir cielo/techo",
    "Creates the upper Doom-style slab above the maze. Disabled by default so the maze can be inspected from above.": "Crea la losa superior tipo Doom sobre el laberinto. Desactivado por defecto para inspeccionar el laberinto desde arriba.",
    "Seed": "Semilla",
    "Automatic": "Automática",
    "Auto": "Auto",
    "Width mm": "Ancho mm",
    "Depth mm": "Fondo mm",
    "Exterior wall mm": "Muro exterior mm",
    "Interior wall mm": "Pared interior mm",
    "Wall height mm": "Altura de muro mm",
    "Create irregular terrain and floor": "Crear terreno irregular y piso",
    "Flatten terrain under building": "Aplanar terreno bajo edificio",
    "Platform margin mm": "Margen de plataforma mm",
    "Terrain margin mm": "Margen de terreno mm",
    "Terrain relief mm": "Relieve del terreno mm",
    "Floor overhang mm": "Sobresaliente del piso mm",
    "Copy JSON context to clipboard": "Copiar contexto JSON al portapapeles",
    "Delete previous Quick Examples": "Borrar ejemplos rápidos anteriores",
    "Quick Example error": "Error de Ejemplo rápido",
    "Help": "Ayuda",
    "Open the complete Game Engine Export WB help": "Abrir la ayuda completa de Game Engine Export WB",
    "Copy": "Copiar",
    "Copy the full help text.": "Copiar todo el texto de ayuda.",
    "Reload Workbench": "Recargar Workbench",
    "Reload GameEngineExportWB code without restarting FreeCAD": "Recargar el código de GameEngineExportWB sin reiniciar FreeCAD",
}


def current_language() -> str:
    """Return a compact current language code using FreeCAD's active preference."""
    try:
        language = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General").GetString("Language", "")
    except Exception:
        language = ""
    normalized = str(language or "").strip().lower()
    if normalized.startswith("spanish") or normalized.startswith("espa") or normalized in {"es", "es_es"}:
        return "es"
    return "en"


def tr(text: str, context: str = CONTEXT) -> str:
    """Translate a visible UI string, preferring FreeCAD/Qt translation catalogs."""
    source = str(text)
    try:
        translated = FreeCAD.Qt.translate(context, source)
    except Exception:
        translated = source
    if translated != source:
        return translated
    if current_language() == "es":
        return _ES.get(source, source)
    return source



def bi(spanish: str, english: str, context: str = CONTEXT) -> str:
    """Return one visible language while still allowing native Qt catalogs to override English source text."""
    translated = tr(english, context)
    if translated != english:
        return translated
    return str(spanish) if current_language() == "es" else str(english)

def install_translation_path() -> str:
    """Register the standard Workbench translations directory in FreeCAD."""
    path = os.path.join(os.path.dirname(__file__), "translations")
    try:
        FreeCADGui.addLanguagePath(path)
        FreeCADGui.updateLocale()
        FreeCAD.Console.PrintMessage("[GAMEEXPORT] Translation path registered\n")
    except Exception as exc:
        FreeCAD.Console.PrintWarning("[GAMEEXPORT][WARN] Could not install translation path: " + str(exc) + "\n")
    return path


def QT_TRANSLATE_NOOP(context, text):
    """Marker compatible with FreeCAD translation extraction conventions."""
    del context
    return text


__all__ = [
    "CONTEXT",
    "WORKBENCH_CONTEXT",
    "QT_TRANSLATE_NOOP",
    "bi",
    "current_language",
    "install_translation_path",
    "tr",
]
