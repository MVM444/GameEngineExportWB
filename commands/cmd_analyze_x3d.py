"""FreeCAD command to analyze an existing X3D without modifying it.

Descripcion: localiza el X3D del documento activo, permite escoger otro y
genera reportes pequenos JSON/Markdown junto al archivo analizado.
Fecha y hora: 2026-08-13 17:35 America/Costa_Rica.
Instrucciones clave:
- Mantener codigo y mensajes en ASCII.
- No modificar ni copiar el X3D.
- Mostrar progreso y permitir cancelar.
- Registrar mensajes con prefijo [GAMEEXPORT].
"""

import importlib
import os
import sys
from pathlib import Path

import FreeCAD
import FreeCADGui

from .. import i18n

try:
    from PySide import QtCore, QtGui
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets

    for name in (
        "QApplication",
        "QFileDialog",
        "QMessageBox",
        "QProgressDialog",
    ):
        if not hasattr(QtGui, name) and hasattr(QtWidgets, name):
            setattr(QtGui, name, getattr(QtWidgets, name))

from ..ui.output_defaults import compute_output_defaults, normalize_base_name


LOG_PREFIX = "[GAMEEXPORT] "
PARAM_GROUP = "User parameter:Plugins/GameEngineExportWB"
ICON_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "resources",
        "icons",
        "analyze_x3d.svg",
    )
).replace(os.sep, "/")
ANALYZER_MODULE_NAME = "GameEngineExportWB.core.x3d_analyzer"


def _load_analyzer_module():
    """Load or reload the analyzer without using a stale package reference."""
    module = sys.modules.get(ANALYZER_MODULE_NAME)
    if module is not None:
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX + "Reloading X3D analyzer module\n"
        )
        return importlib.reload(module)

    core_package = importlib.import_module("GameEngineExportWB.core")
    stale_module = getattr(core_package, "x3d_analyzer", None)
    if stale_module is not None:
        try:
            delattr(core_package, "x3d_analyzer")
        except Exception:
            pass
        FreeCAD.Console.PrintWarning(
            LOG_PREFIX + "Removed stale X3D analyzer package reference\n"
        )

    FreeCAD.Console.PrintMessage(
        LOG_PREFIX + "Importing X3D analyzer module\n"
    )
    return importlib.import_module(ANALYZER_MODULE_NAME)


def _candidate_paths():
    params = FreeCAD.ParamGet(PARAM_GROUP)
    doc = FreeCAD.ActiveDocument
    doc_path = None
    if doc is not None and getattr(doc, "FileName", ""):
        doc_path = Path(doc.FileName)
    output_dir, base_name, _ = compute_output_defaults(params, doc_path)

    candidates = []
    if output_dir and base_name:
        safe_name = normalize_base_name(base_name)
        candidates.extend(
            [
                Path(output_dir) / (safe_name + ".x3d"),
                Path(output_dir) / (safe_name + ".x3dz"),
            ]
        )
    if doc_path is not None:
        safe_stem = normalize_base_name(doc_path.stem)
        candidates.extend(
            [
                doc_path.parent / (safe_stem + ".x3d"),
                doc_path.parent / (safe_stem + ".x3dz"),
            ]
        )

    result = []
    seen = set()
    for path in candidates:
        key = os.path.normcase(os.path.abspath(str(path)))
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _choose_x3d_path():
    existing = [path for path in _candidate_paths() if path.is_file()]
    if existing:
        return max(existing, key=lambda path: path.stat().st_mtime)

    start_dir = ""
    doc = FreeCAD.ActiveDocument
    if doc is not None and getattr(doc, "FileName", ""):
        start_dir = str(Path(doc.FileName).parent)
    selected, _ = QtGui.QFileDialog.getOpenFileName(
        FreeCADGui.getMainWindow(),
        "Seleccionar X3D para analizar",
        start_dir,
        "X3D (*.x3d *.x3dz);;Todos los archivos (*)",
    )
    return Path(selected) if selected else None


def _open_report(path):
    try:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))
    except Exception as exc:
        FreeCAD.Console.PrintWarning(
            LOG_PREFIX + "Could not open analysis report: " + str(exc) + "\n"
        )


