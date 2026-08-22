"""Command to add CGE light properties to a luminaire master."""

from __future__ import annotations

import os
from pathlib import Path

import FreeCAD
import FreeCADGui

from .. import i18n

from ..core import exporter_x3d, lights, persist
from ..ui.panel_export import _ensure_qt_compat


_ensure_qt_compat()

from PySide import QtCore, QtGui  # noqa: E402


LOG_PREFIX = "[GAMEEXPORT] "
PARAM_GROUP = "User parameter:Plugins/GameEngineExportWB"
ICON_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "resources", "icons", "add_light_properties.svg")
).replace(os.sep, "/")


def _info(message: str) -> None:
    FreeCAD.Console.PrintMessage(LOG_PREFIX + "[INFO] " + message + "\n")


def _warn(message: str) -> None:
    FreeCAD.Console.PrintWarning(LOG_PREFIX + "[WARN] " + message + "\n")


class CommandClass:
    """FreeCAD command wrapper for light master configuration."""

    CommandName = "GameEngineExport_AddLightProperties"

    def GetResources(self):  # noqa: N802
        return {
            "MenuText": i18n.bi("Agregar propiedades a luz", "Add Light Properties"),
            "ToolTip": i18n.bi(
                "Define propiedades de luz en la luminaria master. Los Links heredaran la configuracion.",
                "Define light properties on the master luminaire. Links inherit the configuration.",
            ),
            "Pixmap": ICON_PATH,
        }

    def Activated(self):  # noqa: N802
        selection = FreeCADGui.Selection.getSelection()
        if not selection:
            QtGui.QMessageBox.warning(
                None,
                i18n.bi("Agregar propiedades a luz", "Add Light Properties"),
                i18n.bi("Seleccione una luminaria master o una instancia Link.", "Select a master luminaire or a Link instance."),
            )
            _warn("Seleccione una luminaria master o una instancia Link.")
            return
        dialog = AddLightPropertiesDialog(selection[0])
        dialog.exec_()

    def IsActive(self):  # noqa: N802
        return FreeCAD.ActiveDocument is not None


