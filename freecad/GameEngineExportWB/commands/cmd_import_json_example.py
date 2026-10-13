"""Import JSON / AI command for GameEngineExportWB.








Name: commands/cmd_import_json_example.py
Purpose: use copy/paste JSON as a manual bridge between FreeCAD and an external AI assistant.
Main behavior: copies an AI-ready prompt + current JSON, accepts returned JSON, validates it and rebuilds a Quick Example.
Modification notes: keep the workflow local, without external APIs, and delegate JSON validation/generation to core.json_importer.
Version: 2026-10-12-json-hot-reload-safe-v2
Date and time: 2026-08-21 07:49 -06:00
"""








from __future__ import annotations








import importlib
import os
import time








import FreeCAD
import FreeCADGui








from .. import i18n








from ..core import json_ai, json_importer
from . import cmd_bim_doors_windows, cmd_roof_quick_example
from ..ui.panel_export import _ensure_qt_compat
















_ensure_qt_compat()








from PySide import QtGui  # noqa: E402
















LOG_PREFIX = "[GAMEEXPORT] "
COMMAND_VERSION = str(time.time_ns())
ICON_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "resources", "icons", "import_json_example.svg")
).replace(os.sep, "/")
















class CommandClass:
    """FreeCAD command wrapper for importing quick example JSON."""








    # Unique on each hot reload: FreeCAD 1.1.4 lacks removeCommand.
    # This prevents a stale command instance from surviving module purges.
    CommandName = "GameEngineExport_ImportJSONExample_" + COMMAND_VERSION








    def GetResources(self):  # noqa: N802
        return {
            "MenuText": i18n.bi("IA / JSON: copiar y pegar", "AI / JSON: copy and paste"),
            "ToolTip": i18n.bi("Copiar prompt/contexto para una IA o pegar JSON devuelto y reconstruir el ejemplo", "Copy an AI prompt/context or paste returned JSON and rebuild the example"),
            "Pixmap": ICON_PATH,
        }








    def Activated(self):  # noqa: N802
        global json_importer
        importlib.invalidate_caches()
        # The loader purges package modules, but Qt can retain older command
        # instances. A stale module object cannot be passed to reload().
        # Resolve the current module from sys.modules/import machinery instead.
        json_importer = importlib.import_module(
            "freecad.GameEngineExportWB.core.json_importer"
        )
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "Opening JSON import dialog\n")
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX + "JSON import command: " + self.CommandName + "\n"
        )
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX + "JSON import UI build: json-hot-reload-safe-v2\n"
        )
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX + "JSON importer source: "
            + str(getattr(json_importer, "__file__", "unknown")) + "\n"
        )
        dialog = ImportJSONDialog()
        dialog.exec_()








    def IsActive(self):  # noqa: N802
        return True
