class CommandClass:
    """Analyze the current X3D and create small diagnostic reports."""

    CommandName = "GameEngineExport_AnalyzeX3D"

    def GetResources(self):  # noqa: N802
        return {
            "MenuText": i18n.bi("Analizar X3D", "Analyze X3D"),
            "ToolTip": i18n.bi(
                "Analiza tamano, vertices, triangulos, luces y geometria repetida sin modificar el X3D",
                "Analyze size, vertices, triangles, lights and repeated geometry without modifying the X3D",
            ),
            "Pixmap": ICON_PATH,
        }

    def Activated(self):  # noqa: N802
        path = _choose_x3d_path()
        if path is None:
            FreeCAD.Console.PrintMessage(LOG_PREFIX + "X3D analysis cancelled: no file selected\n")
            return

        FreeCAD.Console.PrintMessage(LOG_PREFIX + "Analyzing X3D: " + path.name + "\n")
        progress = QtGui.QProgressDialog(
            "Analizando X3D sin modificarlo...",
            "Cancelar",
            0,
            100,
            FreeCADGui.getMainWindow(),
        )
        progress.setWindowTitle(i18n.bi("Game Engine Export - Analisis X3D", "Game Engine Export - X3D Analysis"))
        progress.setMinimumDuration(0)
        progress.setValue(0)

        def update_progress(bytes_read, total_hint):
            if total_hint > 0:
                value = min(99, int(100.0 * float(bytes_read) / float(total_hint)))
                progress.setValue(value)
                progress.setLabelText(
                    "Analizando X3D: "
                    + f"{bytes_read / (1024.0 * 1024.0):.1f} / "
                    + f"{total_hint / (1024.0 * 1024.0):.1f} MB"
                )
            else:
                progress.setRange(0, 0)
                progress.setLabelText(
                    "Analizando X3DZ: "
                    + f"{bytes_read / (1024.0 * 1024.0):.1f} MB sin comprimir"
                )
            QtGui.QApplication.processEvents()
            return not progress.wasCanceled()

        try:
            analyzer = _load_analyzer_module()
            report = analyzer.analyze_x3d(
                path,
                top_n=20,
                progress_callback=update_progress,
            )
            json_path, markdown_path = analyzer.write_reports(report, path)
        except Exception as exc:
            if (
                exc.__class__.__name__ == "AnalysisCancelled"
                and exc.__class__.__module__ == ANALYZER_MODULE_NAME
            ):
                FreeCAD.Console.PrintWarning(
                    LOG_PREFIX + "X3D analysis cancelled by user\n"
                )
                return
            FreeCAD.Console.PrintError(
                LOG_PREFIX + "X3D analysis failed: " + type(exc).__name__ + "\n"
            )
            QtGui.QMessageBox.critical(
                FreeCADGui.getMainWindow(),
                "Analisis X3D",
                "No se pudo analizar el archivo:\n" + str(exc),
            )
            return
        finally:
            progress.close()

        summary = report.get("summary", {})
        file_size = report.get("file", {}).get("size_bytes", 0)
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "X3D analysis complete: size="
            + f"{float(file_size) / (1024.0 * 1024.0):.2f} MB"
            + ", shapes="
            + str(summary.get("shapes", 0))
            + ", vertices="
            + str(summary.get("vertices", 0))
            + ", triangles="
            + str(summary.get("triangles_approx", 0))
            + ", duplicate_geometry_groups="
            + str(summary.get("duplicate_geometry_groups", 0))
            + "\n"
        )
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "Markdown report: " + Path(markdown_path).name + "\n")
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "JSON report: " + Path(json_path).name + "\n")
        QtGui.QMessageBox.information(
            FreeCADGui.getMainWindow(),
            "Analisis X3D completado",
            "Archivo analizado sin modificaciones.\n\n"
            + "Tamano: "
            + f"{float(file_size) / (1024.0 * 1024.0):.2f} MB\n"
            + "Shapes: "
            + str(summary.get("shapes", 0))
            + "\nVertices: "
            + str(summary.get("vertices", 0))
            + "\nTriangulos aproximados: "
            + str(summary.get("triangles_approx", 0))
            + "\nGeometrias repetidas: "
            + str(summary.get("duplicate_geometry_groups", 0))
            + "\n\nSe abrira el reporte Markdown.",
        )
        _open_report(markdown_path)

    def IsActive(self):  # noqa: N802
        return True


__all__ = ["CommandClass"]
