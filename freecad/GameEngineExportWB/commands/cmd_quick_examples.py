"""Quick Example command for GameEngineExportWB.
































Name: commands/cmd_quick_examples.py
Purpose: generate small test scenes and optionally copy an AI-ready prompt + JSON context.
Main behavior: keeps stable Quick Example generation while exposing the manual JSON/AI bridge.
Modification notes: preserve saved option keys and canonical internal building type values.
Version: 2026-10-12-photometric-terrain-v1
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
from . import cmd_bim_doors_windows, cmd_roof_quick_example
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
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX + "Quick example UI source: " + os.path.realpath(__file__) + "\n"
        )
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX + "Quick example UI build: tabs-1.1.4-20261012-photometric-terrain\n"
        )
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
        # Direct tab pages: avoid QScrollArea viewport color mismatch on FreeCAD 1.1.4.
        self.resize(580, 470)
        self.setMinimumWidth(500)
        layout = QtGui.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)
        self.tabs = QtGui.QTabWidget(self)
        main_page = QtGui.QWidget(self.tabs)
        terrain_page = QtGui.QWidget(self.tabs)
        options_page = QtGui.QWidget(self.tabs)
        form = QtGui.QFormLayout(main_page)
        terrain_form = QtGui.QFormLayout(terrain_page)
        options_form = QtGui.QFormLayout(options_page)
        for section in (form, terrain_form, options_form):
            section.setSpacing(6)
            section.setHorizontalSpacing(15)
            section.setFieldGrowthPolicy(QtGui.QFormLayout.ExpandingFieldsGrow)
        self._form = form
        self.tabs.addTab(main_page, i18n.bi("Ejemplo", "Example"))
        self.terrain_tab_index = self.tabs.addTab(
            terrain_page, i18n.bi("Terreno y piso", "Terrain and floor")
        )
        self.tabs.addTab(options_page, i18n.bi("Opciones", "Options"))
        layout.addWidget(self.tabs, 1)
















        def add_heading(title):
            label = QtGui.QLabel(title)
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            label.setContentsMargins(0, 8, 0, 3)
            form.addRow(label)
            return label
















































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
































        self.maze_heading = add_heading(i18n.bi("LABERINTO", "MAZE"))
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
































        self.dimensions_heading = add_heading(i18n.bi("DIMENSIONES Y MUROS", "DIMENSIONS AND WALLS"))
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
































        self.bim_heading = add_heading(i18n.bi("PUERTAS, VENTANAS Y TECHO", "DOORS, WINDOWS AND ROOF"))
        self.add_bim_doors_windows = QtGui.QCheckBox(i18n.bi("Agregar puertas y ventanas BIM", "Add BIM doors and windows"))
        self.add_bim_doors_windows.setToolTip(i18n.bi("Crea puertas y ventanas BIM en la casa u oficina generada.", "Creates BIM doors and windows in the generated house or office."))
        form.addRow("", self.add_bim_doors_windows)
        self.add_roof = QtGui.QCheckBox(i18n.bi("Agregar techo", "Add roof"))
        self.add_roof.setToolTip(i18n.bi("Agrega el techo a dos aguas existente.", "Adds the existing gable roof."))
        form.addRow("", self.add_roof)








        self.terrain_heading = None  # Terrain settings are in their own tab
        self.create_terrain = QtGui.QCheckBox(i18n.tr("Create irregular terrain and floor"))
        terrain_form.addRow("", self.create_terrain)
































        self.flatten_pad = QtGui.QCheckBox(i18n.tr("Flatten terrain under building"))
        terrain_form.addRow("", self.flatten_pad)
































        self.pad_margin_mm = QtGui.QSpinBox()
        self.pad_margin_mm.setRange(0, 8000)
        self.pad_margin_mm.setSingleStep(250)
        terrain_form.addRow(i18n.tr("Platform margin mm"), self.pad_margin_mm)
































        self.terrain_margin_mm = QtGui.QSpinBox()
        self.terrain_margin_mm.setRange(2000, 30000)
        self.terrain_margin_mm.setSingleStep(500)
        terrain_form.addRow(i18n.tr("Terrain margin mm"), self.terrain_margin_mm)
































        self.terrain_variation_mm = QtGui.QSpinBox()
        self.terrain_variation_mm.setRange(0, 3000)
        self.terrain_variation_mm.setSingleStep(100)
        terrain_form.addRow(i18n.tr("Terrain relief mm"), self.terrain_variation_mm)
































        self.floor_overhang_mm = QtGui.QSpinBox()
        self.floor_overhang_mm.setRange(0, 2000)
        self.floor_overhang_mm.setSingleStep(50)
        terrain_form.addRow(i18n.tr("Floor overhang mm"), self.floor_overhang_mm)
































        self.options_heading = None  # General options are in their own tab
        self.copy_context = QtGui.QCheckBox(i18n.bi("Copiar contexto para IA (prompt + JSON)", "Copy AI context (prompt + JSON)"))
        self.copy_context.setToolTip(i18n.bi("Copia instrucciones para la IA seguidas del JSON actual, listas para pegar en un chat.", "Copies AI instructions followed by the current JSON, ready to paste into a chat."))
        options_form.addRow("", self.copy_context)
        self.clear_previous = QtGui.QCheckBox(i18n.tr("Delete previous Quick Examples"))
        options_form.addRow("", self.clear_previous)
























































































        # Native FreeCAD controls inherit the active theme from the dialog.
        for control in (
            self.building_type, self.maze_rows, self.maze_cols,
            self.maze_cell_mm, self.seed, self.width_mm, self.depth_mm,
            self.ext_wall_mm, self.int_wall_mm, self.wall_height_mm,
            self.pad_margin_mm, self.terrain_margin_mm,
            self.terrain_variation_mm, self.floor_overhang_mm,
        ):
            control.setMinimumWidth(170)
            control.setSizePolicy(
                QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Fixed
            )








        # No scroll viewport: all three pages are native Qt widgets.
































        buttons = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)
        buttons.button(QtGui.QDialogButtonBox.Ok).setText(
            i18n.bi("Generar ejemplo", "Generate example")
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.building_type.currentIndexChanged.connect(self._update_type_controls)
        self.create_terrain.toggled.connect(self._update_terrain_controls)
        self.flatten_pad.toggled.connect(self._update_terrain_controls)
































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
        self.add_bim_doors_windows.setChecked(self.params.GetBool("add_bim_doors_windows", True))
        self.add_roof.setChecked(self.params.GetBool("add_roof", True))
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
            "add_bim_doors_windows": bool(self.add_bim_doors_windows.isChecked()),
            "add_roof": bool(self.add_roof.isChecked()),
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
        self.params.SetBool("add_bim_doors_windows", state["add_bim_doors_windows"])
        self.params.SetBool("add_roof", state["add_roof"])
        self.params.SetInt("maze_rows", state["maze_rows"])
        self.params.SetInt("maze_cols", state["maze_cols"])
        self.params.SetInt("maze_cell_mm", state["maze_cell_mm"])
        self.params.SetBool("maze_include_ceiling", state["include_ceiling"])
































    def _update_type_controls(self, *_args):
        maze_enabled = str(self.building_type.currentData() or "") == "Laberinto"
        example_type = str(self.building_type.currentData() or "Casa")
        terrain_visible = example_type != "Laberinto"
        self.maze_heading.setVisible(maze_enabled)
        self.tabs.setTabEnabled(self.terrain_tab_index, terrain_visible)
        self.bim_heading.setVisible(not maze_enabled)
















        def show_field(widget, visible):
            widget.setVisible(visible)
            label = self._form.labelForField(widget)
            if label is not None:
                label.setVisible(visible)
















        for widget in (self.maze_rows, self.maze_cols, self.maze_cell_mm, self.maze_include_ceiling):
            show_field(widget, maze_enabled)
        for widget in (self.width_mm, self.depth_mm):
            show_field(widget, not maze_enabled)
        # The whole terrain page is disabled when the generator ignores terrain.
        for widget in (self.add_bim_doors_windows, self.add_roof):
            show_field(widget, not maze_enabled)
        self._update_terrain_controls()
















    def _update_terrain_controls(self, *_args):
        enabled = self.create_terrain.isChecked()
        self.flatten_pad.setEnabled(enabled)
        self.pad_margin_mm.setEnabled(enabled and self.flatten_pad.isChecked())
        self.terrain_margin_mm.setEnabled(enabled)
        self.terrain_variation_mm.setEnabled(enabled)
        self.floor_overhang_mm.setEnabled(enabled)
































    def _accept(self):
        self._save()
        try:
            state = self._state()
            root = quick_examples.generate_quick_example(state)
            try:
                FreeCADGui.Selection.clearSelection()
                FreeCADGui.Selection.addSelection(root)
                FreeCADGui.SendMsgToActiveView("ViewFit")
            except Exception:
                pass
            if state["building_type"] != "Laberinto":
                if state["add_bim_doors_windows"]:
                    cmd_bim_doors_windows.CommandClass().Activated()
                if state["add_roof"]:
                    cmd_roof_quick_example.CommandClass().Activated()
            self.accept()
        except Exception as exc:
            FreeCAD.Console.PrintError(LOG_PREFIX + "Quick example error: " + str(exc) + "\n")
            QtGui.QMessageBox.critical(self, i18n.tr("Quick Example error"), str(exc))