class ImportJSONDialog(QtGui.QDialog):
    """Dialog for paste/load JSON and generating the model."""








    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.bi("GameEngineExport - Importar JSON", "GameEngineExport - Import JSON"))
        self.resize(760, 560)
        self._build_ui()








    def _build_ui(self):
        layout = QtGui.QVBoxLayout(self)








        intro = QtGui.QLabel(i18n.bi(
            "1. Presione Copiar contexto para IA. 2. Abra ChatGPT, Codex u otro chat de IA y pegue con Ctrl+V. 3. Solicite un analisis o cambios. Si la IA devuelve un JSON modificado, peguelo abajo y pulse Generar.",
            "1. Click Copy context for AI. 2. Open ChatGPT, Codex or another AI chat and paste with Ctrl+V. 3. Request analysis or edits. If the AI returns modified JSON, paste it below and click Generate.",
        ))
        intro.setWordWrap(True)
        layout.addWidget(intro)








        ai_buttons = QtGui.QHBoxLayout()
        self.btn_ai_prompt = QtGui.QPushButton(i18n.bi("Solo instrucciones", "Instructions only"))
        self.btn_ai_package = QtGui.QPushButton(i18n.bi("Copiar contexto para IA", "Copy context for AI"))
        self.btn_ai_prompt.clicked.connect(self._copy_ai_prompt)
        self.btn_ai_package.clicked.connect(self._copy_ai_package)
        ai_buttons.addWidget(self.btn_ai_package)
        ai_buttons.addWidget(self.btn_ai_prompt)
        ai_buttons.addStretch(1)
        layout.addLayout(ai_buttons)








        self.text = QtGui.QPlainTextEdit()
        self.text.setPlaceholderText(i18n.bi("Pegue aqui JSON puro o texto con un bloque JSON.", "Paste plain JSON or text containing a JSON block here."))
        layout.addWidget(self.text, 1)








        top_buttons = QtGui.QHBoxLayout()
        self.btn_paste = QtGui.QPushButton(i18n.bi("Pegar portapapeles", "Paste clipboard"))
        self.btn_file = QtGui.QPushButton(i18n.bi("Cargar archivo JSON", "Load JSON file"))
        self.btn_paste.clicked.connect(self._paste_clipboard)
        self.btn_file.clicked.connect(self._load_file)
        top_buttons.addWidget(self.btn_paste)
        top_buttons.addWidget(self.btn_file)
        top_buttons.addStretch(1)
        layout.addLayout(top_buttons)








        self.add_bim_doors_windows = QtGui.QCheckBox(
            i18n.bi("Agregar puertas y ventanas BIM", "Add BIM doors and windows")
        )
        self.add_bim_doors_windows.setToolTip(i18n.bi(
            "Genera puertas y ventanas a partir de las aberturas del JSON, como en Ejemplo rapido.",
            "Generate BIM doors and windows from JSON openings, as in Quick Example."
        ))
        self.add_bim_doors_windows.setChecked(True)
        self.add_roof = QtGui.QCheckBox(i18n.bi("Agregar techo", "Add roof"))
        self.add_roof.setToolTip(i18n.bi(
            "Genera el techo con la herramienta existente de Ejemplo rapido.",
            "Generate a roof with the existing Quick Example tool."
        ))
        self.add_roof.setChecked(True)
        self.clear_previous = QtGui.QCheckBox(i18n.bi("Borrar ejemplos rapidos anteriores", "Delete previous Quick Examples"))
        self.clear_previous.setChecked(True)
        self.copy_context = QtGui.QCheckBox(i18n.bi("Copiar contexto actualizado para IA (prompt + JSON)", "Copy updated AI context (prompt + JSON)"))
        self.copy_context.setChecked(False)
        layout.addWidget(self.add_bim_doors_windows)
        layout.addWidget(self.add_roof)
        layout.addWidget(self.clear_previous)
        layout.addWidget(self.copy_context)








        bottom = QtGui.QHBoxLayout()
        bottom.addStretch(1)
        self.btn_generate = QtGui.QPushButton(i18n.bi("Generar", "Generate"))
        self.btn_cancel = QtGui.QPushButton(i18n.bi("Cancelar", "Cancel"))
        self.btn_generate.clicked.connect(self._generate)
        self.btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self.btn_generate)
        bottom.addWidget(self.btn_cancel)
        layout.addLayout(bottom)








    def _clipboard(self):
        app = QtGui.QApplication.instance()
        return app.clipboard() if app is not None else None








    def _current_document_context(self):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return ""
        for obj in reversed(list(getattr(doc, "Objects", []) or [])):
            props = list(getattr(obj, "PropertiesList", []) or [])
            if "GEE_ContextJSON" in props:
                value = str(getattr(obj, "GEE_ContextJSON", "") or "").strip()
                if value:
                    return value
        return ""








    def _editor_context(self):
        raw = self.text.toPlainText().strip()
        if not raw:
            return ""
        try:
            return json_importer.extract_json_text(raw)
        except Exception:
            return ""








    def _copy_ai_prompt(self):
        clipboard = self._clipboard()
        if clipboard is None:
            return
        clipboard.setText(json_ai.get_prompt_template(i18n.current_language()))
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "AI JSON prompt copied to clipboard\n")








    def _copy_ai_package(self):
        clipboard = self._clipboard()
        if clipboard is None:
            return
        context = self._editor_context() or self._current_document_context()
        clipboard.setText(json_ai.build_ai_prompt(context, i18n.current_language()))
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "AI prompt + JSON context copied to clipboard\n")
        if context:
            QtGui.QMessageBox.information(
                self,
                i18n.bi("Contexto copiado", "Context copied"),
                i18n.bi(
                    "Contexto copiado. Abra un chat de IA y peguelo con Ctrl+V. Si solicita modificaciones, pegue aqui el JSON de respuesta.",
                    "Context copied. Open an AI chat and paste with Ctrl+V. If you request changes, paste the returned JSON here.",
                ),
            )
        else:
            QtGui.QMessageBox.information(
                self,
                i18n.bi("IA / JSON", "AI / JSON"),
                i18n.bi("No se encontro JSON actual; se copio solamente el prompt.", "No current JSON was found; only the prompt was copied."),
            )








    def _paste_clipboard(self):
        app = QtGui.QApplication.instance()
        if app is None:
            return
        self.text.setPlainText(app.clipboard().text())








    def _load_file(self):
        path, _selected = QtGui.QFileDialog.getOpenFileName(
            self,
            i18n.bi("Cargar archivo JSON", "Load JSON file"),
            "",
            i18n.bi("JSON (*.json);;Texto (*.txt);;Todos (*.*)", "JSON (*.json);;Text (*.txt);;All files (*.*)"),
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig") as handle:
                self.text.setPlainText(handle.read())
        except Exception as exc:
            QtGui.QMessageBox.critical(self, "GameEngineExport - Import JSON", str(exc))








    def _generate(self):
        raw = self.text.toPlainText()
        try:
            payload = json_importer.load_payload_from_text(raw)
            root, _payload, context_text = json_importer.generate_quick_example_from_payload(
                payload,
                {
                    "clear_previous": bool(self.clear_previous.isChecked()),
                    "copy_context": bool(self.copy_context.isChecked()),
                },
            )
            try:
                FreeCADGui.Selection.clearSelection()
                FreeCADGui.Selection.addSelection(root)
                FreeCADGui.SendMsgToActiveView("ViewFit")
            except Exception:
                pass
            # The JSON contains openings/sketches, not the BIM door/window/roof
            # objects from the old FreeCAD document. Recreate them after
            # selecting the newly imported root, exactly like Quick Example.
            if str(payload.get("building_type", "Casa") or "Casa") != "Laberinto":
                if self.add_bim_doors_windows.isChecked():
                    cmd_bim_doors_windows.CommandClass().Activated()
                if self.add_roof.isChecked():
                    cmd_roof_quick_example.CommandClass().Activated()
            if self.copy_context.isChecked():
                app = QtGui.QApplication.instance()
                if app is not None:
                    app.clipboard().setText(json_ai.build_ai_prompt(context_text, i18n.current_language()))
            FreeCAD.Console.PrintMessage(LOG_PREFIX + "JSON example imported: " + str(root.Label) + "\n")
            self.accept()
        except Exception as exc:
            FreeCAD.Console.PrintError(LOG_PREFIX + "JSON import error: " + str(exc) + "\n")
            QtGui.QMessageBox.critical(self, "GameEngineExport - Import JSON", str(exc))