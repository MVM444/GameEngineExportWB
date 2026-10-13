"""Open Solar's existing SunPathDialog and synchronize GEEWB afterwards."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Optional

import FreeCAD
import FreeCADGui

from .. import i18n
from ..adapters import solar_adapter

try:
    from PySide import QtGui
except ImportError:  # pragma: no cover - FreeCAD 1.1 currently supplies PySide
    from PySide6 import QtGui, QtWidgets

    QtGui.QMessageBox = QtWidgets.QMessageBox


LOG_PREFIX = "[GAMEEXPORT] "
PARAM_GROUP = "User parameter:Plugins/GameEngineExportWB"
WORKBENCH_ID = "GameEngineExportWorkbench"
SOLAR_DIALOG_MODULE = "freecad.Solar.SunDialog"
SOLAR_COMMAND_ID = "SunPathDialog"
ICON_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "resources",
        "icons",
        "integrate_solar.svg",
    )
).replace(os.sep, "/")


def _warning(message_es: str, message_en: str) -> None:
    message = i18n.bi(message_es, message_en)
    FreeCAD.Console.PrintWarning(LOG_PREFIX + "[WARN] " + message + "\n")
    QtGui.QMessageBox.warning(
        None,
        i18n.bi("Integrar con Solar", "Integrate with Solar"),
        message,
    )


def _reactivate_gameengine_workbench() -> None:
    """Keep the originating Workbench active after Solar's modal tool closes."""
    try:
        FreeCADGui.activateWorkbench(WORKBENCH_ID)
    except Exception as exc:  # pragma: no cover - defensive FreeCAD GUI boundary
        FreeCAD.Console.PrintWarning(
            LOG_PREFIX
            + "[WARN] Could not reactivate GameEngineExportWB: "
            + str(exc)
            + "\n"
        )


@dataclass(frozen=True)
class SolarIntegrationResult:
    """Outcome of one Solar dialog invocation without duplicating Solar logic."""

    status: str
    sync: Optional[solar_adapter.SolarPreferenceSyncResult] = None
    reason: str = ""

    @property
    def synchronized(self) -> bool:
        return self.status == "synchronized" and self.sync is not None


def _registered_solar_command_available() -> bool:
    """Import Solar's registration module and verify the real GUI command."""
    importlib.import_module(SOLAR_DIALOG_MODULE)
    return SOLAR_COMMAND_ID in tuple(FreeCADGui.listCommands())


def run_solar_integration(parent=None) -> SolarIntegrationResult:
    """Run Solar's registered dialog and synchronize only saved changes.

    Solar's command creates its own ``SunPathDialog``. Temporary wrappers only
    observe whether Solar called its existing save method (Apply or OK); the
    original dialog, calculations and SunProperties persistence remain owned by
    Solar.  A plain Cancel therefore cannot overwrite GEEWB preferences.
    """
    document = FreeCAD.ActiveDocument
    if document is None:
        return SolarIntegrationResult(
            "unavailable",
            reason=i18n.bi(
                "Abra o cree un documento antes de integrar Solar.",
                "Open or create a document before integrating Solar.",
            ),
        )
    if not solar_adapter.solar_workbench_available():
        return SolarIntegrationResult(
            "unavailable",
            reason=i18n.bi(
                "Solar Workbench no esta instalado. Las funciones actuales de GEEWB siguen disponibles.",
                "Solar Workbench is not installed. Existing GEEWB features remain available.",
            ),
        )

    solar_dialog = importlib.import_module(SOLAR_DIALOG_MODULE)
    if not _registered_solar_command_available():
        return SolarIntegrationResult(
            "unavailable",
            reason=i18n.bi(
                "Solar esta instalado, pero su comando SunPathDialog no esta registrado.",
                "Solar is installed, but its SunPathDialog command is not registered.",
            ),
        )

    dialog_class = solar_dialog.SunPathDialog
    original_show = dialog_class.show_dialog
    original_save = dialog_class.save_to_propeties
    observed = {"accepted": False, "applied": False}

    def observed_show(dialog_self, *args, **kwargs):
        accepted = bool(original_show(dialog_self, *args, **kwargs))
        observed["accepted"] = accepted
        return accepted

    def observed_save(dialog_self, *args, **kwargs):
        result = original_save(dialog_self, *args, **kwargs)
        observed["applied"] = True
        return result

    dialog_class.show_dialog = observed_show
    dialog_class.save_to_propeties = observed_save
    try:
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX + "Opening registered Solar SunPathDialog without changing Workbench\n"
        )
        FreeCADGui.runCommand(SOLAR_COMMAND_ID)
    finally:
        dialog_class.show_dialog = original_show
        dialog_class.save_to_propeties = original_save
        _reactivate_gameengine_workbench()

    if not observed["applied"]:
        return SolarIntegrationResult(
            "cancelled",
            reason=i18n.bi(
                "Integracion cancelada; GEEWB no fue modificado.",
                "Integration cancelled; GEEWB was not changed.",
            ),
        )

    sync = solar_adapter.sync_gameengine_preferences(
        document,
        FreeCAD.ParamGet(PARAM_GROUP),
        allow_below_horizon=True,
    )
    if not sync.updated:
        return SolarIntegrationResult(
            "invalid",
            sync=sync,
            reason=i18n.bi(
                "Solar termino, pero no dejo datos solares validos: ",
                "Solar finished, but it did not leave valid solar data: ",
            )
            + sync.discovery.reason,
        )
    return SolarIntegrationResult("synchronized", sync=sync)


class CommandClass:
    """FreeCAD command wrapper for the optional Solar integration."""

    CommandName = "GameEngineExport_IntegrateSolar"

    def GetResources(self):  # noqa: N802
        return {
            "MenuText": i18n.bi("Integrar con Solar", "Integrate with Solar"),
            "ToolTip": i18n.bi(
                "Abrir la herramienta solar existente y sincronizar sus datos con GameEngineExportWB.",
                "Open the existing Solar tool and synchronize its data with GameEngineExportWB.",
            ),
            "Pixmap": ICON_PATH,
        }

    def Activated(self):  # noqa: N802
        try:
            result = run_solar_integration()
            if result.status in {"unavailable", "invalid"}:
                _warning(result.reason, result.reason)
                return
            if result.status == "cancelled":
                FreeCAD.Console.PrintMessage(LOG_PREFIX + result.reason + "\n")
                return

            sync = result.sync
            environment = sync.discovery.environment
            source_name = str(getattr(environment, "source_object_name", "") or "SunProperties")
            FreeCAD.Console.PrintMessage(
                LOG_PREFIX
                + "Solar synchronized through solar_adapter from "
                + source_name
                + ": yaw {:.1f} deg, pitch {:.1f} deg\n".format(
                    sync.yaw_deg,
                    sync.pitch_deg,
                )
            )
            QtGui.QMessageBox.information(
                None,
                i18n.bi("Integrar con Solar", "Integrate with Solar"),
                i18n.bi(
                    "Datos solares actualizados en GameEngineExportWB.",
                    "Solar data updated in GameEngineExportWB.",
                ),
            )
        except Exception as exc:
            _warning(
                "No se pudo abrir o sincronizar SunPathDialog: " + str(exc),
                "Could not open or synchronize SunPathDialog: " + str(exc),
            )
            _reactivate_gameengine_workbench()

    def IsActive(self):  # noqa: N802
        return FreeCAD.ActiveDocument is not None


__all__ = ["CommandClass", "SolarIntegrationResult", "run_solar_integration"]
