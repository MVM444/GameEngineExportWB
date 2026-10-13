"""GUI smoke for the optional Integrate with Solar command.

Run with an isolated FreeCAD 1.1 GUI profile containing DEV and Solar. The
script accepts or cancels the real modal SunPathDialog without changing its fields,
checks the resulting GEEWB preferences, writes JSON to ``GEE_SOLAR_COMMAND_RESULT``
and closes only its own temporary document and GUI process.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import traceback

import FreeCAD
import FreeCADGui

try:
    from PySide import QtCore, QtGui
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets

    for name in ("QApplication", "QDialog", "QMessageBox"):
        if not hasattr(QtGui, name) and hasattr(QtWidgets, name):
            setattr(QtGui, name, getattr(QtWidgets, name))


RESULT_PATH = Path(
    os.environ.get("GEE_SOLAR_COMMAND_RESULT", "")
    or (Path(FreeCAD.getUserAppDataDir()) / "integrate-solar-smoke.json")
)
DOCUMENT_NAME = "GEEIntegrateSolarSmoke"
EXPECT_SOLAR_AVAILABLE = os.environ.get("GEE_SOLAR_EXPECT_AVAILABLE", "1") != "0"
DIALOG_ACTION = os.environ.get("GEE_SOLAR_DIALOG_ACTION", "accept").strip().lower()


def _accept_modal_dialogs():
    app = QtGui.QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        if not isinstance(widget, QtGui.QDialog) or not widget.isVisible():
            continue
        class_name = type(widget).__name__
        if class_name == "SunPathDialog" and DIALOG_ACTION == "cancel":
            widget.reject()
        elif class_name == "SunPathDialog" or isinstance(widget, QtGui.QMessageBox):
            widget.accept()
    QtCore.QTimer.singleShot(50, _accept_modal_dialogs)


def _close_freecad():
    if FreeCAD.getDocument(DOCUMENT_NAME) is not None:
        FreeCAD.closeDocument(DOCUMENT_NAME)
    main_window = FreeCADGui.getMainWindow()
    if main_window is not None:
        main_window.close()
    app = QtGui.QApplication.instance()
    if app is not None:
        app.quit()


def _run():
    result = {
        "status": "running",
        "freecad_version": FreeCAD.Version(),
        "gui_up": bool(FreeCAD.GuiUp),
    }
    try:
        document = FreeCAD.newDocument(DOCUMENT_NAME)
        FreeCADGui.activateWorkbench("GameEngineExportWorkbench")
        # The command is exercised for real; only its final informational
        # message boxes are suppressed so the unattended smoke cannot stall.
        from freecad.GameEngineExportWB.commands import cmd_integrate_solar

        cmd_integrate_solar.QtGui.QMessageBox.information = lambda *args, **kwargs: None
        cmd_integrate_solar.QtGui.QMessageBox.warning = lambda *args, **kwargs: None
        if not EXPECT_SOLAR_AVAILABLE:
            cmd_integrate_solar.solar_adapter.solar_workbench_available = lambda: False
        parameters = FreeCAD.ParamGet("User parameter:Plugins/GameEngineExportWB")
        sentinel = {
            "gl_enabled": False,
            "gl_use_solar_workbench": False,
            "gl_interactive_solar_x3d": False,
            "gl_yaw": 123.25,
            "gl_pitch": -12.75,
        }
        if DIALOG_ACTION == "cancel":
            parameters.SetBool("gl_enabled", sentinel["gl_enabled"])
            parameters.SetBool("gl_use_solar_workbench", sentinel["gl_use_solar_workbench"])
            parameters.SetBool("gl_interactive_solar_x3d", sentinel["gl_interactive_solar_x3d"])
            parameters.SetFloat("gl_yaw", sentinel["gl_yaw"])
            parameters.SetFloat("gl_pitch", sentinel["gl_pitch"])
        QtCore.QTimer.singleShot(50, _accept_modal_dialogs)
        FreeCADGui.runCommand("GameEngineExport_IntegrateSolar")

        sun = document.getObject("SunProperties")
        active_workbench = str(FreeCADGui.activeWorkbench().name())
        if active_workbench != "GameEngineExportWorkbench":
            raise RuntimeError("GEEWB was not kept active: " + active_workbench)
        if not EXPECT_SOLAR_AVAILABLE:
            if sun is not None:
                raise RuntimeError("Unavailable Solar unexpectedly created SunProperties")
            result.update(
                {
                    "status": "passed",
                    "command": "GameEngineExport_IntegrateSolar",
                    "solar_available": False,
                    "sun_object": None,
                    "active_workbench": active_workbench,
                }
            )
            return

        if DIALOG_ACTION == "cancel":
            actual = {
                "gl_enabled": bool(parameters.GetBool("gl_enabled", True)),
                "gl_use_solar_workbench": bool(parameters.GetBool("gl_use_solar_workbench", True)),
                "gl_interactive_solar_x3d": bool(parameters.GetBool("gl_interactive_solar_x3d", True)),
                "gl_yaw": float(parameters.GetFloat("gl_yaw", 0.0)),
                "gl_pitch": float(parameters.GetFloat("gl_pitch", 0.0)),
            }
            if actual != sentinel:
                raise RuntimeError("Cancel changed GEEWB preferences: " + repr(actual))
            result.update(
                {
                    "status": "passed",
                    "command": "GameEngineExport_IntegrateSolar",
                    "solar_available": True,
                    "dialog_action": "cancel",
                    "sun_object": str(sun.Name) if sun is not None else None,
                    "preferences_unchanged": True,
                    "active_workbench": active_workbench,
                }
            )
            return

        if sun is None:
            raise RuntimeError("Solar did not create or reuse SunProperties")
        yaw = float(parameters.GetFloat("gl_yaw", float("nan")))
        pitch = float(parameters.GetFloat("gl_pitch", float("nan")))
        if not parameters.GetBool("gl_enabled", False):
            raise RuntimeError("GEEWB global light was not enabled")
        if not parameters.GetBool("gl_use_solar_workbench", False):
            raise RuntimeError("GEEWB Solar preference was not enabled")
        if not parameters.GetBool("gl_interactive_solar_x3d", False):
            raise RuntimeError("GEEWB interactive Solar preference was not enabled")
        if not (math.isfinite(yaw) and math.isfinite(pitch)):
            raise RuntimeError("GEEWB Solar angles were not persisted")
        result.update(
            {
                "status": "passed",
                "command": "GameEngineExport_IntegrateSolar",
                "solar_available": True,
                "dialog_action": "accept",
                "sun_object": str(sun.Name),
                "yaw_deg": yaw,
                "pitch_deg": pitch,
                "active_workbench": active_workbench,
            }
        )
    except Exception as exc:
        result.update(
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True),
            encoding="utf-8",
        )
        FreeCAD.Console.PrintMessage(
            "[GAMEEXPORT][SOLAR-COMMAND-SMOKE] "
            + result["status"]
            + ": "
            + RESULT_PATH.name
            + "\n"
        )
        QtCore.QTimer.singleShot(100, _close_freecad)


QtCore.QTimer.singleShot(0, _run)
