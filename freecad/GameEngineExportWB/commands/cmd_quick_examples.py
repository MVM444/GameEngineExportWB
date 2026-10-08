"""Quick Example command for GameEngineExportWB.

Name: commands/cmd_quick_examples.py
Purpose: generate small test scenes and optionally copy an AI-ready prompt + JSON context.
Main behavior: keeps stable Quick Example generation while exposing the manual JSON/AI bridge.
Modification notes: preserve saved option keys and canonical internal building type values.
Version: 2026-08-21-ai-context-v1
Date and time: 2026-08-21 07:49 -06:00
"""

from __future__ import annotations

import importlib
import os
import time

import FreeCAD
import FreeCADGui

from .. import i18n

from ..core import quick_examples
from ..ui.panel_export import _ensure_qt_compat


_ensure_qt_compat()

from PySide import QtGui  # noqa: E402


LOG_PREFIX = "[GAMEEXPORT] "
PARAM_GROUP = "User parameter:Plugins/GameEngineExportWB/QuickExamples"
ICON_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "resources", "icons", "quick_example.svg")
).replace(os.sep, "/")
COMMAND_VERSION = str(int(time.time()))


class CommandClass:
    """FreeCAD command wrapper for quick example generation."""

    CommandName = "GameEngineExport_QuickExample_" + COMMAND_VERSION

    def GetResources(self):  # noqa: N802
        return {
            "MenuText": i18n.tr("Quick Example"),
            "ToolTip": i18n.tr("Generate a test house, office, photometric scene or maze."),
            "Pixmap": ICON_PATH,
        }

    def Activated(self):  # noqa: N802
        global quick_examples
        importlib.invalidate_caches()
        quick_examples = importlib.reload(quick_examples)
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "Opening quick example dialog\n")
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX + "Quick example module: " + str(getattr(quick_examples, "__file__", "unknown")) + "\n"
        )
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "Quick example command: " + self.CommandName + "\n")
        dialog = QuickExampleDialog()
        dialog.exec_()

    def IsActive(self):  # noqa: N802
        return True