class AddLightPropertiesDialog(QtGui.QDialog):
    """Small modal dialog to edit CGE_Light properties on a master object."""

    def __init__(self, selected_obj=None, parent=None):
        super().__init__(parent)
        self.params = FreeCAD.ParamGet(PARAM_GROUP)
        self.doc = FreeCAD.ActiveDocument
        self.source_obj = None
        self.master_obj = None
        self.current_color = (1.0, 0.95, 0.85)
        self.setWindowTitle(i18n.bi("Agregar propiedades a luz", "Add Light Properties"))
        self._build_ui()
        self._load_selection(selected_obj)

    def _build_ui(self):
        main = QtGui.QVBoxLayout(self)

        select_group = QtGui.QGroupBox(i18n.bi("Seleccionar master", "Select master"))
        select_layout = QtGui.QGridLayout(select_group)
        select_layout.addWidget(QtGui.QLabel(i18n.bi("Objeto master:", "Master object:")), 0, 0)
        self.master_line = QtGui.QLineEdit()
        self.master_line.setReadOnly(True)
        select_layout.addWidget(self.master_line, 0, 1)
        self.btn_take_selection = QtGui.QPushButton(i18n.bi("Tomar seleccion", "Use selection"))
        self.btn_take_selection.clicked.connect(self._take_selection)
        select_layout.addWidget(self.btn_take_selection, 0, 2)
        self.links_label = QtGui.QLabel(i18n.bi("Links detectados: 0", "Detected links: 0"))
        select_layout.addWidget(self.links_label, 1, 0, 1, 3)
        self.selection_info = QtGui.QLabel(
            "Las propiedades se guardan en el master. Todas las instancias Link heredaran esta configuracion."
        )
        self.selection_info.setWordWrap(True)
        select_layout.addWidget(self.selection_info, 2, 0, 1, 3)
        main.addWidget(select_group)

        type_group = QtGui.QGroupBox(i18n.bi("Tipo y distribucion", "Type and distribution"))
        type_layout = QtGui.QGridLayout(type_group)
        self.chk_enabled = QtGui.QCheckBox(i18n.bi("Luz habilitada", "Light enabled"))
        type_layout.addWidget(self.chk_enabled, 0, 0, 1, 2)
        type_layout.addWidget(QtGui.QLabel(i18n.bi("Tipo de luz:", "Light type:")), 1, 0)
        self.combo_type = QtGui.QComboBox()
        self.combo_type.addItems(lights.CGE_LIGHT_TYPES)
        type_layout.addWidget(self.combo_type, 1, 1)
        type_layout.addWidget(QtGui.QLabel(i18n.bi("Patron:", "Pattern:")), 2, 0)
        self.combo_pattern = QtGui.QComboBox()
        self.combo_pattern.addItems(lights.CGE_LIGHT_PATTERNS)
        type_layout.addWidget(self.combo_pattern, 2, 1)
        type_layout.addWidget(QtGui.QLabel(i18n.bi("Filas:", "Rows:")), 3, 0)
        self.spin_rows = QtGui.QSpinBox()
        self.spin_rows.setRange(1, 25)
        type_layout.addWidget(self.spin_rows, 3, 1)
        type_layout.addWidget(QtGui.QLabel(i18n.bi("Columnas:", "Columns:")), 4, 0)
        self.spin_cols = QtGui.QSpinBox()
        self.spin_cols.setRange(1, 25)
        type_layout.addWidget(self.spin_cols, 4, 1)
        type_layout.addWidget(QtGui.QLabel(i18n.bi("Cantidad:", "Count:")), 5, 0)
        self.spin_count = QtGui.QSpinBox()
        self.spin_count.setRange(1, 25)
        type_layout.addWidget(self.spin_count, 5, 1)
        main.addWidget(type_group)

        position_group = QtGui.QGroupBox(i18n.bi("Posicion y direccion", "Position and direction"))
        position_layout = QtGui.QGridLayout(position_group)
        position_layout.addWidget(QtGui.QLabel(i18n.bi("Direccion de emision:", "Emission direction:")), 0, 0)
        self.combo_direction = QtGui.QComboBox()
        self.combo_direction.addItems(lights.CGE_LIGHT_DIRECTIONS)
        position_layout.addWidget(self.combo_direction, 0, 1)
        position_layout.addWidget(QtGui.QLabel(i18n.bi("Origen de luz:", "Light origin:")), 1, 0)
        self.combo_origin = QtGui.QComboBox()
        self.combo_origin.addItem(i18n.bi("Automatico desde cara emisora", "Automatic from emitting face"), "AutoFaceCenter")
        self.combo_origin.addItem(i18n.bi("Punto local manual", "Manual local point"), "ManualLocalPoint")
        self.combo_origin.addItem(i18n.bi("Marcador de referencia", "Reference marker"), "ReferenceMarker")
        self.combo_origin.setToolTip(i18n.bi("ReferenceMarker: disponible en una proxima version.", "ReferenceMarker: available in a future version."))
        position_layout.addWidget(self.combo_origin, 1, 1)
        self._disable_reference_marker_item()
        position_layout.addWidget(QtGui.QLabel(i18n.bi("Offset fuera de luminaria (mm):", "Offset outside luminaire (mm):")), 2, 0)
        self.spin_offset = QtGui.QDoubleSpinBox()
        self.spin_offset.setRange(0.0, 10000.0)
        self.spin_offset.setDecimals(1)
        self.spin_offset.setSuffix(" mm")
        position_layout.addWidget(self.spin_offset, 2, 1)
        self.spin_local_x = self._length_spin()
        self.spin_local_y = self._length_spin()
        self.spin_local_z = self._length_spin()
        position_layout.addWidget(QtGui.QLabel(i18n.bi("Local X (mm):", "Local X (mm):")), 3, 0)
        position_layout.addWidget(self.spin_local_x, 3, 1)
        position_layout.addWidget(QtGui.QLabel(i18n.bi("Local Y (mm):", "Local Y (mm):")), 4, 0)
        position_layout.addWidget(self.spin_local_y, 4, 1)
        position_layout.addWidget(QtGui.QLabel(i18n.bi("Local Z (mm):", "Local Z (mm):")), 5, 0)
        position_layout.addWidget(self.spin_local_z, 5, 1)
        main.addWidget(position_group)

        props_group = QtGui.QGroupBox(i18n.bi("Propiedades de luz", "Light properties"))
        props_layout = QtGui.QGridLayout(props_group)
        self.btn_color = QtGui.QPushButton(i18n.bi("Color...", "Color..."))
        self.btn_color.clicked.connect(self._choose_color)
        props_layout.addWidget(self.btn_color, 0, 0)
        props_layout.addWidget(QtGui.QLabel(i18n.bi("Intensidad:", "Intensity:")), 1, 0)
        self.spin_intensity = QtGui.QDoubleSpinBox()
        self.spin_intensity.setRange(0.0, 20.0)
        self.spin_intensity.setDecimals(2)
        self.spin_intensity.setSingleStep(0.1)
        props_layout.addWidget(self.spin_intensity, 1, 1)
        props_layout.addWidget(QtGui.QLabel(i18n.bi("Alcance (m):", "Range (m):")), 2, 0)
        self.spin_range = QtGui.QDoubleSpinBox()
        self.spin_range.setRange(0.1, 500.0)
        self.spin_range.setDecimals(2)
        self.spin_range.setSuffix(" m")
        props_layout.addWidget(self.spin_range, 2, 1)
        props_layout.addWidget(QtGui.QLabel(i18n.bi("Flujo luminoso (lm):", "Luminous flux (lm):")), 3, 0)
        self.spin_lumens = QtGui.QDoubleSpinBox()
        self.spin_lumens.setRange(0.0, 200000.0)
        self.spin_lumens.setDecimals(0)
        self.spin_lumens.setSingleStep(100.0)
        props_layout.addWidget(self.spin_lumens, 3, 1)
        props_layout.addWidget(QtGui.QLabel(i18n.bi("Angulo completo de haz (°):", "Full beam angle (deg):")), 4, 0)
        self.spin_beam_angle = QtGui.QDoubleSpinBox()
        self.spin_beam_angle.setRange(1.0, 179.0)
        self.spin_beam_angle.setDecimals(1)
        self.spin_beam_angle.setSingleStep(5.0)
        props_layout.addWidget(self.spin_beam_angle, 4, 1)
        props_layout.addWidget(QtGui.QLabel(i18n.bi("Intensidad calculada (cd):", "Calculated intensity (cd):")), 5, 0)
        self.line_candela = QtGui.QLineEdit()
        self.line_candela.setReadOnly(True)
        props_layout.addWidget(self.line_candela, 5, 1)
        props_layout.addWidget(QtGui.QLabel(i18n.bi("Temperatura de color CCT (K):", "Color temperature CCT (K):")), 6, 0)
        self.spin_cct = QtGui.QDoubleSpinBox()
        self.spin_cct.setRange(1800.0, 10000.0)
        self.spin_cct.setDecimals(0)
        self.spin_cct.setSingleStep(100.0)
        props_layout.addWidget(self.spin_cct, 6, 1)
        self.chk_preview = QtGui.QCheckBox(i18n.bi("Mostrar objeto representativo", "Show representative object"))
        props_layout.addWidget(self.chk_preview, 7, 0, 1, 2)
        main.addWidget(props_group)

        self.status_label = QtGui.QLabel("")
        self.status_label.setStyleSheet("color: #2563eb;")
        main.addWidget(self.status_label)

        buttons = QtGui.QHBoxLayout()
        self.btn_preview = QtGui.QPushButton(i18n.bi("Vista previa", "Preview"))
        self.btn_apply = QtGui.QPushButton(i18n.bi("Aplicar", "Apply"))
        self.btn_cancel = QtGui.QPushButton(i18n.bi("Cancelar", "Cancel"))
        self.btn_preview.clicked.connect(self._preview)
        self.btn_apply.clicked.connect(self._apply)
        self.btn_cancel.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(self.btn_preview)
        buttons.addWidget(self.btn_apply)
        buttons.addWidget(self.btn_cancel)
        main.addLayout(buttons)

        self.combo_type.currentIndexChanged.connect(self._update_control_states)
        self.combo_pattern.currentIndexChanged.connect(self._update_control_states)
        self.combo_origin.currentIndexChanged.connect(self._update_control_states)
        self.spin_lumens.valueChanged.connect(self._update_candela)
        self.spin_beam_angle.valueChanged.connect(self._update_candela)

    def _length_spin(self):
        spin = QtGui.QDoubleSpinBox()
        spin.setRange(-100000.0, 100000.0)
        spin.setDecimals(1)
        spin.setSuffix(" mm")
        return spin

    def _disable_reference_marker_item(self):
        try:
            index = self.combo_origin.findData("ReferenceMarker")
            item = self.combo_origin.model().item(index)
            item.setEnabled(False)
            item.setToolTip(i18n.bi("Disponible en una proxima version.", "Available in a future version."))
        except Exception:
            pass

    def _take_selection(self):
        selection = FreeCADGui.Selection.getSelection()
        if not selection:
            self.status_label.setText("Seleccione una luminaria master o una instancia Link.")
            return
        self._load_selection(selection[0])

    def _load_selection(self, obj):
        if obj is None:
            return
        self.source_obj = obj
        master = lights.resolve_master_object(obj)
        if master is None:
            self.status_label.setText("No se pudo resolver el master.")
            return
        self.master_obj = master
        self.master_line.setText((getattr(master, "Label", "") or getattr(master, "Name", "")))
        link_count = lights.count_links_to_master(self.doc, master)
        self.links_label.setText("Links detectados: " + str(link_count))
        if str(getattr(obj, "TypeId", "") or "") == "App::Link":
            self.selection_info.setText(
                "Instancia seleccionada. Se editaran las propiedades del master: "
                + (getattr(master, "Name", "") or "Unknown")
            )
        else:
            self.selection_info.setText(
                "Las propiedades se guardan en el master. Todas las instancias Link heredaran esta configuracion."
            )
        values = lights.read_cge_light_properties(master, create=False) or self._default_values()
        self._load_values(values)
        _info("Links detected: " + str(link_count))

    def _default_values(self) -> dict:
        return {
            "enabled": True,
            "type": "Point",
            "pattern": "Single",
            "direction": "Down",
            "origin_mode": "AutoFaceCenter",
            "offset_mm": float(self.params.GetFloat("default_light_offset", 50.0)),
            "intensity": float(self.params.GetFloat("default_light_intensity", 1.0)),
            "range_m": float(self.params.GetFloat("default_light_range", 8.0)),
            "lumens": float(self.params.GetFloat("default_light_lumens", lights.DEFAULT_LUMENS)),
            "beam_angle_deg": float(self.params.GetFloat("default_light_beam_angle", lights.DEFAULT_BEAM_ANGLE_DEG)),
            "cct_kelvin": float(self.params.GetFloat("default_light_cct", lights.DEFAULT_CCT_K)),
            "rows": 2,
            "cols": 2,
            "count": 6,
            "color": (1.0, 0.95, 0.85),
            "local_point": (0.0, 0.0, 0.0),
            "preview_enabled": bool(self.params.GetBool("show_light_preview", True)),
        }

    def _load_values(self, values: dict):
        self.chk_enabled.setChecked(bool(values.get("enabled", True)))
        self._set_combo_text(self.combo_type, str(values.get("type", "Point")))
        self._set_combo_text(self.combo_pattern, str(values.get("pattern", "Single")))
        self._set_combo_text(self.combo_direction, str(values.get("direction", "Down")))
        self._set_combo_data(self.combo_origin, str(values.get("origin_mode", "AutoFaceCenter")))
        self.spin_offset.setValue(float(values.get("offset_mm", 50.0)))
        self.spin_intensity.setValue(float(values.get("intensity", 1.0)))
        self.spin_range.setValue(float(values.get("range_m", 8.0)))
        self.spin_lumens.setValue(float(values.get("lumens", lights.DEFAULT_LUMENS)))
        self.spin_beam_angle.setValue(float(values.get("beam_angle_deg", lights.DEFAULT_BEAM_ANGLE_DEG)))
        self.spin_cct.setValue(float(values.get("cct_kelvin", lights.DEFAULT_CCT_K)))
        self.spin_rows.setValue(int(values.get("rows", 2)))
        self.spin_cols.setValue(int(values.get("cols", 2)))
        self.spin_count.setValue(int(values.get("count", 6)))
        color = values.get("color", (1.0, 0.95, 0.85))
        self.current_color = tuple(color)
        local_point = values.get("local_point", (0.0, 0.0, 0.0))
        self.spin_local_x.setValue(float(local_point[0]))
        self.spin_local_y.setValue(float(local_point[1]))
        self.spin_local_z.setValue(float(local_point[2]))
        self.chk_preview.setChecked(bool(values.get("preview_enabled", True)))
        self._update_color_button()
        self._update_control_states()
        self._update_candela()

    def _values_from_ui(self) -> dict:
        return {
            "enabled": bool(self.chk_enabled.isChecked()),
            "type": str(self.combo_type.currentText()),
            "pattern": str(self.combo_pattern.currentText()),
            "direction": str(self.combo_direction.currentText()),
            "origin_mode": str(self.combo_origin.itemData(self.combo_origin.currentIndex())),
            "offset_mm": float(self.spin_offset.value()),
            "intensity": float(self.spin_intensity.value()),
            "range_m": float(self.spin_range.value()),
            "lumens": float(self.spin_lumens.value()),
            "beam_angle_deg": float(self.spin_beam_angle.value()),
            "cct_kelvin": float(self.spin_cct.value()),
            "rows": int(self.spin_rows.value()),
            "cols": int(self.spin_cols.value()),
            "count": int(self.spin_count.value()),
            "color": self.current_color,
            "local_point": (
                float(self.spin_local_x.value()),
                float(self.spin_local_y.value()),
                float(self.spin_local_z.value()),
            ),
            "preview_enabled": bool(self.chk_preview.isChecked()),
        }

    def _validate(self, values: dict) -> bool:
        if self.master_obj is None:
            self.status_label.setText("No hay master seleccionado.")
            return False
        if values["origin_mode"] == "AutoFaceCenter" and not hasattr(self.master_obj, "Shape"):
            self.status_label.setText("El master no tiene Shape valido para AutoFaceCenter.")
            return False
        total = 1
        if values["type"] == "RectPanel" or values["pattern"] == "Grid":
            total = values["rows"] * values["cols"]
        elif values["type"] in {"Linear", "Circular"} or values["pattern"] in {"Line", "Ring"}:
            total = values["count"]
        if total > lights.MAX_POINTS_PER_LUMINAIRE:
            _warn("Light distribution limited to " + str(lights.MAX_POINTS_PER_LUMINAIRE) + " points")
        return True

    def _preview(self):
        values = self._values_from_ui()
        if not self._validate(values):
            return
        definition = lights.LightDefinition(
            master_obj=self.master_obj,
            source_obj=self.source_obj or self.master_obj,
            effective_placement=lights.get_global_placement(self.source_obj or self.master_obj),
            light_properties=values,
        )
        entries = lights.generate_light_points_for_definition(definition)
        count = lights.create_temp_light_preview(self.doc, entries)
        self.status_label.setText("Vista previa creada: " + str(count) + " puntos.")

    def _apply(self):
        values = self._values_from_ui()
        if not self._validate(values):
            return
        lights.write_cge_light_properties(self.master_obj, values)
        if values.get("preview_enabled"):
            self._preview()
        else:
            lights.remove_temp_light_preview(self.doc)
        self._save_ui_defaults(values)
        link_count = lights.count_links_to_master(self.doc, self.master_obj)
        _info("Light master configured: " + (getattr(self.master_obj, "Name", "") or "Unknown"))
        _info("Links detected: " + str(link_count))
        try:
            self.doc.recompute()
        except Exception:
            pass
        self.accept()

    def _save_ui_defaults(self, values: dict):
        self.params.SetBool("show_light_preview", bool(values.get("preview_enabled", True)))
        self.params.SetFloat("default_light_offset", float(values.get("offset_mm", 50.0)))
        self.params.SetFloat("default_light_intensity", float(values.get("intensity", 1.0)))
        self.params.SetFloat("default_light_range", float(values.get("range_m", 8.0)))
        self.params.SetFloat("default_light_lumens", float(values.get("lumens", lights.DEFAULT_LUMENS)))
        self.params.SetFloat("default_light_beam_angle", float(values.get("beam_angle_deg", lights.DEFAULT_BEAM_ANGLE_DEG)))
        self.params.SetFloat("default_light_cct", float(values.get("cct_kelvin", lights.DEFAULT_CCT_K)))
        doc = FreeCAD.ActiveDocument
        if doc is None or not getattr(doc, "FileName", ""):
            return
        path = Path(doc.FileName)
        data = persist.load_sidecar(path) or {}
        data["light_properties_ui"] = {
            "show_light_preview": bool(values.get("preview_enabled", True)),
            "default_light_offset": float(values.get("offset_mm", 50.0)),
            "default_light_intensity": float(values.get("intensity", 1.0)),
            "default_light_range": float(values.get("range_m", 8.0)),
            "default_light_lumens": float(values.get("lumens", lights.DEFAULT_LUMENS)),
            "default_light_beam_angle": float(values.get("beam_angle_deg", lights.DEFAULT_BEAM_ANGLE_DEG)),
            "default_light_cct": float(values.get("cct_kelvin", lights.DEFAULT_CCT_K)),
        }
        persist.save_sidecar(path, data)

    def _choose_color(self):
        current = QtGui.QColor(
            int(self.current_color[0] * 255),
            int(self.current_color[1] * 255),
            int(self.current_color[2] * 255),
        )
        color = QtGui.QColorDialog.getColor(current, self, "Color de luz / Light color")
        if color.isValid():
            self.current_color = (color.red() / 255.0, color.green() / 255.0, color.blue() / 255.0)
            self._update_color_button()

    def _update_color_button(self):
        r = int(max(0, min(255, round(self.current_color[0] * 255.0))))
        g = int(max(0, min(255, round(self.current_color[1] * 255.0))))
        b = int(max(0, min(255, round(self.current_color[2] * 255.0))))
        color = QtGui.QColor(r, g, b)
        text_color = "#000000" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"
        self.btn_color.setStyleSheet(
            "background-color: " + color.name() + "; color: " + text_color + "; border: 1px solid #444;"
        )

    def _update_candela(self, *_args):
        value = exporter_x3d.photometric_candela(
            float(self.spin_lumens.value()), float(self.spin_beam_angle.value())
        )
        self.line_candela.setText(f"{value:.1f} cd")

    def _update_control_states(self):
        light_type = str(self.combo_type.currentText())
        pattern = str(self.combo_pattern.currentText())
        use_grid = light_type == "RectPanel" or pattern == "Grid"
        use_count = light_type in {"Linear", "Circular"} or pattern in {"Line", "Ring"}
        self.spin_rows.setEnabled(use_grid)
        self.spin_cols.setEnabled(use_grid)
        self.spin_count.setEnabled(use_count)
        manual = str(self.combo_origin.itemData(self.combo_origin.currentIndex())) == "ManualLocalPoint"
        self.spin_local_x.setEnabled(manual)
        self.spin_local_y.setEnabled(manual)
        self.spin_local_z.setEnabled(manual)

    def _set_combo_text(self, combo, text: str):
        index = combo.findText(text)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _set_combo_data(self, combo, value: str):
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)