class QuickExampleDialog(QtGui.QDialog):
    """Small dialog for quick sample scene generation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.params = FreeCAD.ParamGet(PARAM_GROUP)
        self.setWindowTitle(i18n.tr("GameEngineExport - Quick Example"))
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QtGui.QVBoxLayout(self)
        form = QtGui.QFormLayout()

        self.building_type = QtGui.QComboBox()
        for visible, key in [
            (i18n.tr("House"), "Casa"),
            (i18n.tr("Office"), "Oficina"),
            (i18n.tr("Photometric"), "Fotometria"),
            (i18n.tr("Maze"), "Laberinto"),
            (i18n.tr("Random"), "Aleatorio"),
        ]:
            self.building_type.addItem(visible, key)
        self.building_type.setToolTip(
            i18n.bi(
                "Fotometria crea dos recintos pequenos con luminarias calibradas y acceso principal. Laberinto crea un mapa aleatorio tipo Doom y guarda su geometria en JSON.",
                "Photometric creates two small rooms with calibrated luminaires and a main entrance. Maze creates a random Doom-like map and stores its geometry in JSON.",
            )
        )
        form.addRow(i18n.tr("Type"), self.building_type)

        self.maze_rows = QtGui.QSpinBox()
        self.maze_rows.setRange(2, 30)
        self.maze_rows.setValue(7)
        form.addRow(i18n.tr("Maze: rows"), self.maze_rows)

        self.maze_cols = QtGui.QSpinBox()
        self.maze_cols.setRange(2, 30)
        self.maze_cols.setValue(10)
        form.addRow(i18n.tr("Maze: columns"), self.maze_cols)

        self.maze_cell_mm = QtGui.QSpinBox()
        self.maze_cell_mm.setRange(800, 5000)
        self.maze_cell_mm.setSingleStep(100)
        self.maze_cell_mm.setValue(2000)
        self.maze_cell_mm.setSuffix(" mm")
        form.addRow(i18n.tr("Maze: cell width"), self.maze_cell_mm)

        self.maze_include_ceiling = QtGui.QCheckBox(i18n.tr("Maze: include ceiling/roof"))
        self.maze_include_ceiling.setToolTip(
            i18n.tr("Creates the upper Doom-style slab above the maze. Disabled by default so the maze can be inspected from above.")
        )
        form.addRow("", self.maze_include_ceiling)

        self.seed = QtGui.QSpinBox()
        self.seed.setRange(0, 2147483647)
        self.seed.setSpecialValueText(i18n.tr("Automatic"))
        form.addRow(i18n.tr("Seed"), self.seed)

        self.width_mm = QtGui.QDoubleSpinBox()
        self.width_mm.setRange(0, 100000)
        self.width_mm.setDecimals(0)
        self.width_mm.setSingleStep(500)
        self.width_mm.setSpecialValueText("Auto")
        form.addRow(i18n.tr("Width mm"), self.width_mm)

        self.depth_mm = QtGui.QDoubleSpinBox()
        self.depth_mm.setRange(0, 100000)
        self.depth_mm.setDecimals(0)
        self.depth_mm.setSingleStep(500)
        self.depth_mm.setSpecialValueText("Auto")
        form.addRow(i18n.tr("Depth mm"), self.depth_mm)

        self.ext_wall_mm = QtGui.QSpinBox()
        self.ext_wall_mm.setRange(100, 500)
        form.addRow(i18n.tr("Exterior wall mm"), self.ext_wall_mm)

        self.int_wall_mm = QtGui.QSpinBox()
        self.int_wall_mm.setRange(50, 300)
        form.addRow(i18n.tr("Interior wall mm"), self.int_wall_mm)

        self.wall_height_mm = QtGui.QSpinBox()
        self.wall_height_mm.setRange(1000, 8000)
        self.wall_height_mm.setSingleStep(100)
        form.addRow(i18n.tr("Wall height mm"), self.wall_height_mm)

        self.create_terrain = QtGui.QCheckBox(i18n.tr("Create irregular terrain and floor"))
        form.addRow("", self.create_terrain)

        self.flatten_pad = QtGui.QCheckBox(i18n.tr("Flatten terrain under building"))
        form.addRow("", self.flatten_pad)

        self.pad_margin_mm = QtGui.QSpinBox()
        self.pad_margin_mm.setRange(0, 8000)
        self.pad_margin_mm.setSingleStep(250)
        form.addRow(i18n.tr("Platform margin mm"), self.pad_margin_mm)

        self.terrain_margin_mm = QtGui.QSpinBox()
        self.terrain_margin_mm.setRange(2000, 30000)
        self.terrain_margin_mm.setSingleStep(500)
        form.addRow(i18n.tr("Terrain margin mm"), self.terrain_margin_mm)

        self.terrain_variation_mm = QtGui.QSpinBox()
        self.terrain_variation_mm.setRange(0, 3000)
        self.terrain_variation_mm.setSingleStep(100)
        form.addRow(i18n.tr("Terrain relief mm"), self.terrain_variation_mm)

        self.floor_overhang_mm = QtGui.QSpinBox()
        self.floor_overhang_mm.setRange(0, 2000)
        self.floor_overhang_mm.setSingleStep(50)
        form.addRow(i18n.tr("Floor overhang mm"), self.floor_overhang_mm)

        self.copy_context = QtGui.QCheckBox(i18n.bi("Copiar contexto para IA (prompt + JSON)", "Copy AI context (prompt + JSON)"))
        self.copy_context.setToolTip(i18n.bi("Copia instrucciones para la IA seguidas del JSON actual, listas para pegar en un chat.", "Copies AI instructions followed by the current JSON, ready to paste into a chat."))
        form.addRow("", self.copy_context)

        self.clear_previous = QtGui.QCheckBox(i18n.tr("Delete previous Quick Examples"))
        form.addRow("", self.clear_previous)

        layout.addLayout(form)

        buttons = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.building_type.currentIndexChanged.connect(self._update_type_controls)

    def _load(self):
        saved_type = self.params.GetString("building_type", "Casa")
        saved_index = self.building_type.findData(saved_type)
        self.building_type.setCurrentIndex(saved_index if saved_index >= 0 else 0)
        self.seed.setValue(self.params.GetInt("seed", 0))
        self.width_mm.setValue(self.params.GetFloat("width_mm", 0.0))
        self.depth_mm.setValue(self.params.GetFloat("depth_mm", 0.0))
        self.ext_wall_mm.setValue(self.params.GetInt("ext_wall_mm", int(quick_examples.DEFAULT_EXT_WALL_MM)))
        self.int_wall_mm.setValue(self.params.GetInt("int_wall_mm", int(quick_examples.DEFAULT_INT_WALL_MM)))
        self.wall_height_mm.setValue(self.params.GetInt("wall_height_mm", int(quick_examples.DEFAULT_WALL_HEIGHT_MM)))
        self.create_terrain.setChecked(self.params.GetBool("create_terrain", True))
        self.flatten_pad.setChecked(self.params.GetBool("flatten_pad", quick_examples.DEFAULT_FLATTEN_PAD))
        self.pad_margin_mm.setValue(self.params.GetInt("pad_margin_mm", int(quick_examples.DEFAULT_PAD_MARGIN_MM)))
        self.terrain_margin_mm.setValue(self.params.GetInt("terrain_margin_mm", int(quick_examples.DEFAULT_TERRAIN_MARGIN_MM)))
        self.terrain_variation_mm.setValue(
            self.params.GetInt("terrain_variation_mm", int(quick_examples.DEFAULT_TERRAIN_VARIATION_MM))
        )
        self.floor_overhang_mm.setValue(
            self.params.GetInt("floor_overhang_mm", int(quick_examples.DEFAULT_FLOOR_OVERHANG_MM))
        )
        self.copy_context.setChecked(self.params.GetBool("copy_context", False))
        self.clear_previous.setChecked(self.params.GetBool("clear_previous", True))
        self.maze_rows.setValue(self.params.GetInt("maze_rows", 7))
        self.maze_cols.setValue(self.params.GetInt("maze_cols", 10))
        self.maze_cell_mm.setValue(self.params.GetInt("maze_cell_mm", 2000))
        self.maze_include_ceiling.setChecked(self.params.GetBool("maze_include_ceiling", False))
        self._update_type_controls()

    def _state(self):
        return {
            "building_type": str(self.building_type.currentData() or "Casa"),
            "seed": int(self.seed.value()),
            "width_mm": float(self.width_mm.value()),
            "depth_mm": float(self.depth_mm.value()),
            "ext_wall_mm": int(self.ext_wall_mm.value()),
            "int_wall_mm": int(self.int_wall_mm.value()),
            "wall_height_mm": int(self.wall_height_mm.value()),
            "create_terrain": bool(self.create_terrain.isChecked()),
            "flatten_pad": bool(self.flatten_pad.isChecked()),
            "pad_margin_mm": int(self.pad_margin_mm.value()),
            "terrain_margin_mm": int(self.terrain_margin_mm.value()),
            "terrain_variation_mm": int(self.terrain_variation_mm.value()),
            "floor_overhang_mm": int(self.floor_overhang_mm.value()),
            "copy_context": bool(self.copy_context.isChecked()),
            "clear_previous": bool(self.clear_previous.isChecked()),
            "maze_rows": int(self.maze_rows.value()),
            "maze_cols": int(self.maze_cols.value()),
            "maze_cell_mm": int(self.maze_cell_mm.value()),
            "include_ceiling": bool(self.maze_include_ceiling.isChecked()),
            "ai_prompt_language": i18n.current_language(),
        }

    def _save(self):
        state = self._state()
        self.params.SetString("building_type", state["building_type"])
        self.params.SetInt("seed", state["seed"])
        self.params.SetFloat("width_mm", state["width_mm"])
        self.params.SetFloat("depth_mm", state["depth_mm"])
        self.params.SetInt("ext_wall_mm", state["ext_wall_mm"])
        self.params.SetInt("int_wall_mm", state["int_wall_mm"])
        self.params.SetInt("wall_height_mm", state["wall_height_mm"])
        self.params.SetBool("create_terrain", state["create_terrain"])
        self.params.SetBool("flatten_pad", state["flatten_pad"])
        self.params.SetInt("pad_margin_mm", state["pad_margin_mm"])
        self.params.SetInt("terrain_margin_mm", state["terrain_margin_mm"])
        self.params.SetInt("terrain_variation_mm", state["terrain_variation_mm"])
        self.params.SetInt("floor_overhang_mm", state["floor_overhang_mm"])
        self.params.SetBool("copy_context", state["copy_context"])
        self.params.SetBool("clear_previous", state["clear_previous"])
        self.params.SetInt("maze_rows", state["maze_rows"])
        self.params.SetInt("maze_cols", state["maze_cols"])
        self.params.SetInt("maze_cell_mm", state["maze_cell_mm"])
        self.params.SetBool("maze_include_ceiling", state["include_ceiling"])

    def _update_type_controls(self, *_args):
        maze_enabled = str(self.building_type.currentData() or "") == "Laberinto"
        self.maze_rows.setEnabled(maze_enabled)
        self.maze_cols.setEnabled(maze_enabled)
        self.maze_cell_mm.setEnabled(maze_enabled)
        self.maze_include_ceiling.setEnabled(maze_enabled)
        self.width_mm.setEnabled(not maze_enabled)
        self.depth_mm.setEnabled(not maze_enabled)

    def _accept(self):
        self._save()
        try:
            root = quick_examples.generate_quick_example(self._state())
            try:
                FreeCADGui.Selection.clearSelection()
                FreeCADGui.Selection.addSelection(root)
                FreeCADGui.SendMsgToActiveView("ViewFit")
            except Exception:
                pass
            self.accept()
        except Exception as exc:
            FreeCAD.Console.PrintError(LOG_PREFIX + "Quick example error: " + str(exc) + "\n")
            QtGui.QMessageBox.critical(self, i18n.tr("Quick Example error"), str(exc))
