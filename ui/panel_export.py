"""Export TaskPanel for Game Engine Export WB.

Descripcion rapida: panel para escoger objetos, ruta y ejecutar la exportacion X3D.
Fecha y hora: 2025-10-13 19:00 UTC.
Revision: 2026-08-22 10:58 -06:00 - guided Castle executable configuration.
Instrucciones clave:
- Trabajar con listas de objetos disponibles y seleccionados.
- Leer configuracion previa desde ParamGet y permitir ajustes rapidos.
- Realizar exportacion inmediata al aceptar, con logs [GAMEEXPORT].
"""

# Qt compatibility for FreeCAD 1.x (PySide6) and older builds.
def _ensure_qt_compat():
    import sys
    import types

    QtCore = QtGui = QtWidgets = None
    binding_name = None

    for candidate in ("PySide6", "PySide2", "PySide"):
        try:
            if candidate == "PySide":
                from PySide import QtCore as _QtCore, QtGui as _QtGui
                _QtWidgets = _QtGui
            else:
                module = __import__(candidate, fromlist=["QtCore", "QtGui", "QtWidgets"])
                _QtCore = module.QtCore
                _QtGui = module.QtGui
                _QtWidgets = module.QtWidgets
            QtCore, QtGui, QtWidgets = _QtCore, _QtGui, _QtWidgets
            binding_name = candidate
            break
        except Exception:
            continue

    if QtCore is None:
        return

    qtgui_compat = types.ModuleType("QtGui")
    qtgui_compat.__dict__.update(getattr(QtGui, "__dict__", {}))
    qtgui_compat.__dict__.update(getattr(QtWidgets, "__dict__", {}))

    qtsvg_compat = None
    for module_name in ("QtSvg", "QtSvgWidgets"):
        try:
            module = __import__(binding_name, fromlist=[module_name])
            qt_module = getattr(module, module_name)
        except Exception:
            continue
        if qtsvg_compat is None:
            qtsvg_compat = types.ModuleType("QtSvg")
        qtsvg_compat.__dict__.update(getattr(qt_module, "__dict__", {}))

    qtuitools_compat = None
    try:
        module = __import__(binding_name, fromlist=["QtUiTools"])
        qtuitools_compat = module.QtUiTools
    except Exception:
        pass

    for package_name in ("PySide2", "PySide"):
        package = sys.modules.get(package_name)
        if package is None:
            package = types.ModuleType(package_name)
            sys.modules[package_name] = package
        package.QtCore = QtCore
        package.QtGui = qtgui_compat
        package.QtWidgets = QtWidgets
        sys.modules[package_name + ".QtCore"] = QtCore
        sys.modules[package_name + ".QtGui"] = qtgui_compat
        sys.modules[package_name + ".QtWidgets"] = QtWidgets
        if qtsvg_compat is not None:
            package.QtSvg = qtsvg_compat
            sys.modules[package_name + ".QtSvg"] = qtsvg_compat
        if qtuitools_compat is not None:
            package.QtUiTools = qtuitools_compat
            sys.modules[package_name + ".QtUiTools"] = qtuitools_compat


_ensure_qt_compat()

import datetime
import json
import math
import os
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from PySide import QtCore, QtGui

from .. import i18n
from ..core import exporter_x3d, gamestart, lighting_profiles, material_assignments, persist, lights, web_preview
from . import panel_info
from .output_defaults import (
    compute_output_defaults,
    ensure_output_directory,
    normalize_base_name,
    persist_output_settings,
)


def _git_last_update_label() -> str:
    try:
        repo_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            ["git", "log", "-1", "--format=%cd", "--date=iso"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=1.5,
            check=True,
        )
        ts = completed.stdout.strip()
        if ts:
            return f"Actualizado: {ts}"
    except Exception:
        pass
    return "Actualizado: desconocido"

FreeCAD = __import__("FreeCAD")
FreeCADGui = __import__("FreeCADGui")

PARAM_GROUP = "User parameter:Plugins/GameEngineExportWB"


def _safe_path_label(value) -> str:
    """Return only the final path component for normal logs/debug sharing."""
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    return text.rstrip("/").rsplit("/", 1)[-1]


def _sanitize_debug_value(value, key_hint=""):
    """Remove machine-specific absolute paths from generated debug JSON."""
    key = str(key_hint or "").lower()
    if isinstance(value, dict):
        return {str(k): _sanitize_debug_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_debug_value(item, key_hint) for item in value]
    if isinstance(value, str) and any(token in key for token in ("path", "file", "dir")):
        return _safe_path_label(value)
    return value


def _is_quick_example_document(doc) -> bool:
    """Detect Quick Example documents without relying only on document names."""
    if doc is None:
        return False
    for obj in list(getattr(doc, "Objects", []) or []):
        props = list(getattr(obj, "PropertiesList", []) or [])
        if "GEE_QuickExampleObject" in props or "GEE_QuickExampleRoot" in props:
            return True
    return str(getattr(doc, "Name", "") or "").startswith("GameEngineExport_QuickExample")
DEBUG_VERSION = "2026-08-22-castle-config-v1"
ARCHITECTURAL_PROFILE_VERSION = "architectural-complete-v5"
ARCHITECTURAL_CGE_LIGHT_RADIUS_M = 4.0
ARCHITECTURAL_GLOBAL_AMBIENT = 0.12
ARCHITECTURAL_GLOBAL_INTENSITY = 0.32
ARCHITECTURAL_CAMERA_FILL_INTENSITY = 0.45


def _qt_button_mask(*buttons) -> int:
    mask = 0
    for button in buttons:
        try:
            mask |= int(button)
            continue
        except TypeError:
            pass
        value = getattr(button, "value", button)
        mask |= int(value)
    return mask


class ExportTaskPanel:
    """TaskPanel to manage selection and export workflow."""

    def __init__(self):
        FreeCAD.Console.PrintMessage("[GAMEEXPORT] Opening export panel\n")
        FreeCAD.Console.PrintMessage("[GAMEEXPORT] Debug version: " + DEBUG_VERSION + "\n")
        self.params = FreeCAD.ParamGet(PARAM_GROUP)
        self.widget = QtGui.QWidget()
        self.widget.setWindowTitle("Game Engine Export - " + i18n.bi("Seleccion y exportacion", "Selection and export"))
        self.form = self.widget
        self.root_names = []
        self.export_names = set()
        self.light_names = set()
        self.material_object_names = []
        self.sidecar_data = {}
        self.active_lighting_profile = lighting_profiles.DEFAULT_PROFILE_NAME
        self.custom_lighting_profiles = lighting_profiles.loads_custom_profiles(
            self.params.GetString(lighting_profiles.CUSTOM_PROFILES_PARAM, "")
        )
        self.doc_path = None
        self.global_light_color = (1.0, 0.95, 0.85)
        self.light_color_current = (1.0, 1.0, 1.0)

        layout = QtGui.QVBoxLayout(self.widget)
        self.version_label = QtGui.QLabel(_git_last_update_label() + " | Panel: " + DEBUG_VERSION)
        self.version_label.setStyleSheet("color: #1f4e79; font-size: 11px;")
        layout.addWidget(self.version_label)

        self.tabs = QtGui.QTabWidget()
        layout.addWidget(self.tabs)

        scene_tab = QtGui.QWidget()
        scene_layout = QtGui.QVBoxLayout(scene_tab)
        scene_layout.addWidget(self._build_root_group())
        scene_layout.addWidget(self._build_gamestart_group())
        scene_layout.addWidget(self._build_lists_group())
        scene_layout.addWidget(self._build_output_group())
        scene_layout.addStretch()
        self.tabs.addTab(scene_tab, i18n.bi("Escena", "Scene"))

        lighting_tab = self._build_lighting_tab()
        self.tabs.addTab(lighting_tab, i18n.bi("Iluminacion", "Lighting"))

        textures_tab = self._build_textures_tab()
        self.tabs.addTab(textures_tab, i18n.bi("Texturas", "Textures"))

        config_tab = self._build_config_tab()
        self.tabs.addTab(config_tab, i18n.bi("Configuracion", "Configuration"))

        info_tab = panel_info.build_info_tab()
        self.tabs.addTab(info_tab, i18n.bi("Informacion", "About"))
        self.status_label = QtGui.QLabel("")
        self.status_label.setStyleSheet("color: #2563eb;")
        layout.addWidget(self.status_label)
        layout.addStretch()

        self._load_defaults()
        self._refresh_available()

    def _build_root_group(self):
        group = QtGui.QGroupBox(i18n.bi("Raiz", "Root"))
        layout = QtGui.QHBoxLayout(group)

        self.root_line = QtGui.QLineEdit()
        self.root_line.setReadOnly(True)
        layout.addWidget(self.root_line, stretch=1)

        btn_use_selection = QtGui.QPushButton(i18n.bi("Tomar seleccion", "Use selection"))
        btn_use_selection.setToolTip(
            i18n.bi('Agrega los objetos/grupos seleccionados como raices.', 'Append selected objects/groups as roots.')
        )
        btn_use_selection.clicked.connect(self._use_selection_as_root)
        layout.addWidget(btn_use_selection)

        self.btn_clear_root = QtGui.QPushButton(i18n.bi("Limpiar", "Clear"))
        self.btn_clear_root.setToolTip(
            i18n.bi('Quita todas las raices seleccionadas.', 'Remove all selected roots.')
        )
        self.btn_clear_root.clicked.connect(self._clear_root_selection)
        layout.addWidget(self.btn_clear_root)

        return group

    def _build_gamestart_group(self):
        group = QtGui.QGroupBox("GameStart")
        layout = QtGui.QHBoxLayout(group)
        self.gamestart_line = QtGui.QLineEdit()
        self.btn_create_gamestart = QtGui.QPushButton(i18n.bi("Crear", "Create"))
        self.label_gamestart_state = QtGui.QLabel("")
        self.btn_create_gamestart.setToolTip(
            i18n.bi('Crea un marcador (cono+base). Sus propiedades definen el Viewpoint inicial.', 'Creates a marker (cone+base). Its properties define the initial Viewpoint.')
        )
        layout.addWidget(self.gamestart_line)
        layout.addWidget(self.btn_create_gamestart)
        layout.addWidget(self.label_gamestart_state)
        self.btn_create_gamestart.clicked.connect(self._create_gamestart)
        return group

    def _build_lists_group(self):
        group = QtGui.QGroupBox(i18n.bi("Objetos", "Objects"))
        main_layout = QtGui.QVBoxLayout(group)
        layout = QtGui.QHBoxLayout()

        self.list_available = QtGui.QListWidget()
        self.list_available.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.list_available)

        btn_layout = QtGui.QVBoxLayout()
        btn_add = QtGui.QPushButton(">>")
        btn_remove = QtGui.QPushButton("<<")
        btn_add.clicked.connect(self._move_selected_to_export)
        btn_remove.clicked.connect(self._move_selected_to_available)
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_remove)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.list_export = QtGui.QListWidget()
        self.list_export.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.list_export)

        main_layout.addLayout(layout)

        self.chk_include_hidden_3d_objects = QtGui.QCheckBox(
            i18n.bi("Incluir objetos 3D ocultos", "Include hidden 3D objects")
        )
        self.chk_include_hidden_3d_objects.setToolTip(
            i18n.bi('Incluye temporalmente solidos y mallas ocultos, como cielorrasos, columnas, equipos y mobiliario.', 'Temporarily includes hidden solids and meshes such as ceilings, columns, equipment and furniture.')
        )
        main_layout.addWidget(self.chk_include_hidden_3d_objects)

        self.chk_automatic_3d_scene = QtGui.QCheckBox(
            i18n.bi("Usar escena 3D automatica", "Use automatic 3D scene")
        )
        self.chk_automatic_3d_scene.setToolTip(
            i18n.bi('Usa la politica completa del Workbench y evita listas antiguas con simbolos 2D o masters.', 'Uses the complete Workbench policy and ignores stale lists containing 2D symbols or masters.')
        )
        main_layout.addWidget(self.chk_automatic_3d_scene)

        actions_layout = QtGui.QHBoxLayout()
        btn_add_selection = QtGui.QPushButton(i18n.bi("Agregar seleccion", "Add selection"))
        btn_add_selection.setToolTip(
            i18n.bi('Usa la seleccion actual del 3D (por ejemplo con Shift+B) y la agrega a A exportar.', 'Use current 3D selection (for example with Shift+B) and add it to To export.')
        )
        btn_add_selection.clicked.connect(self._add_current_selection_to_export)
        btn_refresh = QtGui.QPushButton(i18n.bi("Actualizar lista", "Refresh list"))
        btn_refresh.clicked.connect(self._refresh_available)
        btn_clear = QtGui.QPushButton(i18n.bi("Limpiar seleccion", "Clear selection"))
        btn_clear.clicked.connect(self._clear_export_list)
        btn_diagnose = QtGui.QPushButton(i18n.bi("Diagnosticar exportacion", "Diagnose export"))
        btn_diagnose.clicked.connect(self._diagnose_export_selection)
        actions_layout.addWidget(btn_add_selection)
        actions_layout.addWidget(btn_refresh)
        actions_layout.addWidget(btn_clear)
        actions_layout.addWidget(btn_diagnose)
        actions_layout.addStretch()
        main_layout.addLayout(actions_layout)

        return group

    def _build_global_light_group(self):
        group = QtGui.QGroupBox(i18n.bi("Luz global", "Global light"))
        layout = QtGui.QGridLayout(group)

        self.chk_global_light = QtGui.QCheckBox(i18n.bi("Habilitar", "Enable"))
        self.chk_global_light.setToolTip(
            i18n.bi('Inserta un DirectionalLight que ilumina la escena. Yaw/Pitch definen la direccion.', 'Insert a DirectionalLight for the whole scene. Yaw/Pitch control the direction.')
        )
        layout.addWidget(self.chk_global_light, 0, 0, 1, 3)

        layout.addWidget(QtGui.QLabel("Yaw (deg)"), 1, 0)
        self.spin_gl_yaw = QtGui.QDoubleSpinBox()
        self.spin_gl_yaw.setRange(-180.0, 180.0)
        self.spin_gl_yaw.setSingleStep(1.0)
        layout.addWidget(self.spin_gl_yaw, 1, 1)

        layout.addWidget(QtGui.QLabel("Pitch (deg)"), 2, 0)
        self.spin_gl_pitch = QtGui.QDoubleSpinBox()
        self.spin_gl_pitch.setRange(-90.0, 90.0)
        self.spin_gl_pitch.setSingleStep(1.0)
        layout.addWidget(self.spin_gl_pitch, 2, 1)

        layout.addWidget(QtGui.QLabel(i18n.bi("Intensidad", "Intensity")), 3, 0)
        self.spin_gl_intensity = QtGui.QDoubleSpinBox()
        self.spin_gl_intensity.setRange(0.0, 5.0)
        self.spin_gl_intensity.setSingleStep(0.1)
        layout.addWidget(self.spin_gl_intensity, 3, 1)

        self.btn_gl_color = QtGui.QPushButton(i18n.bi("Color...", "Color..."))
        self.btn_gl_color.setToolTip(
            i18n.bi('Selecciona el color de la luz. Valor sugerido: blanco calido.', 'Choose the light color. Suggested: warm white.')
        )
        self.btn_gl_color.clicked.connect(self._choose_global_color)
        layout.addWidget(self.btn_gl_color, 4, 0)

        self.btn_gl_time = QtGui.QPushButton(i18n.bi("Hora solar...", "Solar time..."))
        self.btn_gl_time.setToolTip(
            i18n.bi('Calcula yaw/pitch aproximados segun latitud y hora.', 'Estimate yaw/pitch from latitude and time.')
        )
        self.btn_gl_time.clicked.connect(self._open_solar_dialog)
        layout.addWidget(self.btn_gl_time, 4, 1)

        self.chk_camera_fill = QtGui.QCheckBox(i18n.bi("Relleno de camara", "Camera fill"))
        self.chk_camera_fill.setToolTip(
            i18n.bi('Agrega una sola luz tenue asociada a la camara para aclarar superficies visibles sin recuperar los circulos de PointLight.', 'Add one low-intensity camera light to brighten visible surfaces without PointLight halos.')
        )
        layout.addWidget(self.chk_camera_fill, 5, 0)

        self.spin_camera_fill_intensity = QtGui.QDoubleSpinBox()
        self.spin_camera_fill_intensity.setRange(0.0, 1.5)
        self.spin_camera_fill_intensity.setDecimals(2)
        self.spin_camera_fill_intensity.setSingleStep(0.05)
        self.spin_camera_fill_intensity.setToolTip(
            i18n.bi('Intensidad recomendada para interiores: 0.45.', 'Recommended interior intensity: 0.45.')
        )
        layout.addWidget(self.spin_camera_fill_intensity, 5, 1)

        self.chk_gl_shadows = QtGui.QCheckBox(i18n.bi("Sombras", "Shadows"))
        self.chk_gl_shadows.setToolTip(
            i18n.bi('Activa sombras X3D para la luz global. Puede bajar el rendimiento.', 'Enable X3D shadows for the global light. May reduce performance.')
        )
        layout.addWidget(self.chk_gl_shadows, 6, 0, 1, 2)

        return group

    def _build_scene_lights_group(self):
        group = QtGui.QGroupBox(i18n.bi("Luces de escena", "Scene lights"))
        layout = QtGui.QVBoxLayout(group)

        self.chk_pointlights = QtGui.QCheckBox(
            i18n.bi("Exportar luces manuales", "Export manual lights")
        )
        self.chk_pointlights.setToolTip(
            i18n.bi('Exporta como luces los objetos marcados manualmente.', 'Exports manually tagged objects as lights.')
        )
        layout.addWidget(self.chk_pointlights)

        self.chk_auto_detect_luminaires = QtGui.QCheckBox(
            i18n.bi("Detectar luminarias 3D automaticamente", "Auto-detect 3D luminaires")
        )
        self.chk_auto_detect_luminaires.setToolTip(
            i18n.bi('Crea una luz por cada App::Link de luminaria con solido 3D. Ignora simbolos 2D.', 'Creates one light per 3D luminaire App::Link. Ignores 2D symbols.')
        )
        layout.addWidget(self.chk_auto_detect_luminaires)

        mode_row = QtGui.QHBoxLayout()
        mode_row.addWidget(QtGui.QLabel(i18n.bi("Algoritmo de luz", "Light algorithm")))
        self.combo_local_light_mode = QtGui.QComboBox()
        self.combo_local_light_mode.addItem(
            i18n.bi("SpotLight sin sombras (recomendado)", "SpotLight without shadows (recommended)"),
            exporter_x3d.LIGHT_MODE_SPOT_NO_SHADOWS,
        )
        self.combo_local_light_mode.addItem(
            i18n.bi("SpotLight + sombras limitadas (experimental)", "SpotLight + limited shadows (experimental)"),
            exporter_x3d.LIGHT_MODE_SPOT_SHADOW_MAP,
        )
        self.combo_local_light_mode.addItem(
            i18n.bi("PointLight clasico (respaldo)", "Classic PointLight (fallback)"),
            exporter_x3d.LIGHT_MODE_POINT_CLASSIC,
        )
        self.combo_local_light_mode.addItem(
            i18n.bi("Fotometrico experimental (lm/cd)", "Experimental photometric (lm/cd)"),
            exporter_x3d.LIGHT_MODE_PHOTOMETRIC,
        )
        self.combo_local_light_mode.setToolTip(
            i18n.bi('SpotLight dirige cada luminaria hacia abajo. El modo recomendado evita mapas de sombra masivos; el modo experimental los limita. PointLight clasico conserva el algoritmo anterior.', 'SpotLight aims each fixture downward. Recommended mode avoids massive shadow maps; experimental mode limits them. Classic PointLight preserves the previous algorithm. Photometric mode converts lm to cd, uses the beam angle and inverse-square falloff.')
        )
        self.combo_local_light_mode.currentIndexChanged.connect(
            self._on_local_light_mode_changed
        )
        mode_row.addWidget(self.combo_local_light_mode, stretch=1)
        layout.addLayout(mode_row)

        render_row = QtGui.QHBoxLayout()
        self.chk_pointlight_shadows = QtGui.QCheckBox(
            i18n.bi("Sombras limitadas", "Limited shadows")
        )
        self.chk_pointlight_shadows.setToolTip(
            i18n.bi('Solo para PointLight clasico. Activa sombras volumetricas en pocas luces.', 'Classic PointLight only. Enables volume shadows on a few lights.')
        )
        render_row.addWidget(self.chk_pointlight_shadows)

        render_row.addWidget(QtGui.QLabel(i18n.bi("Max sombras", "Max shadows")))
        self.spin_max_shadow_lights = QtGui.QSpinBox()
        self.spin_max_shadow_lights.setRange(0, 4)
        self.spin_max_shadow_lights.setValue(2)
        render_row.addWidget(self.spin_max_shadow_lights)

        render_row.addWidget(QtGui.QLabel(i18n.bi("Atenuacion", "Falloff")))
        self.combo_pointlight_falloff = QtGui.QComboBox()
        self.combo_pointlight_falloff.addItems(["Interior", "Soft", "Constant"])
        render_row.addWidget(self.combo_pointlight_falloff)
        render_row.addStretch()
        layout.addLayout(render_row)

        btn_row = QtGui.QHBoxLayout()
        self.btn_add_light = QtGui.QPushButton(i18n.bi("Agregar seleccion como luz", "Add selection as light"))
        self.btn_add_light.setToolTip(
            i18n.bi('Marca los objetos seleccionados como luminarias.', 'Mark selected objects as light sources.')
        )
        self.btn_add_light.clicked.connect(self._add_lights_from_selection)
        self.btn_remove_light = QtGui.QPushButton(i18n.bi("Quitar seleccion como luz", "Remove selection as light"))
        self.btn_remove_light.setToolTip(
            i18n.bi('Elimina el marcado de luminaria para los items seleccionados en la lista.', 'Remove light flag for the selected items in the list.')
        )
        self.btn_remove_light.clicked.connect(self._remove_lights_from_list)
        btn_row.addWidget(self.btn_add_light)
        btn_row.addWidget(self.btn_remove_light)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.list_lights = QtGui.QListWidget()
        self.list_lights.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        self.list_lights.setAlternatingRowColors(True)
        layout.addWidget(self.list_lights)
        self.list_lights.itemSelectionChanged.connect(self._on_lights_selection_changed)

        controls = QtGui.QHBoxLayout()
        controls.addWidget(QtGui.QLabel(i18n.bi("Intensidad", "Intensity")))
        self.spin_light_intensity = QtGui.QDoubleSpinBox()
        self.spin_light_intensity.setRange(0.0, 5.0)
        self.spin_light_intensity.setSingleStep(0.1)
        controls.addWidget(self.spin_light_intensity)

        controls.addWidget(QtGui.QLabel(i18n.bi("Radio (m)", "Radius (m)")))
        self.spin_light_radius = QtGui.QDoubleSpinBox()
        self.spin_light_radius.setRange(0.1, 200.0)
        self.spin_light_radius.setSingleStep(0.5)
        controls.addWidget(self.spin_light_radius)

        self.btn_light_color = QtGui.QPushButton(i18n.bi("Color luz...", "Light color..."))
        self.btn_light_color.clicked.connect(self._choose_light_color)
        controls.addWidget(self.btn_light_color)

        self.btn_apply_light_props = QtGui.QPushButton(i18n.bi("Aplicar a seleccion", "Apply to selection"))
        self.btn_apply_light_props.clicked.connect(self._apply_light_properties)
        controls.addWidget(self.btn_apply_light_props)
        controls.addStretch()

        layout.addLayout(controls)

        photo_controls = QtGui.QHBoxLayout()
        photo_controls.addWidget(QtGui.QLabel(i18n.bi("Flujo (lm)", "Flux (lm)")))
        self.spin_light_lumens = QtGui.QDoubleSpinBox()
        self.spin_light_lumens.setRange(0.0, 200000.0)
        self.spin_light_lumens.setDecimals(0)
        self.spin_light_lumens.setSingleStep(100.0)
        self.spin_light_lumens.setValue(exporter_x3d.DEFAULT_PHOTOMETRIC_LUMENS)
        photo_controls.addWidget(self.spin_light_lumens)

        photo_controls.addWidget(QtGui.QLabel(i18n.bi("Haz (°)", "Beam (deg)")))
        self.spin_light_beam_angle = QtGui.QDoubleSpinBox()
        self.spin_light_beam_angle.setRange(1.0, 179.0)
        self.spin_light_beam_angle.setDecimals(1)
        self.spin_light_beam_angle.setSingleStep(5.0)
        self.spin_light_beam_angle.setValue(exporter_x3d.DEFAULT_PHOTOMETRIC_BEAM_ANGLE_DEG)
        photo_controls.addWidget(self.spin_light_beam_angle)

        photo_controls.addWidget(QtGui.QLabel(i18n.bi("Intensidad (cd)", "Intensity (cd)")))
        self.line_light_candela = QtGui.QLineEdit()
        self.line_light_candela.setReadOnly(True)
        self.line_light_candela.setMaximumWidth(110)
        photo_controls.addWidget(self.line_light_candela)

        photo_controls.addWidget(QtGui.QLabel("CCT (K)"))
        self.spin_light_cct = QtGui.QDoubleSpinBox()
        self.spin_light_cct.setRange(1800.0, 10000.0)
        self.spin_light_cct.setDecimals(0)
        self.spin_light_cct.setSingleStep(100.0)
        self.spin_light_cct.setValue(exporter_x3d.DEFAULT_PHOTOMETRIC_CCT_K)
        photo_controls.addWidget(self.spin_light_cct)
        photo_controls.addStretch()
        layout.addLayout(photo_controls)
        self.spin_light_lumens.valueChanged.connect(self._update_photometric_candela)
        self.spin_light_beam_angle.valueChanged.connect(self._update_photometric_candela)

        self.btn_apply_light_props.setEnabled(False)
        self._update_light_color_button()
        self._update_photometric_candela()
        self._on_local_light_mode_changed()

        return group

    def _build_output_group(self):
        group = QtGui.QGroupBox(i18n.bi("Salida", "Output"))
        grid = QtGui.QGridLayout(group)

        grid.addWidget(QtGui.QLabel(i18n.bi("Carpeta", "Folder")), 0, 0)
        self.output_dir_line = QtGui.QLineEdit()
        self.output_dir_line.setPlaceholderText(
            i18n.bi("Carpeta del documento; si no existe, use Examinar", "Document folder; otherwise use Browse")
        )
        grid.addWidget(self.output_dir_line, 0, 1)
        btn_browse_dir = QtGui.QPushButton(i18n.bi("Examinar", "Browse"))
        btn_browse_dir.clicked.connect(self._browse_output_dir)
        grid.addWidget(btn_browse_dir, 0, 2)

        grid.addWidget(QtGui.QLabel(i18n.bi("Nombre base", "Base name")), 1, 0)
        self.base_name_line = QtGui.QLineEdit()
        grid.addWidget(self.base_name_line, 1, 1)

        grid.addWidget(QtGui.QLabel(i18n.bi("Algoritmo X3D", "X3D algorithm")), 2, 0)
        self.combo_geometry_export_mode = QtGui.QComboBox()
        self.combo_geometry_export_mode.addItem(
            i18n.bi("Optimizado - reutilizar enlaces", "Optimized - reuse links"),
            "Optimized",
        )
        self.combo_geometry_export_mode.addItem(
            i18n.bi("Clasico - compatibilidad", "Classic - compatibility"),
            "Classic",
        )
        self.combo_geometry_export_mode.setToolTip(
            i18n.bi('Optimizado reutiliza geometria identica mediante DEF/USE. Clasico conserva el algoritmo anterior como respaldo.', 'Optimized reuses identical geometry with DEF/USE. Classic preserves the previous algorithm as a fallback.')
        )
        grid.addWidget(self.combo_geometry_export_mode, 2, 1, 1, 2)

        self.launch_checkbox = QtGui.QCheckBox(i18n.bi("Lanzar Castle Engine al exportar", "Launch Castle Engine after export"))
        grid.addWidget(self.launch_checkbox, 3, 0, 1, 3)

        self.btn_web_preview = QtGui.QPushButton(i18n.bi("Vista previa Web", "Web preview"))
        self.btn_web_preview.setToolTip(
            i18n.bi('Exporta X3D, genera index.html y abre el navegador predeterminado.', 'Exports X3D, generates index.html and opens the default browser.')
        )
        self.btn_web_preview.clicked.connect(self._export_web_preview)
        grid.addWidget(self.btn_web_preview, 4, 0, 1, 3)

        return group

    def _build_lighting_tab(self):
        tab = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(tab)
        layout.addWidget(self._build_lighting_profile_group())
        layout.addWidget(self._build_global_light_group())
        layout.addWidget(self._build_scene_lights_group())
        layout.addWidget(self._build_materials_group())
        layout.addStretch()
        return tab

    def _build_lighting_profile_group(self):
        group = QtGui.QGroupBox(i18n.bi("Perfil", "Profile"))
        layout = QtGui.QGridLayout(group)
        self.combo_lighting_profile = QtGui.QComboBox()
        self._refresh_lighting_profile_combo()
        self.combo_lighting_profile.setToolTip(
            i18n.bi('Los perfiles cambian conjuntamente luces, relleno de camara y materiales. Fotometrico realista conserva la medicion en lm/cd; Fotometrico visible agrega una compensacion material suave para Castle.', 'Profiles jointly configure lights, camera fill and materials.')
        )
        layout.addWidget(self.combo_lighting_profile, 0, 0, 1, 3)

        self.btn_apply_lighting_profile = QtGui.QPushButton(i18n.bi("Aplicar", "Apply"))
        icon_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "resources",
                "icons",
                "add_light_properties.svg",
            )
        )
        self.btn_apply_lighting_profile.setIcon(QtGui.QIcon(icon_path))
        self.btn_apply_lighting_profile.clicked.connect(self._apply_selected_lighting_profile)
        layout.addWidget(self.btn_apply_lighting_profile, 1, 0)

        self.btn_save_lighting_profile = QtGui.QPushButton(i18n.bi("Guardar actual...", "Save current..."))
        self.btn_save_lighting_profile.clicked.connect(self._save_current_lighting_profile)
        layout.addWidget(self.btn_save_lighting_profile, 1, 1)

        self.btn_delete_lighting_profile = QtGui.QPushButton(i18n.bi("Eliminar", "Delete"))
        self.btn_delete_lighting_profile.clicked.connect(self._delete_selected_lighting_profile)
        layout.addWidget(self.btn_delete_lighting_profile, 1, 2)
        return group

    def _refresh_lighting_profile_combo(self, selected_name: str = "") -> None:
        combo = self.combo_lighting_profile
        current = selected_name or str(getattr(self, "active_lighting_profile", "") or "")
        combo.blockSignals(True)
        combo.clear()
        for name in lighting_profiles.builtin_profile_names():
            combo.addItem(name, "builtin")
        if self.custom_lighting_profiles:
            combo.insertSeparator(combo.count())
            for name in sorted(self.custom_lighting_profiles, key=str.casefold):
                combo.addItem(name, "custom")
        index = combo.findText(current)
        if index < 0:
            index = combo.findText(lighting_profiles.DEFAULT_PROFILE_NAME)
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)

    def _selected_lighting_profile_name(self) -> str:
        return str(self.combo_lighting_profile.currentText() or "").strip()

    def _lighting_profile_data(self, name: str):
        builtin = lighting_profiles.get_builtin_profile(name)
        if builtin is not None:
            return builtin
        custom = self.custom_lighting_profiles.get(str(name or ""))
        return lighting_profiles.normalize_profile(custom) if custom is not None else None

    def _apply_selected_lighting_profile(self) -> None:
        self._apply_lighting_profile(self._selected_lighting_profile_name(), log=True)

    def _apply_lighting_profile(self, name: str, log: bool = False) -> bool:
        profile = self._lighting_profile_data(name)
        if not isinstance(profile, dict):
            self.status_label.setText("Perfil de iluminacion no encontrado.")
            return False

        scene = profile.get("scene", {})
        global_cfg = profile.get("global", {})
        navigation = profile.get("navigation", {})
        local = profile.get("local", {})
        materials = profile.get("materials", {})

        self.chk_automatic_3d_scene.setChecked(bool(scene.get("automatic_3d_scene", True)))
        self.chk_include_hidden_3d_objects.setChecked(
            bool(scene.get("include_hidden_3d_objects", True))
        )
        self.chk_global_light.setChecked(bool(global_cfg.get("enabled", False)))
        self.spin_gl_yaw.setValue(float(global_cfg.get("yaw", -30.0)))
        self.spin_gl_pitch.setValue(float(global_cfg.get("pitch", -45.0)))
        self.spin_gl_intensity.setValue(float(global_cfg.get("intensity", 0.0)))
        self.global_light_color = self._color_from_config_value(
            global_cfg.get("color", [1.0, 0.95, 0.85])
        )
        self._update_global_color_button()
        self.chk_gl_shadows.setChecked(bool(global_cfg.get("shadows", False)))

        self.chk_camera_fill.setChecked(bool(navigation.get("camera_fill_enabled", False)))
        self.spin_camera_fill_intensity.setValue(
            float(navigation.get("camera_fill_intensity", 0.0))
        )

        self.chk_pointlights.setChecked(bool(local.get("manual_lights", False)))
        self.chk_auto_detect_luminaires.setChecked(
            bool(local.get("auto_detect_luminaires", True))
        )
        self._set_local_light_mode(
            str(local.get("light_mode", exporter_x3d.LIGHT_MODE_SPOT_NO_SHADOWS))
        )
        self.chk_pointlight_shadows.setChecked(bool(local.get("shadows", False)))
        self.spin_max_shadow_lights.setValue(
            max(0, min(4, int(local.get("max_shadow_lights", 0) or 0)))
        )
        self._set_point_light_falloff_mode(str(local.get("falloff", "Interior")))
        self.spin_light_lumens.setValue(
            float(local.get("lumens", exporter_x3d.DEFAULT_PHOTOMETRIC_LUMENS))
        )
        self.spin_light_beam_angle.setValue(
            float(local.get("beam_angle_deg", exporter_x3d.DEFAULT_PHOTOMETRIC_BEAM_ANGLE_DEG))
        )
        self.spin_light_cct.setValue(
            float(local.get("cct_kelvin", exporter_x3d.DEFAULT_PHOTOMETRIC_CCT_K))
        )
        self.chk_improve_interior_lighting.setChecked(bool(materials.get("enabled", False)))
        self._set_material_lighting_mode(str(materials.get("mode", "None")))

        self.active_lighting_profile = str(name)
        self._refresh_lighting_profile_combo(self.active_lighting_profile)
        if isinstance(self.sidecar_data, dict):
            self.sidecar_data["lighting_profile_name"] = self.active_lighting_profile
        self.status_label.setText("Perfil aplicado: " + self.active_lighting_profile)
        if log:
            FreeCAD.Console.PrintMessage(
                "[GAMEEXPORT] Lighting profile applied: "
                + self.active_lighting_profile
                + ", light_mode="
                + self._local_light_mode()
                + ", materials="
                + self._material_lighting_mode()
                + "\n"
            )
        return True

    def _capture_lighting_profile(self) -> dict:
        return lighting_profiles.normalize_profile(
            {
                "scene": {
                    "automatic_3d_scene": bool(self.chk_automatic_3d_scene.isChecked()),
                    "include_hidden_3d_objects": bool(
                        self.chk_include_hidden_3d_objects.isChecked()
                    ),
                },
                "global": {
                    "enabled": bool(self.chk_global_light.isChecked()),
                    "yaw": float(self.spin_gl_yaw.value()),
                    "pitch": float(self.spin_gl_pitch.value()),
                    "intensity": float(self.spin_gl_intensity.value()),
                    "color": [float(value) for value in self.global_light_color],
                    "shadows": bool(self.chk_gl_shadows.isChecked()),
                },
                "navigation": {
                    "camera_fill_enabled": bool(self.chk_camera_fill.isChecked()),
                    "camera_fill_intensity": float(self.spin_camera_fill_intensity.value()),
                },
                "local": {
                    "manual_lights": bool(self.chk_pointlights.isChecked()),
                    "auto_detect_luminaires": bool(
                        self.chk_auto_detect_luminaires.isChecked()
                    ),
                    "light_mode": self._local_light_mode(),
                    "shadows": bool(self.chk_pointlight_shadows.isChecked()),
                    "max_shadow_lights": int(self.spin_max_shadow_lights.value()),
                    "falloff": self._point_light_falloff_mode(),
                    "lumens": float(self.spin_light_lumens.value()),
                    "beam_angle_deg": float(self.spin_light_beam_angle.value()),
                    "cct_kelvin": float(self.spin_light_cct.value()),
                },
                "materials": {
                    "enabled": bool(self.chk_improve_interior_lighting.isChecked()),
                    "mode": self._material_lighting_mode(),
                },
            }
        )

    def _save_current_lighting_profile(self) -> None:
        default_name = self._selected_lighting_profile_name()
        if default_name in lighting_profiles.BUILTIN_PROFILES:
            default_name = "Mi perfil"
        name, accepted = QtGui.QInputDialog.getText(
            self.widget,
            "Guardar perfil de iluminacion",
            "Nombre del perfil:",
            text=default_name,
        )
        if not accepted:
            return
        clean_name = lighting_profiles.clean_profile_name(name)
        if not clean_name:
            self.status_label.setText("Escriba un nombre para el perfil.")
            return
        if clean_name in lighting_profiles.BUILTIN_PROFILES:
            self.status_label.setText("Los perfiles incluidos no se pueden reemplazar.")
            return
        self.custom_lighting_profiles[clean_name] = self._capture_lighting_profile()
        self.params.SetString(
            lighting_profiles.CUSTOM_PROFILES_PARAM,
            lighting_profiles.dumps_custom_profiles(self.custom_lighting_profiles),
        )
        self.active_lighting_profile = clean_name
        self._refresh_lighting_profile_combo(clean_name)
        self.status_label.setText("Perfil guardado: " + clean_name)

    def _delete_selected_lighting_profile(self) -> None:
        name = self._selected_lighting_profile_name()
        if name in lighting_profiles.BUILTIN_PROFILES:
            self.status_label.setText("Los perfiles incluidos no se pueden eliminar.")
            return
        if name not in self.custom_lighting_profiles:
            self.status_label.setText("Seleccione un perfil guardado por el usuario.")
            return
        del self.custom_lighting_profiles[name]
        self.params.SetString(
            lighting_profiles.CUSTOM_PROFILES_PARAM,
            lighting_profiles.dumps_custom_profiles(self.custom_lighting_profiles),
        )
        self.active_lighting_profile = lighting_profiles.DEFAULT_PROFILE_NAME
        self._refresh_lighting_profile_combo(self.active_lighting_profile)
        self.status_label.setText("Perfil eliminado: " + name)

    def _build_materials_group(self):
        group = QtGui.QGroupBox(i18n.bi("Materiales X3D", "X3D Materials"))
        grid = QtGui.QGridLayout(group)

        self.chk_improve_interior_lighting = QtGui.QCheckBox(
            i18n.bi("Mejorar iluminacion interior", "Improve interior lighting")
        )
        grid.addWidget(self.chk_improve_interior_lighting, 0, 0, 1, 2)

        grid.addWidget(QtGui.QLabel(i18n.bi("Modo", "Mode")), 1, 0)
        self.combo_interior_lighting_mode = QtGui.QComboBox()
        self.combo_interior_lighting_mode.addItems(["None", "Soft", "Architectural", "Bright"])
        self.chk_improve_interior_lighting.toggled.connect(self._on_improve_interior_lighting_toggled)
        self.combo_interior_lighting_mode.currentIndexChanged.connect(self._on_material_lighting_mode_changed)
        grid.addWidget(self.combo_interior_lighting_mode, 1, 1)

        return group

    def _build_textures_tab(self):
        tab = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(tab)
        layout.addWidget(self._build_object_material_group())

        # Keep the former ground-only controls alive for compatibility with
        # existing preferences/sidecars, but remove them from the normal user
        # workflow. New assignments persist on the selected FreeCAD objects.
        legacy_group = self._build_ground_texture_group()
        legacy_group.setVisible(False)
        layout.addWidget(legacy_group)
        layout.addStretch()
        return tab

    def _build_object_material_group(self):
        group = QtGui.QGroupBox(i18n.bi("Materiales, texturas y reflejos", "Materials, textures and reflections"))
        grid = QtGui.QGridLayout(group)

        intro = QtGui.QLabel(
            i18n.bi(
                "Seleccione uno o varios objetos de FreeCAD, tome la seleccion y asigne un acabado persistente para futuras exportaciones X3D.",
                "Select one or more FreeCAD objects, capture the selection, and assign a persistent finish for future X3D exports.",
            )
        )
        intro.setWordWrap(True)
        grid.addWidget(intro, 0, 0, 1, 4)

        grid.addWidget(QtGui.QLabel(i18n.bi("Objetos", "Objects")), 1, 0)
        self.material_objects_line = QtGui.QLineEdit()
        self.material_objects_line.setReadOnly(True)
        grid.addWidget(self.material_objects_line, 1, 1, 1, 2)
        btn_selection = QtGui.QPushButton(i18n.bi("Tomar seleccion", "Use selection"))
        btn_selection.clicked.connect(self._use_selection_as_material_objects)
        grid.addWidget(btn_selection, 1, 3)

        grid.addWidget(QtGui.QLabel(i18n.bi("Acabado", "Finish")), 2, 0)
        self.combo_material_mode = QtGui.QComboBox()
        self.combo_material_mode.addItem(i18n.bi("Textura", "Texture"), material_assignments.MODE_TEXTURE)
        self.combo_material_mode.addItem(i18n.bi("Pulido / reflectante", "Polished / reflective"), material_assignments.MODE_POLISHED)
        self.combo_material_mode.addItem(i18n.bi("Espejo real", "True mirror"), material_assignments.MODE_MIRROR)
        self.combo_material_mode.currentIndexChanged.connect(self._on_object_material_mode_changed)
        grid.addWidget(self.combo_material_mode, 2, 1)

        grid.addWidget(QtGui.QLabel(i18n.bi("Textura", "Texture")), 2, 2)
        self.combo_material_texture = QtGui.QComboBox()
        texture_order = [
            material_assignments.TEXTURE_NONE,
            material_assignments.TEXTURE_CERAMIC,
            material_assignments.TEXTURE_WOOD,
            material_assignments.TEXTURE_CONCRETE,
            material_assignments.TEXTURE_STONE,
            material_assignments.TEXTURE_BRICK,
            material_assignments.TEXTURE_CEILING,
            material_assignments.TEXTURE_METAL,
            material_assignments.TEXTURE_CUSTOM,
        ]
        spanish = i18n.current_language() == "es"
        for texture_id in texture_order:
            meta = material_assignments.BUILTIN_TEXTURES[texture_id]
            label = meta["label_es"] if spanish else meta["label_en"]
            self.combo_material_texture.addItem(str(label), texture_id)
        self.combo_material_texture.currentIndexChanged.connect(self._on_object_texture_preset_changed)
        grid.addWidget(self.combo_material_texture, 2, 3)

        grid.addWidget(QtGui.QLabel(i18n.bi("Archivo personalizado", "Custom file")), 3, 0)
        self.material_texture_line = QtGui.QLineEdit()
        grid.addWidget(self.material_texture_line, 3, 1, 1, 2)
        self.btn_material_texture_browse = QtGui.QPushButton(i18n.bi("Examinar", "Browse"))
        self.btn_material_texture_browse.clicked.connect(self._browse_object_texture)
        grid.addWidget(self.btn_material_texture_browse, 3, 3)

        grid.addWidget(QtGui.QLabel(i18n.bi("Proyeccion UV", "UV projection")), 4, 0)
        self.combo_material_projection = QtGui.QComboBox()
        self.combo_material_projection.addItem(i18n.bi("Automatica", "Automatic"), material_assignments.PROJECTION_AUTO)
        self.combo_material_projection.addItem("XY", material_assignments.PROJECTION_XY)
        self.combo_material_projection.addItem("XZ", material_assignments.PROJECTION_XZ)
        self.combo_material_projection.addItem("YZ", material_assignments.PROJECTION_YZ)
        grid.addWidget(self.combo_material_projection, 4, 1)

        grid.addWidget(QtGui.QLabel(i18n.bi("Tamano U mm", "U tile mm")), 4, 2)
        self.spin_material_tile_u = QtGui.QDoubleSpinBox()
        self.spin_material_tile_u.setRange(1.0, 100000.0)
        self.spin_material_tile_u.setDecimals(1)
        self.spin_material_tile_u.setValue(600.0)
        grid.addWidget(self.spin_material_tile_u, 4, 3)

        grid.addWidget(QtGui.QLabel(i18n.bi("Tamano V mm", "V tile mm")), 5, 0)
        self.spin_material_tile_v = QtGui.QDoubleSpinBox()
        self.spin_material_tile_v.setRange(1.0, 100000.0)
        self.spin_material_tile_v.setDecimals(1)
        self.spin_material_tile_v.setValue(600.0)
        grid.addWidget(self.spin_material_tile_v, 5, 1)

        grid.addWidget(QtGui.QLabel(i18n.bi("Reflectividad", "Reflectivity")), 5, 2)
        self.spin_material_reflectivity = QtGui.QDoubleSpinBox()
        self.spin_material_reflectivity.setRange(0.0, 1.0)
        self.spin_material_reflectivity.setDecimals(2)
        self.spin_material_reflectivity.setSingleStep(0.05)
        self.spin_material_reflectivity.setValue(0.35)
        self.spin_material_reflectivity.setToolTip(
            i18n.bi(
                "Controla brillo y reflejo especular del acabado pulido. El espejo usa reflexion dinamica de Castle.",
                "Controls specular brightness of polished finishes. Mirror uses Castle dynamic reflection.",
            )
        )
        grid.addWidget(self.spin_material_reflectivity, 5, 3)

        grid.addWidget(QtGui.QLabel(i18n.bi("Resolucion espejo", "Mirror resolution")), 6, 0)
        self.combo_mirror_size = QtGui.QComboBox()
        for size in (256, 512, 1024, 2048):
            self.combo_mirror_size.addItem(str(size), size)
        self._set_combo_data(self.combo_mirror_size, 512)
        grid.addWidget(self.combo_mirror_size, 6, 1)

        btn_apply = QtGui.QPushButton(i18n.bi("Asignar a objetos", "Assign to objects"))
        btn_apply.clicked.connect(self._apply_object_material_assignment)
        grid.addWidget(btn_apply, 6, 2)
        btn_clear = QtGui.QPushButton(i18n.bi("Quitar acabado", "Clear finish"))
        btn_clear.clicked.connect(self._clear_object_material_assignment)
        grid.addWidget(btn_clear, 6, 3)

        status_group = QtGui.QGroupBox(i18n.bi("Estado del material", "Material status"))
        status_layout = QtGui.QVBoxLayout(status_group)
        self.object_material_status_box = QtGui.QTextEdit()
        self.object_material_status_box.setReadOnly(True)
        self.object_material_status_box.setAcceptRichText(False)
        self.object_material_status_box.setMinimumHeight(128)
        self.object_material_status_box.setToolTip(
            i18n.bi(
                "Muestra el acabado persistente guardado en los objetos seleccionados. Use Tomar seleccion para releer el estado actual del modelo.",
                "Shows the persistent finish stored on the selected objects. Use Use selection to reread the current model state.",
            )
        )
        status_layout.addWidget(self.object_material_status_box)
        # Compatibility alias: existing validation paths still call setText().
        self.object_material_status_label = self.object_material_status_box
        grid.addWidget(status_group, 7, 0, 1, 4)

        self._set_combo_data(self.combo_material_texture, material_assignments.TEXTURE_CERAMIC)
        self._on_object_texture_preset_changed()
        self._on_object_material_mode_changed()
        self._refresh_object_material_status()
        return group

    @staticmethod
    def _combo_data(combo):
        try:
            return combo.currentData()
        except Exception:
            return combo.itemData(combo.currentIndex())

    @staticmethod
    def _set_combo_data(combo, value) -> None:
        for index in range(combo.count()):
            try:
                data = combo.itemData(index)
            except Exception:
                data = None
            if str(data) == str(value):
                combo.setCurrentIndex(index)
                return

    def _use_selection_as_material_objects(self):
        selection = [obj for obj in FreeCADGui.Selection.getSelection() if obj is not None]
        if not selection:
            self.material_object_names = []
            self.material_objects_line.clear()
            self.object_material_status_label.setText(
                i18n.bi("Seleccione uno o varios objetos en FreeCAD.", "Select one or more objects in FreeCAD.")
            )
            return
        self.material_object_names = []
        labels = []
        seen = set()
        for obj in selection:
            name = str(getattr(obj, "Name", "") or "")
            if not name or name in seen:
                continue
            seen.add(name)
            self.material_object_names.append(name)
            labels.append(str(getattr(obj, "Label", "") or name))
        self.material_objects_line.setText(", ".join(labels))
        if len(selection) == 1:
            self._load_object_material_assignment(selection[0])
        self._refresh_object_material_status()

    def _material_mode_label(self, mode: object) -> str:
        value = str(mode or material_assignments.MODE_TEXTURE)
        labels = {
            material_assignments.MODE_TEXTURE: i18n.bi("Textura", "Texture"),
            material_assignments.MODE_POLISHED: i18n.bi("Pulido / reflectante", "Polished / reflective"),
            material_assignments.MODE_MIRROR: i18n.bi("Espejo real", "True mirror"),
        }
        return labels.get(value, value)

    def _material_texture_label(self, texture_id: object, texture_path: object = "") -> str:
        texture_key = str(texture_id or material_assignments.TEXTURE_NONE)
        if texture_key == material_assignments.TEXTURE_CUSTOM:
            path = str(texture_path or "").strip()
            return os.path.basename(path) if path else i18n.bi("Archivo personalizado", "Custom file")
        meta = material_assignments.BUILTIN_TEXTURES.get(texture_key, {})
        if meta:
            key = "label_es" if i18n.current_language() == "es" else "label_en"
            return str(meta.get(key, texture_key))
        return texture_key

    def _material_persisted_state(self, cfg: dict) -> str:
        if not bool(cfg.get("enabled", False)):
            return i18n.bi("- Sin material GameEngineExport", "- No GameEngineExport material")
        mode = str(cfg.get("mode", material_assignments.MODE_TEXTURE))
        if mode == material_assignments.MODE_MIRROR:
            return i18n.bi("OK - Espejo configurado", "OK - Mirror configured")
        texture_id = str(cfg.get("texture_id", material_assignments.TEXTURE_NONE))
        texture_path = str(cfg.get("texture_path", "") or "")
        if mode == material_assignments.MODE_TEXTURE:
            if texture_id == material_assignments.TEXTURE_NONE:
                return i18n.bi("ADVERTENCIA - Configurado sin textura", "WARNING - Configured without texture")
            if texture_id == material_assignments.TEXTURE_CUSTOM and not texture_path:
                return i18n.bi("ADVERTENCIA - Falta archivo de textura", "WARNING - Texture file missing")
            return i18n.bi("OK - Texturizado", "OK - Textured")
        if mode == material_assignments.MODE_POLISHED:
            return i18n.bi("OK - Pulido / reflectante", "OK - Polished / reflective")
        return i18n.bi("OK - Configurado", "OK - Configured")

    def _refresh_object_material_status(self, message: str = "") -> None:
        if not hasattr(self, "object_material_status_box"):
            return
        doc = FreeCAD.ActiveDocument
        names = list(getattr(self, "material_object_names", []) or [])
        if doc is None:
            self.object_material_status_box.setPlainText(i18n.bi("No hay documento activo.", "No active document."))
            return
        if not names:
            self.object_material_status_box.setPlainText(
                i18n.bi(
                    "Sin objetos capturados. Seleccione uno o varios objetos en FreeCAD y pulse Tomar seleccion.",
                    "No captured objects. Select one or more FreeCAD objects and press Use selection.",
                )
            )
            return
        objects = []
        for name in names:
            obj = doc.getObject(name)
            if obj is not None:
                objects.append(obj)
        lines = []
        if message:
            lines.extend([str(message), ""])
        if not objects:
            lines.append(i18n.bi("Los objetos capturados ya no existen en el documento.", "The captured objects no longer exist in the document."))
            self.object_material_status_box.setPlainText("\n".join(lines))
            return
        if len(objects) == 1:
            obj = objects[0]
            cfg = material_assignments.read_object_assignment(obj)
            label = str(getattr(obj, "Label", "") or getattr(obj, "Name", ""))
            name = str(getattr(obj, "Name", "") or "")
            lines.append(i18n.bi(f"Objeto: {label} ({name})", f"Object: {label} ({name})"))
            lines.append(i18n.bi("Estado: ", "Status: ") + self._material_persisted_state(cfg))
            if bool(cfg.get("enabled", False)):
                mode = str(cfg.get("mode", material_assignments.MODE_TEXTURE))
                lines.append(i18n.bi("Acabado: ", "Finish: ") + self._material_mode_label(mode))
                if mode != material_assignments.MODE_MIRROR:
                    lines.append(i18n.bi("Textura: ", "Texture: ") + self._material_texture_label(cfg.get("texture_id"), cfg.get("texture_path")))
                    lines.append(i18n.bi("Proyeccion: ", "Projection: ") + str(cfg.get("projection", "Auto")))
                    lines.append(i18n.bi("Escala: ", "Scale: ") + f"{float(cfg.get('tile_u_mm', 0.0)):.0f} x {float(cfg.get('tile_v_mm', 0.0)):.0f} mm")
                if mode == material_assignments.MODE_POLISHED:
                    lines.append(i18n.bi("Reflectividad: ", "Reflectivity: ") + f"{float(cfg.get('reflectivity', 0.0)):.2f}")
                if mode == material_assignments.MODE_MIRROR:
                    lines.append(i18n.bi("Resolucion espejo: ", "Mirror resolution: ") + str(int(cfg.get("mirror_size", 512))))
        else:
            lines.append(i18n.bi(f"{len(objects)} objetos capturados:", f"{len(objects)} captured objects:"))
            for obj in objects:
                cfg = material_assignments.read_object_assignment(obj)
                label = str(getattr(obj, "Label", "") or getattr(obj, "Name", ""))
                if not bool(cfg.get("enabled", False)):
                    lines.append(f"- {label}: " + i18n.bi("Sin material", "No material"))
                    continue
                mode = str(cfg.get("mode", material_assignments.MODE_TEXTURE))
                if mode == material_assignments.MODE_MIRROR:
                    detail = self._material_mode_label(mode)
                else:
                    detail = self._material_mode_label(mode) + " - " + self._material_texture_label(cfg.get("texture_id"), cfg.get("texture_path"))
                lines.append(f"OK {label}: {detail}")
        self.object_material_status_box.setPlainText("\n".join(lines))

    def _load_object_material_assignment(self, obj) -> None:
        cfg = material_assignments.read_object_assignment(obj)
        if not bool(cfg.get("enabled", False)):
            return
        self._set_combo_data(self.combo_material_mode, cfg.get("mode"))
        self._set_combo_data(self.combo_material_texture, cfg.get("texture_id"))
        self.material_texture_line.setText(str(cfg.get("texture_path", "") or ""))
        self._set_combo_data(self.combo_material_projection, cfg.get("projection"))
        self.spin_material_tile_u.setValue(float(cfg.get("tile_u_mm", 600.0)))
        self.spin_material_tile_v.setValue(float(cfg.get("tile_v_mm", 600.0)))
        self.spin_material_reflectivity.setValue(float(cfg.get("reflectivity", 0.35)))
        self._set_combo_data(self.combo_mirror_size, int(cfg.get("mirror_size", 512)))
        self._on_object_material_mode_changed()
        self._on_object_texture_preset_changed(update_tile=False)

    def _ensure_object_material_properties(self, obj) -> None:
        specs = [
            ("App::PropertyBool", material_assignments.PROP_ENABLED, False, "Enable GameEngineExport material override"),
            ("App::PropertyString", material_assignments.PROP_MODE, material_assignments.MODE_TEXTURE, "Texture, polished or mirror finish"),
            ("App::PropertyString", material_assignments.PROP_TEXTURE_ID, material_assignments.TEXTURE_NONE, "Bundled texture identifier"),
            ("App::PropertyString", material_assignments.PROP_TEXTURE_PATH, "", "Custom texture file path"),
            ("App::PropertyString", material_assignments.PROP_PROJECTION, material_assignments.PROJECTION_AUTO, "Texture projection"),
            ("App::PropertyFloat", material_assignments.PROP_TILE_U_MM, 1000.0, "Physical texture tile size U in mm"),
            ("App::PropertyFloat", material_assignments.PROP_TILE_V_MM, 1000.0, "Physical texture tile size V in mm"),
            ("App::PropertyFloat", material_assignments.PROP_REFLECTIVITY, 0.35, "Polished reflectivity factor"),
            ("App::PropertyInteger", material_assignments.PROP_MIRROR_SIZE, 512, "Castle mirror texture resolution"),
        ]
        properties = set(getattr(obj, "PropertiesList", []) or [])
        for prop_type, name, default, description in specs:
            if name in properties:
                continue
            obj.addProperty(prop_type, name, material_assignments.PROPERTY_GROUP, description)
            setattr(obj, name, default)
            properties.add(name)

    def _current_object_material_assignment(self) -> dict:
        texture_id = str(self._combo_data(self.combo_material_texture) or material_assignments.TEXTURE_NONE)
        return material_assignments.normalize_assignment(
            {
                "enabled": True,
                "mode": self._combo_data(self.combo_material_mode),
                "texture_id": texture_id,
                "texture_path": self.material_texture_line.text().strip() if texture_id == material_assignments.TEXTURE_CUSTOM else "",
                "projection": self._combo_data(self.combo_material_projection),
                "tile_u_mm": float(self.spin_material_tile_u.value()),
                "tile_v_mm": float(self.spin_material_tile_v.value()),
                "reflectivity": float(self.spin_material_reflectivity.value()),
                "mirror_size": int(self._combo_data(self.combo_mirror_size) or 512),
            }
        )

    def _apply_object_material_assignment(self):
        if not self.material_object_names:
            self._use_selection_as_material_objects()
        if not self.material_object_names:
            return
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return
        cfg = self._current_object_material_assignment()
        if cfg["mode"] != material_assignments.MODE_MIRROR:
            resolved = material_assignments.resolve_texture_path(cfg)
            if cfg["texture_id"] not in (material_assignments.TEXTURE_NONE, material_assignments.TEXTURE_CUSTOM) and not resolved:
                self.object_material_status_label.setText(
                    i18n.bi("No se encontro la textura incluida seleccionada.", "The selected bundled texture was not found.")
                )
                return
            if cfg["texture_id"] == material_assignments.TEXTURE_CUSTOM and not cfg["texture_path"] and cfg["mode"] == material_assignments.MODE_TEXTURE:
                self.object_material_status_label.setText(
                    i18n.bi("Seleccione un archivo de textura personalizado.", "Select a custom texture file.")
                )
                return
            if cfg["texture_path"] and not os.path.isfile(str(cfg["texture_path"])):
                self.object_material_status_label.setText(
                    i18n.bi("El archivo de textura no existe.", "The texture file does not exist.")
                )
                return
        transaction_open = False
        try:
            if hasattr(doc, "openTransaction"):
                doc.openTransaction("GameEngineExport material assignment")
                transaction_open = True
            changed = 0
            for name in self.material_object_names:
                obj = doc.getObject(name)
                if obj is None:
                    continue
                self._ensure_object_material_properties(obj)
                setattr(obj, material_assignments.PROP_ENABLED, True)
                setattr(obj, material_assignments.PROP_MODE, str(cfg["mode"]))
                setattr(obj, material_assignments.PROP_TEXTURE_ID, str(cfg["texture_id"]))
                setattr(obj, material_assignments.PROP_TEXTURE_PATH, str(cfg["texture_path"]))
                setattr(obj, material_assignments.PROP_PROJECTION, str(cfg["projection"]))
                setattr(obj, material_assignments.PROP_TILE_U_MM, float(cfg["tile_u_mm"]))
                setattr(obj, material_assignments.PROP_TILE_V_MM, float(cfg["tile_v_mm"]))
                setattr(obj, material_assignments.PROP_REFLECTIVITY, float(cfg["reflectivity"]))
                setattr(obj, material_assignments.PROP_MIRROR_SIZE, int(cfg["mirror_size"]))
                changed += 1
                FreeCAD.Console.PrintMessage(
                    "[GAMEEXPORT] Material assignment: object="
                    + str(getattr(obj, "Name", ""))
                    + ", mode="
                    + str(cfg["mode"])
                    + ", texture="
                    + str(cfg["texture_id"])
                    + "\n"
                )
            if transaction_open and hasattr(doc, "commitTransaction"):
                doc.commitTransaction()
                transaction_open = False
            if hasattr(doc, "recompute"):
                doc.recompute()
            self._refresh_object_material_status(
                i18n.bi(
                    f"OK - Acabado asignado correctamente a {changed} objeto(s). Guarde el FCStd para conservarlo.",
                    f"OK - Finish assigned successfully to {changed} object(s). Save the FCStd to keep it.",
                )
            )
        except Exception as exc:
            if transaction_open and hasattr(doc, "abortTransaction"):
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
            FreeCAD.Console.PrintError("[GAMEEXPORT][ERROR] Material assignment failed: " + str(exc) + "\n")
            self.object_material_status_label.setText(str(exc))

    def _clear_object_material_assignment(self):
        if not self.material_object_names:
            self._use_selection_as_material_objects()
        doc = FreeCAD.ActiveDocument
        if doc is None or not self.material_object_names:
            return
        transaction_open = False
        try:
            if hasattr(doc, "openTransaction"):
                doc.openTransaction("GameEngineExport clear material assignment")
                transaction_open = True
            changed = 0
            for name in self.material_object_names:
                obj = doc.getObject(name)
                if obj is None:
                    continue
                if material_assignments.PROP_ENABLED in set(getattr(obj, "PropertiesList", []) or []):
                    setattr(obj, material_assignments.PROP_ENABLED, False)
                    changed += 1
            if transaction_open and hasattr(doc, "commitTransaction"):
                doc.commitTransaction()
                transaction_open = False
            if hasattr(doc, "recompute"):
                doc.recompute()
            self._refresh_object_material_status(
                i18n.bi(
                    f"OK - Acabado desactivado en {changed} objeto(s).",
                    f"OK - Finish disabled on {changed} object(s).",
                )
            )
        except Exception as exc:
            if transaction_open and hasattr(doc, "abortTransaction"):
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
            self.object_material_status_label.setText(str(exc))

    def _browse_object_texture(self):
        start = self.material_texture_line.text().strip() or os.path.expanduser("~")
        selected, _ = QtGui.QFileDialog.getOpenFileName(
            self.widget,
            i18n.bi("Seleccionar textura", "Select texture"),
            start,
            "Images (*.png *.jpg *.jpeg *.webp);;All files (*.*)",
        )
        if selected:
            self.material_texture_line.setText(selected)
            self._set_combo_data(self.combo_material_texture, material_assignments.TEXTURE_CUSTOM)

    def _on_object_texture_preset_changed(self, *_args, update_tile=True) -> None:
        texture_id = str(self._combo_data(self.combo_material_texture) or material_assignments.TEXTURE_NONE)
        custom = texture_id == material_assignments.TEXTURE_CUSTOM
        self.material_texture_line.setEnabled(custom)
        self.btn_material_texture_browse.setEnabled(custom)
        if update_tile:
            meta = material_assignments.BUILTIN_TEXTURES.get(texture_id, {})
            if meta:
                self.spin_material_tile_u.setValue(float(meta.get("tile_u_mm", 1000.0)))
                self.spin_material_tile_v.setValue(float(meta.get("tile_v_mm", 1000.0)))

    def _on_object_material_mode_changed(self, *_args) -> None:
        mode = str(self._combo_data(self.combo_material_mode) or material_assignments.MODE_TEXTURE)
        mirror = mode == material_assignments.MODE_MIRROR
        polished = mode == material_assignments.MODE_POLISHED
        self.combo_material_texture.setEnabled(not mirror)
        self.material_texture_line.setEnabled(not mirror and str(self._combo_data(self.combo_material_texture)) == material_assignments.TEXTURE_CUSTOM)
        self.btn_material_texture_browse.setEnabled(not mirror and str(self._combo_data(self.combo_material_texture)) == material_assignments.TEXTURE_CUSTOM)
        self.combo_material_projection.setEnabled(not mirror)
        self.spin_material_tile_u.setEnabled(not mirror)
        self.spin_material_tile_v.setEnabled(not mirror)
        self.spin_material_reflectivity.setEnabled(polished)
        self.combo_mirror_size.setEnabled(mirror)
        if mirror:
            self.object_material_status_label.setText(
                i18n.bi(
                    "Espejo: use preferiblemente un objeto o superficie aproximadamente plana.",
                    "Mirror: preferably use an approximately planar object or surface.",
                )
            )

    def _build_ground_texture_group(self):
        group = QtGui.QGroupBox(i18n.bi("Textura de suelo", "Ground texture"))
        grid = QtGui.QGridLayout(group)

        self.chk_ground_texture = QtGui.QCheckBox(i18n.bi("Aplicar textura al objeto suelo", "Apply texture to ground object"))
        self.chk_ground_texture.setToolTip(
            i18n.bi('Cambia solo el X3D exportado; no modifica materiales de FreeCAD.', 'Changes only the exported X3D; FreeCAD materials are not modified.')
        )
        self.chk_ground_texture.toggled.connect(self._update_ground_texture_status)
        grid.addWidget(self.chk_ground_texture, 0, 0, 1, 4)

        grid.addWidget(QtGui.QLabel(i18n.bi("Objeto", "Object")), 1, 0)
        self.ground_object_line = QtGui.QLineEdit()
        self.ground_object_line.setReadOnly(True)
        grid.addWidget(self.ground_object_line, 1, 1)
        btn_ground_selection = QtGui.QPushButton(i18n.bi("Tomar seleccion", "Use selection"))
        btn_ground_selection.clicked.connect(self._use_selection_as_ground_texture_object)
        grid.addWidget(btn_ground_selection, 1, 2, 1, 2)

        grid.addWidget(QtGui.QLabel(i18n.bi("Textura", "Texture")), 2, 0)
        self.ground_texture_line = QtGui.QLineEdit()
        self.ground_texture_line.textChanged.connect(self._update_ground_texture_status)
        grid.addWidget(self.ground_texture_line, 2, 1)
        btn_texture_browse = QtGui.QPushButton(i18n.bi("Examinar", "Browse"))
        btn_texture_browse.clicked.connect(self._browse_ground_texture)
        grid.addWidget(btn_texture_browse, 2, 2, 1, 2)

        grid.addWidget(QtGui.QLabel(i18n.bi("Repetir S", "Repeat S")), 3, 0)
        self.spin_ground_repeat_s = QtGui.QDoubleSpinBox()
        self.spin_ground_repeat_s.setRange(0.01, 1000.0)
        self.spin_ground_repeat_s.setDecimals(2)
        self.spin_ground_repeat_s.setSingleStep(1.0)
        self.spin_ground_repeat_s.setValue(20.0)
        grid.addWidget(self.spin_ground_repeat_s, 3, 1)

        grid.addWidget(QtGui.QLabel(i18n.bi("Repetir T", "Repeat T")), 3, 2)
        self.spin_ground_repeat_t = QtGui.QDoubleSpinBox()
        self.spin_ground_repeat_t.setRange(0.01, 1000.0)
        self.spin_ground_repeat_t.setDecimals(2)
        self.spin_ground_repeat_t.setSingleStep(1.0)
        self.spin_ground_repeat_t.setValue(20.0)
        grid.addWidget(self.spin_ground_repeat_t, 3, 3)

        self.chk_ground_planar_uv = QtGui.QCheckBox(i18n.bi("Generar UV planar XY", "Generate planar XY UV"))
        self.chk_ground_planar_uv.setChecked(True)
        self.chk_ground_planar_uv.setToolTip(
            i18n.bi('Crea coordenadas UV desde X/Y del objeto exportado para evitar textura estirada.', 'Creates UV coordinates from exported object X/Y to avoid stretched texture.')
        )
        grid.addWidget(self.chk_ground_planar_uv, 4, 0, 1, 4)

        self.ground_texture_status_label = QtGui.QLabel("")
        self.ground_texture_status_label.setStyleSheet("color: #475569;")
        grid.addWidget(self.ground_texture_status_label, 5, 0, 1, 4)

        return group

    def _add_skybox_controls(self, grid, row_offset: int) -> None:
        sky_label = QtGui.QLabel(i18n.bi("Cielo Castle Viewer", "Castle Viewer sky"))
        sky_label.setStyleSheet("font-weight: bold;")
        grid.addWidget(sky_label, row_offset, 0, 1, 4)

        self.chk_environment_skybox = QtGui.QCheckBox(i18n.bi("Usar cielo de Castle Viewer", "Use Castle Viewer sky"))
        self.chk_environment_skybox.setToolTip(
            i18n.bi('Inserta un Background con las seis imagenes de example_models/skies.', 'Insert a Background using the six images from example_models/skies.')
        )
        self.chk_environment_skybox.toggled.connect(self._update_skybox_status)
        grid.addWidget(self.chk_environment_skybox, row_offset + 1, 0, 1, 4)

        grid.addWidget(QtGui.QLabel(i18n.bi("Carpeta skies", "Skies folder")), row_offset + 2, 0)
        self.skybox_dir_line = QtGui.QLineEdit()
        self.skybox_dir_line.textChanged.connect(self._update_skybox_status)
        grid.addWidget(self.skybox_dir_line, row_offset + 2, 1)

        btn_detect = QtGui.QPushButton(i18n.bi("Detectar", "Detect"))
        btn_detect.clicked.connect(self._detect_skybox_dir_from_config)
        grid.addWidget(btn_detect, row_offset + 2, 2)

        btn_browse = QtGui.QPushButton(i18n.bi("Examinar", "Browse"))
        btn_browse.clicked.connect(self._browse_skybox_dir)
        grid.addWidget(btn_browse, row_offset + 2, 3)

        self.skybox_status_label = QtGui.QLabel("")
        self.skybox_status_label.setStyleSheet("color: #475569;")
        grid.addWidget(self.skybox_status_label, row_offset + 3, 0, 1, 4)

    def _build_config_tab(self):
        """Build in-dialog configuration tab (no separate command required)."""
        tab = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(tab)

        nav_group = QtGui.QGroupBox("Castle Model Viewer")
        nav_grid = QtGui.QGridLayout(nav_group)
        nav_grid.addWidget(QtGui.QLabel(i18n.bi("Velocidad WALK", "Walk speed")), 0, 0)
        self.spin_nav_speed = QtGui.QDoubleSpinBox()
        self.spin_nav_speed.setRange(0.1, 10000.0)
        self.spin_nav_speed.setDecimals(2)
        self.spin_nav_speed.setSingleStep(0.1)
        nav_grid.addWidget(self.spin_nav_speed, 0, 1)

        nav_grid.addWidget(QtGui.QLabel(i18n.bi("Altura avatar (mm)", "Avatar height (mm)")), 1, 0)
        self.spin_eye_height_mm = QtGui.QDoubleSpinBox()
        self.spin_eye_height_mm.setRange(100.0, 5000.0)
        self.spin_eye_height_mm.setDecimals(0)
        self.spin_eye_height_mm.setSingleStep(50.0)
        self.spin_eye_height_mm.setSuffix(" mm")
        nav_grid.addWidget(self.spin_eye_height_mm, 1, 1)

        gravity_label = QtGui.QLabel(
            i18n.bi("Gravedad: Z+ (fija por conversion de ejes -90 X en exportacion)", "Gravity: Z+ (fixed by -90 X axis conversion during export)")
        )
        gravity_label.setWordWrap(True)
        nav_grid.addWidget(gravity_label, 2, 0, 1, 2)
        layout.addWidget(nav_group)

        cge_group = QtGui.QGroupBox("Castle Engine")
        cge_layout = QtGui.QGridLayout(cge_group)
        cge_layout.addWidget(QtGui.QLabel(i18n.bi("Ejecutable", "Executable")), 0, 0)
        self.cge_path_line = QtGui.QLineEdit()
        self.cge_path_line.textChanged.connect(self._update_skybox_status)
        cge_layout.addWidget(self.cge_path_line, 0, 1)
        btn_cge_browse = QtGui.QPushButton(i18n.bi("Examinar", "Browse"))
        btn_cge_browse.clicked.connect(self._browse_cge_path)
        cge_layout.addWidget(btn_cge_browse, 0, 2)
        cge_hint = QtGui.QLabel(
            i18n.bi(
                "La ruta se guarda para futuros usos. Si falta o deja de existir, Ejecutar en Castle la solicitara automaticamente.",
                "The path is saved for future use. If it is missing or stops existing, Run in Castle will request it automatically.",
            )
        )
        cge_hint.setWordWrap(True)
        cge_hint.setStyleSheet("color: #475569;")
        cge_layout.addWidget(cge_hint, 1, 0, 1, 3)
        self._add_skybox_controls(cge_layout, 2)
        layout.addWidget(cge_group)

        layout.addStretch()
        return tab

    def _load_defaults(self):
        doc = FreeCAD.ActiveDocument
        doc_path = None
        if doc and getattr(doc, "FileName", ""):
            doc_path = Path(doc.FileName)
        self.doc_path = doc_path

        unsaved_name = ""
        if doc is not None and doc_path is None:
            unsaved_name = str(getattr(doc, "Label", "") or getattr(doc, "Name", "") or "Scene")
        output_dir, base_name, _ = compute_output_defaults(
            self.params, doc_path, unsaved_name=unsaved_name
        )
        self.output_dir_line.setText(output_dir)
        self.base_name_line.setText(base_name)
        if doc_path is None:
            self.output_dir_line.setPlaceholderText(
                i18n.bi("Salida temporal para documento sin guardar", "Temporary output for unsaved document")
            )
            self.output_dir_line.setToolTip(
                i18n.bi('El X3D se guarda en la carpeta temporal del sistema y no reemplaza las preferencias de otros proyectos.', 'The X3D is stored under the system temporary folder and does not replace other project preferences.')
            )
        self.launch_checkbox.setChecked(bool(self.params.GetBool("launch_cge", False)))
        self._set_geometry_export_mode(
            self.params.GetString("x3d_geometry_mode", "Optimized")
        )
        self.cge_path = self.params.GetString("cge_path", "")
        self.cge_path_line.setText(self.cge_path)
        nav_speed = self._normalize_nav_speed(float(self.params.GetFloat("nav_speed", 2.0)))
        self.spin_nav_speed.setValue(nav_speed)
        self.spin_eye_height_mm.setValue(float(self.params.GetFloat("nav_eye_height_mm", 1600.0)))
        self.chk_global_light.setChecked(bool(self.params.GetBool("gl_enabled", False)))
        self.spin_gl_yaw.setValue(float(self.params.GetFloat("gl_yaw", -30.0)))
        self.spin_gl_pitch.setValue(float(self.params.GetFloat("gl_pitch", -45.0)))
        self.spin_gl_intensity.setValue(float(self.params.GetFloat("gl_intensity", 1.2)))
        self.chk_camera_fill.setChecked(bool(self.params.GetBool("camera_fill_enabled", True)))
        self.spin_camera_fill_intensity.setValue(
            float(
                self.params.GetFloat(
                    "camera_fill_intensity", ARCHITECTURAL_CAMERA_FILL_INTENSITY
                )
            )
        )
        self.chk_gl_shadows.setChecked(bool(self.params.GetBool("gl_shadows", False)))
        color_string = self.params.GetString("gl_color", "255,243,217")
        self.global_light_color = self._color_from_param_string(color_string, self.global_light_color)
        self._update_global_color_button()
        self.chk_pointlights.setChecked(bool(self.params.GetBool("export_pointlights", False)))
        self.chk_auto_detect_luminaires.setChecked(
            bool(self.params.GetBool("auto_detect_luminaires", True))
        )
        self._set_local_light_mode(
            self.params.GetString(
                "local_light_mode", exporter_x3d.LIGHT_MODE_SPOT_NO_SHADOWS
            )
        )
        self.spin_light_lumens.setValue(
            float(self.params.GetFloat("photometric_lumens", exporter_x3d.DEFAULT_PHOTOMETRIC_LUMENS))
        )
        self.spin_light_beam_angle.setValue(
            float(self.params.GetFloat("photometric_beam_angle_deg", exporter_x3d.DEFAULT_PHOTOMETRIC_BEAM_ANGLE_DEG))
        )
        self.spin_light_cct.setValue(
            float(self.params.GetFloat("photometric_cct_kelvin", exporter_x3d.DEFAULT_PHOTOMETRIC_CCT_K))
        )
        self._update_photometric_candela()
        self.chk_include_hidden_3d_objects.setChecked(
            bool(
                self.params.GetBool(
                    "include_hidden_3d_objects",
                    self.params.GetBool("include_hidden_3d_links", True),
                )
            )
        )
        self.chk_automatic_3d_scene.setChecked(
            bool(self.params.GetBool("automatic_3d_scene", True))
        )
        shadow_version = self.params.GetString("pointlight_shadow_version", "")
        self.chk_pointlight_shadows.setChecked(
            bool(self.params.GetBool("pointlight_shadows", False)) and shadow_version == "limited-v1"
        )
        self.spin_max_shadow_lights.setValue(int(self.params.GetInt("pointlight_max_shadows", 1)))
        self._set_point_light_falloff_mode(self.params.GetString("pointlight_falloff", "Interior"))
        self.chk_improve_interior_lighting.setChecked(
            bool(self.params.GetBool("improve_interior_lighting", False))
        )
        self._set_material_lighting_mode(self.params.GetString("interior_lighting_mode", "None"))
        self.chk_environment_skybox.setChecked(bool(self.params.GetBool("env_use_skybox", False)))
        stored_skybox_dir = self.params.GetString("env_skybox_dir", "").strip()
        self.skybox_dir_line.setText(stored_skybox_dir or self._discover_skybox_dir())
        self._update_skybox_status()
        self.chk_ground_texture.setChecked(bool(self.params.GetBool("ground_texture_enabled", False)))
        self.ground_object_line.setText(self.params.GetString("ground_texture_object", ""))
        self.ground_texture_line.setText(self.params.GetString("ground_texture_path", ""))
        self.spin_ground_repeat_s.setValue(float(self.params.GetFloat("ground_texture_repeat_s", 20.0)))
        self.spin_ground_repeat_t.setValue(float(self.params.GetFloat("ground_texture_repeat_t", 20.0)))
        self.chk_ground_planar_uv.setChecked(bool(self.params.GetBool("ground_texture_planar_uv", True)))
        self._update_ground_texture_status()
        gamestart_label = self.params.GetString("gamestart_label", "GameStart")
        self.gamestart_line.setText(gamestart_label)
        self.root_names = []
        self._load_sidecar()
        if not self.sidecar_data:
            self._apply_architectural_profile(log=False)
        self._update_gamestart_state()
        self._update_global_color_button()

    def _load_sidecar(self):
        """Load document-specific preferences from sidecar JSON."""
        self.export_names = set()
        self.sidecar_data = {}
        self.doc_path = None
        self._set_root_names([])

        doc = FreeCAD.ActiveDocument
        if not doc or not getattr(doc, "FileName", ""):
            self._update_root_line()
            return
        self.doc_path = Path(doc.FileName)
        data = persist.load_sidecar(self.doc_path)
        if not data:
            return

        self.sidecar_data = data

        candidate_roots: List[str] = []
        stored_roots = data.get("root_names")
        if isinstance(stored_roots, (list, tuple)):
            candidate_roots = [str(item) for item in stored_roots if str(item).strip()]
        else:
            root_name = str(data.get("root_name", ""))
            if root_name:
                for part in root_name.replace(";", ",").split(","):
                    part = part.strip()
                    if part:
                        candidate_roots.append(part)
        self._set_root_names(candidate_roots)

        export_names = data.get("export_names") or data.get("export_list") or []
        self.export_names = {name for name in export_names if isinstance(name, str)}

        gamestart_label = data.get("gamestart_label")
        if gamestart_label:
            self.gamestart_line.setText(gamestart_label)

        output_cfg = data.get("output", {})
        if isinstance(output_cfg, dict):
            document_dir_is_valid = bool(
                self.doc_path is not None and self.doc_path.parent.is_dir()
            )
            sidecar_dir = str(output_cfg.get("dir", "") or "").strip()
            if not document_dir_is_valid and sidecar_dir:
                expanded_sidecar_dir = os.path.expandvars(os.path.expanduser(sidecar_dir))
                if Path(expanded_sidecar_dir).is_dir():
                    self.output_dir_line.setText(str(Path(expanded_sidecar_dir)))
            if output_cfg.get("base_name"):
                self.base_name_line.setText(output_cfg["base_name"])

        geometry_export_cfg = data.get("geometry_export")
        if isinstance(geometry_export_cfg, dict):
            self._set_geometry_export_mode(
                str(geometry_export_cfg.get("mode", "Optimized"))
            )

        global_cfg = data.get("global_light")
        if isinstance(global_cfg, dict):
            if "enabled" in global_cfg:
                self.chk_global_light.setChecked(bool(global_cfg.get("enabled", False)))
            if "yaw" in global_cfg:
                self.spin_gl_yaw.setValue(float(global_cfg.get("yaw", self.spin_gl_yaw.value())))
            if "pitch" in global_cfg:
                self.spin_gl_pitch.setValue(float(global_cfg.get("pitch", self.spin_gl_pitch.value())))
            if "intensity" in global_cfg:
                self.spin_gl_intensity.setValue(float(global_cfg.get("intensity", self.spin_gl_intensity.value())))
            if "color" in global_cfg:
                self.global_light_color = self._color_from_config_value(global_cfg["color"])
                self._update_global_color_button()
            if "shadows" in global_cfg:
                self.chk_gl_shadows.setChecked(bool(global_cfg.get("shadows", False)))

        navigation_cfg = data.get("navigation")
        if isinstance(navigation_cfg, dict):
            if "speed" in navigation_cfg:
                self.spin_nav_speed.setValue(
                    self._normalize_nav_speed(float(navigation_cfg.get("speed", self.spin_nav_speed.value())))
                )
            if "eye_height_mm" in navigation_cfg:
                self.spin_eye_height_mm.setValue(
                    float(navigation_cfg.get("eye_height_mm", self.spin_eye_height_mm.value()))
                )
            if "camera_fill_enabled" in navigation_cfg:
                self.chk_camera_fill.setChecked(
                    bool(navigation_cfg.get("camera_fill_enabled", False))
                )
            if "camera_fill_intensity" in navigation_cfg:
                self.spin_camera_fill_intensity.setValue(
                    float(
                        navigation_cfg.get(
                            "camera_fill_intensity",
                            self.spin_camera_fill_intensity.value(),
                        )
                    )
                )

        if "export_pointlights" in data:
            self.chk_pointlights.setChecked(bool(data.get("export_pointlights", False)))

        scene_selection = data.get("scene_selection")
        if isinstance(scene_selection, dict):
            automatic_setting = scene_selection.get("automatic_3d_scene")
            if automatic_setting is not None:
                self.chk_automatic_3d_scene.setChecked(bool(automatic_setting))
            hidden_setting = scene_selection.get(
                "include_hidden_3d_objects",
                scene_selection.get("include_hidden_3d_links"),
            )
            if hidden_setting is not None:
                self.chk_include_hidden_3d_objects.setChecked(bool(hidden_setting))

        point_options = data.get("point_light_options")
        if isinstance(point_options, dict):
            if "light_mode" in point_options:
                self._set_local_light_mode(str(point_options.get("light_mode", "")))
            if "auto_detect_luminaires" in point_options:
                self.chk_auto_detect_luminaires.setChecked(
                    bool(point_options.get("auto_detect_luminaires", True))
                )
            if "shadows" in point_options:
                has_safe_limit = "max_shadow_lights" in point_options
                self.chk_pointlight_shadows.setChecked(bool(point_options.get("shadows", False)) and has_safe_limit)
            if "max_shadow_lights" in point_options:
                self.spin_max_shadow_lights.setValue(
                    max(0, min(4, int(point_options.get("max_shadow_lights", 1) or 1)))
                )
            if "falloff" in point_options:
                self._set_point_light_falloff_mode(str(point_options.get("falloff", "Interior")))
            if "default_lumens" in point_options:
                self.spin_light_lumens.setValue(float(point_options.get("default_lumens", exporter_x3d.DEFAULT_PHOTOMETRIC_LUMENS)))
            if "default_beam_angle_deg" in point_options:
                self.spin_light_beam_angle.setValue(float(point_options.get("default_beam_angle_deg", exporter_x3d.DEFAULT_PHOTOMETRIC_BEAM_ANGLE_DEG)))
            if "default_cct_kelvin" in point_options:
                self.spin_light_cct.setValue(float(point_options.get("default_cct_kelvin", exporter_x3d.DEFAULT_PHOTOMETRIC_CCT_K)))

        materials_cfg = data.get("materials")
        if isinstance(materials_cfg, dict):
            if "improve_interior_lighting" in materials_cfg:
                self.chk_improve_interior_lighting.setChecked(
                    bool(materials_cfg.get("improve_interior_lighting", False))
                )
            if "interior_lighting_mode" in materials_cfg:
                self._set_material_lighting_mode(str(materials_cfg.get("interior_lighting_mode", "None")))

        environment_cfg = data.get("environment")
        if isinstance(environment_cfg, dict):
            if "use_skybox" in environment_cfg:
                self.chk_environment_skybox.setChecked(bool(environment_cfg.get("use_skybox", False)))
            if "skybox_dir" in environment_cfg:
                sidecar_skybox_dir = str(environment_cfg.get("skybox_dir", "") or "").strip()
                if sidecar_skybox_dir:
                    self.skybox_dir_line.setText(sidecar_skybox_dir)
            if not self.skybox_dir_line.text().strip():
                    self.skybox_dir_line.setText(self._discover_skybox_dir())
            self._update_skybox_status()

        ground_cfg = data.get("ground_texture")
        if isinstance(ground_cfg, dict):
            if "enabled" in ground_cfg:
                self.chk_ground_texture.setChecked(bool(ground_cfg.get("enabled", False)))
            if "object_name" in ground_cfg:
                self.ground_object_line.setText(str(ground_cfg.get("object_name", "") or ""))
            if "texture_path" in ground_cfg:
                self.ground_texture_line.setText(str(ground_cfg.get("texture_path", "") or ""))
            if "repeat_s" in ground_cfg:
                self.spin_ground_repeat_s.setValue(float(ground_cfg.get("repeat_s", self.spin_ground_repeat_s.value())))
            if "repeat_t" in ground_cfg:
                self.spin_ground_repeat_t.setValue(float(ground_cfg.get("repeat_t", self.spin_ground_repeat_t.value())))
            if "generate_planar_uv" in ground_cfg:
                self.chk_ground_planar_uv.setChecked(bool(ground_cfg.get("generate_planar_uv", True)))
            self._update_ground_texture_status()

        scene_lights = data.get("scene_lights", [])
        resolved_names: set[str] = set()
        if isinstance(scene_lights, (list, tuple)):
            for value in scene_lights:
                candidate = str(value)
                obj = doc.getObject(candidate)
                if obj is None:
                    obj = next((o for o in doc.Objects if getattr(o, "Label", "") == candidate), None)
                if obj is not None:
                    resolved_names.add(obj.Name)
        if not resolved_names:
            label_list = data.get("scene_light_labels", [])
            if isinstance(label_list, (list, tuple)):
                for label in label_list:
                    obj = next((o for o in doc.Objects if getattr(o, "Label", "") == str(label)), None)
                    if obj is not None:
                        resolved_names.add(obj.Name)
        self.light_names = resolved_names
        lights.apply_light_names(doc, self.light_names)
        saved_profile = str(data.get("lighting_profile_name", "") or "").strip()
        if self._lighting_profile_data(saved_profile) is not None:
            self.active_lighting_profile = saved_profile
        elif str(data.get("export_profile_version", "") or "") == ARCHITECTURAL_PROFILE_VERSION:
            self.active_lighting_profile = lighting_profiles.DEFAULT_PROFILE_NAME
        self._refresh_lighting_profile_combo(self.active_lighting_profile)

    def _apply_export_selection(self):
        """Move saved export items from available list into export list."""
        if not self.export_names:
            return

        added_names = set()
        move_items = []
        for idx in range(self.list_available.count()):
            item = self.list_available.item(idx)
            name = item.data(QtCore.Qt.UserRole)
            if name in self.export_names:
                move_items.append(item)

        for item in move_items:
            name = item.data(QtCore.Qt.UserRole)
            new = QtGui.QListWidgetItem(item.text())
            new.setData(QtCore.Qt.UserRole, name)
            self.list_export.addItem(new)
            row = self.list_available.row(item)
            self.list_available.takeItem(row)
            added_names.add(name)

        remaining = set(self.export_names) - added_names
        doc = FreeCAD.ActiveDocument
        for name in sorted(remaining):
            obj = doc.getObject(name) if doc else None
            text = self._format_object_label(obj, name)
            item = QtGui.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, name)
            if obj is None:
                item.setForeground(QtGui.QBrush(QtGui.QColor("#9ca3af")))
            self.list_export.addItem(item)

        self._update_export_names()

    def _update_export_names(self):
        """Refresh the cached set of export object names."""
        self.export_names = {
            self.list_export.item(i).data(QtCore.Qt.UserRole)
            for i in range(self.list_export.count())
        }

    def _save_sidecar(self, output_dir: str, base_name: str, gamestart_label: str):
        """Persist current selections to the sidecar JSON."""
        if self.doc_path is None:
            FreeCAD.Console.PrintMessage("[GAMEEXPORT] Sidecar not saved (document without file path)\n")
            return

        doc = FreeCAD.ActiveDocument
        data = dict(self.sidecar_data) if isinstance(self.sidecar_data, dict) else {}

        root_labels = []
        if doc:
            for name in self.root_names:
                obj = doc.getObject(name)
                if obj is not None and getattr(obj, "Label", ""):
                    root_labels.append(obj.Label)

        data["root_names"] = list(self.root_names)
        data["root_name"] = ";".join(self.root_names)
        data["root_label"] = ", ".join(root_labels)
        data["export_names"] = sorted(self.export_names)
        data["gamestart_label"] = gamestart_label
        data["output"] = {"dir": output_dir, "base_name": base_name}
        data["geometry_export"] = self._geometry_export_config()

        data["global_light"] = {
            "enabled": bool(self.chk_global_light.isChecked()),
            "yaw": float(self.spin_gl_yaw.value()),
            "pitch": float(self.spin_gl_pitch.value()),
            "intensity": float(self.spin_gl_intensity.value()),
            "color": [float(value) for value in self.global_light_color],
            "ambient_intensity": self._global_light_ambient_intensity(),
            "shadows": bool(self.chk_gl_shadows.isChecked()),
        }
        data["navigation"] = self._navigation_config()
        data["scene_selection"] = {
            "automatic_3d_scene": bool(self.chk_automatic_3d_scene.isChecked()),
            "include_hidden_3d_objects": bool(
                self.chk_include_hidden_3d_objects.isChecked()
            )
        }
        data["export_profile_version"] = ARCHITECTURAL_PROFILE_VERSION
        data["lighting_profile_name"] = self.active_lighting_profile
        data["materials"] = self._material_lighting_config()
        data["environment"] = self._environment_config_for_sidecar()
        data["point_light_options"] = self._point_light_options_config()
        data["ground_texture"] = self._ground_texture_config()

        data["export_pointlights"] = bool(self.chk_pointlights.isChecked())
        self._update_light_names()
        data["scene_lights"] = sorted(self.light_names)

        if doc:
            data["document_label"] = doc.Label
            export_labels = []
            for name in data["export_names"]:
                obj = doc.getObject(name)
                if obj is not None:
                    export_labels.append(obj.Label)
            if export_labels:
                data["export_labels"] = export_labels
            light_labels = []
            for name in data["scene_lights"]:
                obj = doc.getObject(name)
                if obj is not None:
                    light_labels.append(obj.Label)
            if light_labels:
                data["scene_light_labels"] = light_labels

        self.sidecar_data = data
        persist.save_sidecar(self.doc_path, data)

    def _refresh_available(self):
        previous_export = set(self.export_names)
        self.list_export.clear()
        self.export_names = previous_export
        self.list_available.clear()
        selected_light_names = []
        if hasattr(self, "list_lights"):
            selected_light_names = [
                self.list_lights.item(i).data(QtCore.Qt.UserRole)
                for i in range(self.list_lights.count())
                if self.list_lights.item(i).isSelected()
            ]
            self.list_lights.clear()
        doc = FreeCAD.ActiveDocument
        if doc is None:
            self.status_label.setText("No hay documento activo.")
            self.light_names = set()
            return

        roots = self._resolve_root_objects(doc)
        objects = self._collect_objects_for_display(doc, roots)

        gs_label = self.gamestart_line.text().strip() or "GameStart"
        gs_obj = gamestart.find_gamestart(doc, gs_label)
        gs_name = gs_obj.Name if gs_obj else None

        seen = set()
        for obj in objects:
            if obj is None:
                continue
            if obj.Name in seen:
                continue
            seen.add(obj.Name)
            if obj.Name == gs_name or getattr(obj, "Label", "") == gs_label:
                continue
            if getattr(obj, "ViewObject", None) is None and not hasattr(obj, "Group"):
                continue
            item = QtGui.QListWidgetItem(self._format_object_label(obj, obj.Name))
            item.setData(QtCore.Qt.UserRole, obj.Name)
            self.list_available.addItem(item)

        self.status_label.setText(f"Objetos disponibles: {self.list_available.count()}")
        self._update_gamestart_state()
        self._apply_export_selection()
        self._refresh_light_list(selected_light_names)

    def _clear_export_list(self):
        self.list_export.clear()
        self._update_export_names()

    def _move_selected_to_export(self):
        selected = list(self.list_available.selectedItems())
        if not selected:
            return
        for item in self.list_available.selectedItems():
            new = QtGui.QListWidgetItem(item.text())
            new.setData(QtCore.Qt.UserRole, item.data(QtCore.Qt.UserRole))
            self.list_export.addItem(new)
        for item in self.list_available.selectedItems():
            row = self.list_available.row(item)
            self.list_available.takeItem(row)
        self._update_export_names()

    def _move_selected_to_available(self):
        selected = list(self.list_export.selectedItems())
        if not selected:
            return
        for item in self.list_export.selectedItems():
            new = QtGui.QListWidgetItem(item.text())
            new.setData(QtCore.Qt.UserRole, item.data(QtCore.Qt.UserRole))
            self.list_available.addItem(new)
        for item in self.list_export.selectedItems():
            row = self.list_export.row(item)
            self.list_export.takeItem(row)
        self._update_export_names()

    def _add_current_selection_to_export(self):
        """Add current 3D selection (e.g. selected with Shift+B) into export list."""
        doc = FreeCAD.ActiveDocument
        if doc is None:
            self.status_label.setText("No hay documento activo.")
            return

        selected = FreeCADGui.Selection.getSelection()
        if not selected:
            self.status_label.setText("Seleccion vacia.")
            return

        export_names = {
            self.list_export.item(i).data(QtCore.Qt.UserRole)
            for i in range(self.list_export.count())
        }
        available_by_name = {}
        for i in range(self.list_available.count()):
            item = self.list_available.item(i)
            available_by_name[item.data(QtCore.Qt.UserRole)] = item

        added = 0
        for obj in selected:
            if obj is None or obj.Document != doc:
                continue
            name = obj.Name
            if name in export_names:
                continue

            existing = available_by_name.get(name)
            if existing is not None:
                row = self.list_available.row(existing)
                self.list_available.takeItem(row)
                new_item = QtGui.QListWidgetItem(existing.text())
                new_item.setData(QtCore.Qt.UserRole, name)
            else:
                new_item = QtGui.QListWidgetItem(self._format_object_label(obj, name))
                new_item.setData(QtCore.Qt.UserRole, name)

            self.list_export.addItem(new_item)
            export_names.add(name)
            added += 1

        self._update_export_names()
        self.status_label.setText(f"Agregados a exportar: {added}")

    def _use_selection_as_root(self):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            self.status_label.setText("No hay documento activo.")
            return
        selected = FreeCADGui.Selection.getSelection()
        if not selected:
            self.status_label.setText("Seleccion vacia.")
            return
        added = []
        for obj in selected:
            if obj is None or obj.Document != doc:
                continue
            if obj.Name not in self.root_names:
                self.root_names.append(obj.Name)
                added.append(obj.Label if getattr(obj, "Label", "") else obj.Name)
        if not added:
            self.status_label.setText("Raices sin cambios.")
        else:
            self.status_label.setText("Raices agregadas: " + ", ".join(added))
        self._update_root_line()
        self._refresh_available()

    def _clear_root_selection(self):
        self.root_names = []
        self._update_root_line()
        self._refresh_available()
        self.status_label.setText("Raices limpiadas.")

    def _set_root_names(self, names):
        doc = FreeCAD.ActiveDocument
        unique = []
        if doc:
            for name in names:
                obj = doc.getObject(str(name))
                if obj is not None and obj.Name not in unique:
                    unique.append(obj.Name)
        self.root_names = unique
        self._update_root_line()

    def _update_root_line(self):
        if not self.root_names:
            self.root_line.setText("")
            return
        doc = FreeCAD.ActiveDocument
        display_names = []
        for name in self.root_names:
            label = name
            if doc:
                obj = doc.getObject(name)
                if obj is not None:
                    lbl = getattr(obj, "Label", "")
                    if lbl and lbl != name:
                        label = f"{lbl} ({name})"
                    else:
                        label = name
            display_names.append(label)
        self.root_line.setText(", ".join(display_names))

    def _resolve_root_objects(self, doc):
        if doc is None:
            return []
        resolved = []
        valid_names = []
        for name in self.root_names:
            obj = doc.getObject(name)
            if obj is not None:
                resolved.append(obj)
                valid_names.append(obj.Name)
        if valid_names != self.root_names:
            self.root_names = valid_names
            self._update_root_line()
        return resolved

    def _collect_objects_for_display(self, doc, roots):
        if doc is None:
            return []
        seen = set()
        ordered = []

        def traverse(obj):
            if obj is None or obj.Name in seen:
                return
            seen.add(obj.Name)
            if self._is_exportable_object(obj):
                ordered.append(obj)
            if hasattr(obj, "Group"):
                for child in obj.Group:
                    traverse(child)

        if roots:
            for root in roots:
                traverse(root)
        else:
            for obj in doc.Objects:
                traverse(obj)
        return ordered

    def _format_object_label(self, obj, fallback_name):
        if obj is None:
            return fallback_name
        label = getattr(obj, "Label", "")
        if label and label != obj.Name:
            return f"{label} ({obj.Name})"
        return obj.Name

    def _is_exportable_object(self, obj):
        if obj is None:
            return False
        if hasattr(obj, "Group"):
            return True
        view = getattr(obj, "ViewObject", None)
        if view is None or getattr(view, "Visibility", True) is False:
            return False
        type_id = getattr(obj, "TypeId", "")
        if type_id.startswith("App::Annotation") or type_id.startswith("Spreadsheet::"):
            return False
        if type_id.startswith("TechDraw::"):
            return False
        if hasattr(obj, "LinkedObject") and obj.LinkedObject is None:
            return False
        if not hasattr(obj, "Shape") and not hasattr(obj, "Mesh"):
            return False
        return True

    def _browse_output_dir(self):
        candidate = self.output_dir_line.text().strip()
        if candidate and os.path.isdir(candidate):
            start_dir = candidate
        elif self.doc_path is not None and self.doc_path.parent.is_dir():
            start_dir = str(self.doc_path.parent)
        else:
            start_dir = os.path.expanduser("~")
        selected = QtGui.QFileDialog.getExistingDirectory(
            self.widget, "Seleccionar carpeta de salida", start_dir
        )
        if selected:
            self.output_dir_line.setText(selected)

    def _dialog_parent(self):
        """Return a visible parent for modal dialogs, including one-click commands."""
        try:
            if self.widget is not None and self.widget.isVisible():
                return self.widget
        except Exception:
            pass
        try:
            return FreeCADGui.getMainWindow()
        except Exception:
            return self.widget

    def _castle_config_location_text(self):
        return i18n.bi(
            "Tambien puede cambiarla en Game Engine Export > Configuracion > Castle Engine > Ejecutable.",
            "You can also change it in Game Engine Export > Configuration > Castle Engine > Executable.",
        )

    def _castle_browse_start(self):
        current = self.cge_path_line.text().strip()
        if current:
            candidate = Path(current).expanduser()
            if candidate.is_dir():
                return str(candidate)
            try:
                parent = candidate.parent
                if parent.is_dir():
                    return str(parent)
            except Exception:
                pass
        return os.path.expanduser("~")

    def _select_castle_executable(self):
        """Ask for Castle executable, persist it immediately, and return the selected path."""
        selected, _ = QtGui.QFileDialog.getOpenFileName(
            self._dialog_parent(),
            i18n.bi("Seleccionar ejecutable Castle", "Select Castle executable"),
            self._castle_browse_start(),
        )
        selected = str(selected or "").strip()
        if not selected:
            return ""
        if not os.path.isfile(selected):
            FreeCAD.Console.PrintWarning(
                "[GAMEEXPORT][WARN] Selected Castle executable is not a file\n"
            )
            return ""

        self.cge_path_line.setText(selected)
        self.cge_path = selected
        self.params.SetString("cge_path", selected)
        FreeCAD.Console.PrintMessage(
            "[GAMEEXPORT] Castle executable configured: "
            + _safe_path_label(selected)
            + "\n"
        )
        if not exporter_x3d.detect_skybox_faces(self.skybox_dir_line.text().strip()):
            detected = self._discover_skybox_dir()
            if detected:
                self.skybox_dir_line.setText(detected)
        self._update_skybox_status()
        return selected

    def _browse_cge_path(self):
        self._select_castle_executable()

    def _ensure_castle_executable(self, prompt_if_missing=True):
        """Ensure Castle is configured; optionally guide the user to select it."""
        candidate = self.cge_path_line.text().strip()
        if candidate and os.path.isfile(candidate):
            self.cge_path = candidate
            if self.params.GetString("cge_path", "") != candidate:
                self.params.SetString("cge_path", candidate)
            return True

        if not prompt_if_missing:
            return False

        if candidate:
            reason = i18n.bi(
                "La ruta guardada para Castle Model Viewer ya no existe.",
                "The saved Castle Model Viewer path no longer exists.",
            )
        else:
            reason = i18n.bi(
                "Castle Model Viewer no esta configurado.",
                "Castle Model Viewer is not configured.",
            )

        message = (
            reason
            + "\n\n"
            + i18n.bi(
                "Se abrira una ventana para seleccionar el ejecutable. La ruta elegida quedara guardada para futuros usos.",
                "A file picker will open so you can select the executable. The selected path will be saved for future use.",
            )
            + "\n\n"
            + self._castle_config_location_text()
        )
        try:
            QtGui.QMessageBox.information(
                self._dialog_parent(),
                i18n.bi("Configurar Castle Model Viewer", "Configure Castle Model Viewer"),
                message,
            )
        except Exception as exc:
            FreeCAD.Console.PrintWarning(
                "[GAMEEXPORT][WARN] Could not show Castle configuration message: "
                + str(exc)
                + "\n"
            )

        selected = self._select_castle_executable()
        if selected:
            return True

        status_text = i18n.bi(
            "Castle no configurado. Puede configurarlo en Configuracion > Castle Engine > Ejecutable.",
            "Castle is not configured. Configure it under Configuration > Castle Engine > Executable.",
        )
        try:
            self.status_label.setText(status_text)
        except Exception:
            pass
        FreeCAD.Console.PrintWarning(
            "[GAMEEXPORT][WARN] Castle launch cancelled; executable is not configured. "
            + self._castle_config_location_text()
            + "\n"
        )
        return False

    def _create_gamestart(self):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            self.status_label.setText("No hay documento activo.")
            return
        label = self.gamestart_line.text().strip() or "GameStart"
        obj = gamestart.ensure_gamestart(doc, label)
        created = obj is not None
        if created:
            self.gamestart_line.setText(obj.Label)
        self._update_gamestart_state()
        doc.recompute()
        self._refresh_available()
        if created:
            self.status_label.setText("GameStart creado.")
        else:
            self.status_label.setText("No se pudo crear GameStart.")

    def _update_gamestart_state(self):
        doc = FreeCAD.ActiveDocument
        label = self.gamestart_line.text().strip() or "GameStart"
        obj = gamestart.find_gamestart(doc, label) if doc else None
        if obj:
            self.label_gamestart_state.setText("GameStart listo")
            self.label_gamestart_state.setStyleSheet("color: #16a34a;")
        else:
            self.label_gamestart_state.setText("GameStart no encontrado")
            self.label_gamestart_state.setStyleSheet("color: #dc2626;")
        return obj

    @staticmethod
    def _color_from_param_string(text: str, default: tuple[float, float, float]) -> tuple[float, float, float]:
        try:
            parts = [int(p) for p in text.split(",")]
            if len(parts) == 3:
                return tuple(max(0.0, min(1.0, p / 255.0)) for p in parts)
        except Exception:
            pass
        return default

    def _color_from_config_value(self, value) -> tuple[float, float, float]:
        if isinstance(value, str):
            return self._color_from_param_string(value, self.global_light_color)
        if isinstance(value, (list, tuple)) and len(value) == 3:
            try:
                if any(float(v) > 1.0 for v in value):
                    return tuple(max(0.0, min(1.0, float(v) / 255.0)) for v in value)
                return tuple(max(0.0, min(1.0, float(v))) for v in value)
            except Exception:
                pass
        return self.global_light_color

    @staticmethod
    def _color_to_param_string(color: tuple[float, float, float]) -> str:
        vals = [max(0, min(255, int(round(c * 255.0)))) for c in color]
        return "{},{},{}".format(*vals)

    def _update_global_color_button(self) -> None:
        r, g, b = [max(0, min(255, int(round(c * 255.0)))) for c in self.global_light_color]
        qcolor = QtGui.QColor(r, g, b)
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        text_color = "#000000" if luminance > 150 else "#ffffff"
        self.btn_gl_color.setStyleSheet(
            f"background-color: {qcolor.name()}; color: {text_color}; border: 1px solid #444;"
        )

    def _choose_global_color(self):
        current = QtGui.QColor(
            int(self.global_light_color[0] * 255),
            int(self.global_light_color[1] * 255),
            int(self.global_light_color[2] * 255),
        )
        new_color = QtGui.QColorDialog.getColor(current, self.widget, i18n.bi("Seleccionar color", "Select color"))
        if new_color.isValid():
            self.global_light_color = (
                new_color.red() / 255.0,
                new_color.green() / 255.0,
                new_color.blue() / 255.0,
            )
            self._update_global_color_button()
            if isinstance(self.sidecar_data, dict):
                gl_cfg = dict(self.sidecar_data.get("global_light", {}))
                gl_cfg["color"] = [new_color.red(), new_color.green(), new_color.blue()]
                self.sidecar_data["global_light"] = gl_cfg

    def _open_solar_dialog(self):
        now = datetime.datetime.now()
        offset_hours = -time.timezone / 3600.0
        if time.daylight and time.localtime().tm_isdst:
            offset_hours += 1.0

        gl_cfg = self.sidecar_data.get("global_light") if isinstance(self.sidecar_data, dict) else {}
        if not isinstance(gl_cfg, dict):
            gl_cfg = {}

        lat_default = float(gl_cfg.get("latitude", 10.0))
        lon_default = float(gl_cfg.get("longitude", -84.0))
        tz_default = float(gl_cfg.get("timezone", offset_hours))
        timestamp = gl_cfg.get("timestamp")
        stored_dt = None
        if isinstance(timestamp, str):
            try:
                stored_dt = datetime.datetime.fromisoformat(timestamp)
            except Exception:
                stored_dt = None
        if stored_dt is None:
            stored_dt = now

        dialog = QtGui.QDialog(self.widget)
        dialog.setWindowTitle(i18n.bi("Hora solar", "Solar time"))
        main_layout = QtGui.QVBoxLayout(dialog)
        form = QtGui.QFormLayout()

        lat_spin = QtGui.QDoubleSpinBox()
        lat_spin.setRange(-90.0, 90.0)
        lat_spin.setDecimals(3)
        lat_spin.setValue(lat_default)

        lon_spin = QtGui.QDoubleSpinBox()
        lon_spin.setRange(-180.0, 180.0)
        lon_spin.setDecimals(3)
        lon_spin.setValue(lon_default)

        tz_spin = QtGui.QDoubleSpinBox()
        tz_spin.setRange(-14.0, 14.0)
        tz_spin.setSingleStep(0.25)
        tz_spin.setDecimals(2)
        tz_spin.setValue(tz_default)

        dt_edit = QtGui.QDateTimeEdit()
        dt_edit.setCalendarPopup(True)
        dt_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        dt_edit.setDateTime(
            QtCore.QDateTime(
                stored_dt.year,
                stored_dt.month,
                stored_dt.day,
                stored_dt.hour,
                stored_dt.minute,
                stored_dt.second,
            )
        )

        btn_now = QtGui.QPushButton(i18n.bi("Usar ahora", "Use current time"))

        def _apply_now():
            current_dt = QtCore.QDateTime.currentDateTime()
            dt_edit.setDateTime(current_dt)

        btn_now.clicked.connect(_apply_now)

        form.addRow("Latitud (deg)", lat_spin)
        form.addRow("Longitud (deg)", lon_spin)
        form.addRow("Zona horaria UTC", tz_spin)
        form.addRow("Fecha y hora", dt_edit)

        main_layout.addLayout(form)
        main_layout.addWidget(btn_now)

        button_box = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)
        main_layout.addWidget(button_box)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        if dialog.exec_() != QtGui.QDialog.Accepted:
            return

        lat = float(lat_spin.value())
        lon = float(lon_spin.value())
        tz_hours = float(tz_spin.value())
        qdt = dt_edit.dateTime()
        dt = datetime.datetime(
            qdt.date().year(),
            qdt.date().month(),
            qdt.date().day(),
            qdt.time().hour(),
            qdt.time().minute(),
            qdt.time().second(),
        )

        try:
            yaw, pitch, altitude = self._compute_solar_angles(lat, lon, tz_hours, dt)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return

        self.chk_global_light.setChecked(True)
        self.spin_gl_yaw.setValue(yaw)
        self.spin_gl_pitch.setValue(pitch)
        self.status_label.setText(
            "Luz solar: yaw {:.1f} deg, pitch {:.1f} deg (altura solar {:.1f} deg)".format(
                yaw, pitch, altitude
            )
        )

        if not isinstance(self.sidecar_data, dict):
            self.sidecar_data = {}
        gl_cfg = dict(self.sidecar_data.get("global_light", {}))
        gl_cfg.update(
            {
                "enabled": True,
                "yaw": yaw,
                "pitch": pitch,
                "intensity": float(self.spin_gl_intensity.value()),
                "color": [
                    int(max(0, min(255, round(self.global_light_color[0] * 255.0)))),
                    int(max(0, min(255, round(self.global_light_color[1] * 255.0)))),
                    int(max(0, min(255, round(self.global_light_color[2] * 255.0)))),
                ],
                "latitude": lat,
                "longitude": lon,
                "timezone": tz_hours,
                "timestamp": dt.isoformat(timespec="minutes"),
            }
        )
        self.sidecar_data["global_light"] = gl_cfg

    def _compute_solar_angles(
        self, latitude: float, longitude: float, tz_hours: float, dt: datetime.datetime
    ) -> tuple[float, float, float]:
        lat_rad = math.radians(latitude)
        n = dt.timetuple().tm_yday
        decl_deg = 23.45 * math.sin(math.radians((360.0 / 365.0) * (284 + n)))
        decl_rad = math.radians(decl_deg)
        B = math.radians((360.0 / 365.0) * (n - 81))
        eq_time = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)
        lstm = 15.0 * tz_hours
        local_minutes = dt.hour * 60.0 + dt.minute + dt.second / 60.0
        time_offset = eq_time + 4.0 * (longitude - lstm)
        true_solar_minutes = local_minutes + time_offset
        solar_time_hours = true_solar_minutes / 60.0
        hour_angle_rad = math.radians(15.0 * (solar_time_hours - 12.0))

        altitude_rad = math.asin(
            math.sin(lat_rad) * math.sin(decl_rad)
            + math.cos(lat_rad) * math.cos(decl_rad) * math.cos(hour_angle_rad)
        )
        if altitude_rad <= 0:
            raise ValueError("Sol por debajo del horizonte para esa hora.")

        azimuth_rad = math.atan2(
            -math.sin(hour_angle_rad),
            math.tan(decl_rad) * math.cos(lat_rad) - math.sin(lat_rad) * math.cos(hour_angle_rad),
        )

        dx = math.cos(altitude_rad) * math.sin(azimuth_rad)
        dy = -math.cos(altitude_rad) * math.cos(azimuth_rad)
        dz = math.sin(altitude_rad)
        horizontal = math.sqrt(max(1e-9, dx * dx + dy * dy))
        yaw_deg = math.degrees(math.atan2(dx, -dy))
        yaw_deg = ((yaw_deg + 180.0) % 360.0) - 180.0
        pitch_deg = math.degrees(math.atan2(-dz, horizontal))
        pitch_deg = max(-90.0, min(90.0, pitch_deg))
        altitude_deg = math.degrees(altitude_rad)
        return yaw_deg, pitch_deg, altitude_deg
    def _update_light_names(self):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            self.light_names = set()
            return
        current = lights.list_point_lights(doc)
        self.light_names = {obj.Name for obj in current}

    def _refresh_light_list(self, selected_names: Optional[List[str]] = None):
        if selected_names is None:
            selected_names = [
                self.list_lights.item(i).data(QtCore.Qt.UserRole)
                for i in range(self.list_lights.count())
                if self.list_lights.item(i).isSelected()
            ]
        selected_set = set(selected_names or [])

        self.list_lights.clear()
        doc = FreeCAD.ActiveDocument
        if doc is None:
            self.btn_apply_light_props.setEnabled(False)
            return
        self._update_light_names()
        for obj in lights.list_point_lights(doc):
            props = lights.get_light_properties(obj)
            color = props["color"]
            color_hex = "#{:02x}{:02x}{:02x}".format(
                int(color[0] * 255),
                int(color[1] * 255),
                int(color[2] * 255),
            )
            text = (
                f"{obj.Label} ({obj.Name})  "
                f"I={props['intensity']:.2f}  R={props['radius']:.1f}  "
                f"{props['lumens']:.0f} lm / "
                f"{exporter_x3d.photometric_candela(props['lumens'], props['beam_angle_deg']):.0f} cd  "
                f"C={color_hex}"
            )
            item = QtGui.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, obj.Name)
            self.list_lights.addItem(item)
            if obj.Name in selected_set:
                item.setSelected(True)

        self._on_lights_selection_changed()

    def _update_light_color_button(self):
        r = int(max(0, min(255, round(self.light_color_current[0] * 255.0))))
        g = int(max(0, min(255, round(self.light_color_current[1] * 255.0))))
        b = int(max(0, min(255, round(self.light_color_current[2] * 255.0))))
        color = QtGui.QColor(r, g, b)
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        text_color = "#000000" if luminance > 150 else "#ffffff"
        self.btn_light_color.setStyleSheet(
            f"background-color: {color.name()}; color: {text_color}; border: 1px solid #444;"
        )

    def _choose_light_color(self):
        current = QtGui.QColor(
            int(self.light_color_current[0] * 255),
            int(self.light_color_current[1] * 255),
            int(self.light_color_current[2] * 255),
        )
        chosen = QtGui.QColorDialog.getColor(current, self.widget, i18n.bi("Color de luz", "Light color"))
        if chosen.isValid():
            self.light_color_current = (
                chosen.red() / 255.0,
                chosen.green() / 255.0,
                chosen.blue() / 255.0,
            )
            self._update_light_color_button()

    def _on_lights_selection_changed(self):
        items = self.list_lights.selectedItems()
        has_selection = bool(items)
        self.btn_apply_light_props.setEnabled(has_selection)
        doc = FreeCAD.ActiveDocument
        if not has_selection or doc is None:
            return
        name = items[0].data(QtCore.Qt.UserRole)
        obj = doc.getObject(name) if name else None
        if obj is None:
            return
        props = lights.get_light_properties(obj)
        self.spin_light_intensity.setValue(props["intensity"])
        self.spin_light_radius.setValue(props["radius"])
        self.spin_light_lumens.setValue(props["lumens"])
        self.spin_light_beam_angle.setValue(props["beam_angle_deg"])
        self.spin_light_cct.setValue(props["cct_kelvin"])
        self.light_color_current = props["color"]
        self._update_light_color_button()

    def _apply_light_properties(self):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            self.status_label.setText("No hay documento activo.")
            return
        items = self.list_lights.selectedItems()
        if not items:
            self.status_label.setText("Selecciona una luz en la lista.")
            return
        objects = []
        names = []
        for item in items:
            name = item.data(QtCore.Qt.UserRole)
            obj = doc.getObject(name) if name else None
            if obj is not None:
                objects.append(obj)
                names.append(obj.Name)
        if not objects:
            self.status_label.setText("No se encontraron objetos para actualizar.")
            return
        lights.set_light_properties(
            doc,
            objects,
            intensity=self.spin_light_intensity.value(),
            radius=self.spin_light_radius.value(),
            color=self.light_color_current,
            lumens=self.spin_light_lumens.value(),
            beam_angle_deg=self.spin_light_beam_angle.value(),
            cct_kelvin=self.spin_light_cct.value(),
        )
        labels = [getattr(obj, "Label", obj.Name) for obj in objects]
        self.status_label.setText("Luces actualizadas: " + ", ".join(labels))
        self._refresh_light_list(names)
        if isinstance(self.sidecar_data, dict):
            self.sidecar_data["scene_lights"] = sorted(self.light_names)

    def _add_lights_from_selection(self):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            self.status_label.setText("No hay documento activo.")
            return
        selection = FreeCADGui.Selection.getSelection()
        if not selection:
            self.status_label.setText("Seleccion vacia.")
            return
        names = lights.tag_selection_as_light(doc, selection)
        if names:
            self.status_label.setText("Marcadas como luz: " + ", ".join(names))
        else:
            self.status_label.setText("No se pudo marcar seleccion.")
        self._refresh_light_list(names)
        if isinstance(self.sidecar_data, dict):
            self.sidecar_data["scene_lights"] = sorted(self.light_names)

    def _remove_lights_from_list(self):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            self.status_label.setText("No hay documento activo.")
            return
        items = self.list_lights.selectedItems()
        if not items:
            self.status_label.setText("Selecciona una luz en la lista.")
            return
        objects = []
        for item in items:
            name = item.data(QtCore.Qt.UserRole)
            obj = doc.getObject(name) if name else None
            if obj is not None:
                objects.append(obj)
        if not objects:
            self.status_label.setText("No se encontraron objetos para quitar.")
            return
        names = lights.untag_selection_as_light(doc, objects)
        if names:
            self.status_label.setText("Luces quitadas: " + ", ".join(names))
        else:
            self.status_label.setText("No se pudo quitar la marca de luz.")
        self._refresh_light_list()
        if isinstance(self.sidecar_data, dict):
            self.sidecar_data["scene_lights"] = sorted(self.light_names)

    def _global_light_config(self) -> dict | None:
        if not self.chk_global_light.isChecked():
            return None
        return {
            "enabled": True,
            "yaw": float(self.spin_gl_yaw.value()),
            "pitch": float(self.spin_gl_pitch.value()),
            "intensity": float(self.spin_gl_intensity.value()),
            "color": self.global_light_color,
            "ambient_intensity": self._global_light_ambient_intensity(),
            "shadows": bool(self.chk_gl_shadows.isChecked()),
        }

    def _architectural_profile_is_active(self) -> bool:
        return self.active_lighting_profile == lighting_profiles.DEFAULT_PROFILE_NAME

    def _global_light_ambient_intensity(self) -> float:
        if self._architectural_profile_is_active():
            return ARCHITECTURAL_GLOBAL_AMBIENT
        return 0.18

    def _navigation_config(self) -> dict:
        speed = self._normalize_nav_speed(float(self.spin_nav_speed.value()))
        if abs(speed - float(self.spin_nav_speed.value())) > 1e-9:
            self.spin_nav_speed.setValue(speed)
        return {
            "speed": speed,
            "eye_height_mm": float(self.spin_eye_height_mm.value()),
            "gravity_up": "Z+",
            "camera_fill_enabled": bool(self.chk_camera_fill.isChecked())
            and self._local_light_mode() != exporter_x3d.LIGHT_MODE_PHOTOMETRIC,
            "camera_fill_intensity": float(self.spin_camera_fill_intensity.value()),
            "camera_fill_ambient_intensity": 0.25,
        }

    def _material_lighting_config(self) -> dict:
        return {
            "improve_interior_lighting": bool(self.chk_improve_interior_lighting.isChecked()),
            "interior_lighting_mode": self._material_lighting_mode(),
        }

    def _ground_texture_config(self, log: bool = False) -> dict:
        object_name = self.ground_object_line.text().strip()
        doc = FreeCAD.ActiveDocument
        target_obj = self._find_ground_texture_object(doc, object_name)
        cfg = {
            "enabled": bool(self.chk_ground_texture.isChecked()),
            "object_name": object_name,
            "object_label": str(getattr(target_obj, "Label", "") or "") if target_obj is not None else "",
            "texture_path": self.ground_texture_line.text().strip(),
            "repeat_s": float(self.spin_ground_repeat_s.value()),
            "repeat_t": float(self.spin_ground_repeat_t.value()),
            "generate_planar_uv": bool(self.chk_ground_planar_uv.isChecked()),
        }
        # Quick Examples must not inherit a legacy external ground texture
        # selected for another document. Keep the global preference untouched,
        # but disable it for this export when its target is absent.
        if cfg["enabled"] and target_obj is None and _is_quick_example_document(doc):
            if log:
                FreeCAD.Console.PrintWarning(
                    "[GAMEEXPORT][WARN] Ignored inherited ground texture for Quick Example; "
                    "configured target is not present in this document.\n"
                )
            cfg["enabled"] = False
            cfg["object_name"] = ""
            cfg["object_label"] = ""
            cfg["texture_path"] = ""
            return cfg
        if log and cfg["enabled"]:
            if not cfg["object_name"]:
                FreeCAD.Console.PrintWarning("[GAMEEXPORT][WARN] Ground texture enabled without object.\n")
            elif target_obj is None:
                FreeCAD.Console.PrintWarning(
                    "[GAMEEXPORT][WARN] Ground texture object not found in document: "
                    + cfg["object_name"]
                    + "; exporter will try inferred terrain target.\n"
                )
            if not cfg["texture_path"]:
                FreeCAD.Console.PrintWarning("[GAMEEXPORT][WARN] Ground texture enabled without texture file.\n")
            elif not os.path.isfile(cfg["texture_path"]):
                FreeCAD.Console.PrintWarning(
                    "[GAMEEXPORT][WARN] Ground texture file not found: "
                    + _safe_path_label(cfg["texture_path"])
                    + "\n"
                )
            else:
                FreeCAD.Console.PrintMessage(
                    "[GAMEEXPORT] Ground texture enabled for object "
                    + cfg["object_name"]
                    + ": "
                    + _safe_path_label(cfg["texture_path"])
                    + "\n"
                )
        return cfg

    def _use_selection_as_ground_texture_object(self):
        selection = FreeCADGui.Selection.getSelection()
        if not selection:
            self.status_label.setText("Seleccione el objeto suelo.")
            return
        obj = selection[0]
        self.ground_object_line.setText(str(getattr(obj, "Name", "") or ""))
        self.chk_ground_texture.setChecked(True)
        self._update_ground_texture_status()
        label = getattr(obj, "Label", "") or getattr(obj, "Name", "")
        self.status_label.setText("Objeto suelo seleccionado: " + str(label))

    def _browse_ground_texture(self):
        start = self.ground_texture_line.text().strip() or os.path.expanduser("~")
        selected, _ = QtGui.QFileDialog.getOpenFileName(
            self.widget,
            i18n.bi("Seleccionar textura de suelo", "Select ground texture"),
            start,
            "Images (*.png *.jpg *.jpeg *.webp);;All files (*.*)",
        )
        if selected:
            self.ground_texture_line.setText(selected)
            self.chk_ground_texture.setChecked(True)
            self._update_ground_texture_status()

    def _update_ground_texture_status(self, *_args) -> None:
        if not hasattr(self, "ground_texture_status_label"):
            return
        if not bool(self.chk_ground_texture.isChecked()):
            self.ground_texture_status_label.setText(i18n.bi("Textura de suelo desactivada", "Ground texture disabled"))
            return
        object_name = self.ground_object_line.text().strip()
        texture_path = self.ground_texture_line.text().strip()
        if not object_name:
            self.ground_texture_status_label.setText("Falta seleccionar objeto suelo")
            return
        if not texture_path:
            self.ground_texture_status_label.setText("Falta seleccionar archivo de textura")
            return
        if not os.path.isfile(texture_path):
            self.ground_texture_status_label.setText("Archivo de textura no encontrado")
            return
        if self._find_ground_texture_object(FreeCAD.ActiveDocument, object_name) is None:
            self.ground_texture_status_label.setText("Objeto suelo no encontrado; se intentara detectar terreno")
            return
        self.ground_texture_status_label.setText("Textura lista para aplicar al X3D")

    def _find_ground_texture_object(self, doc, object_name):
        if doc is None or not object_name:
            return None
        obj = doc.getObject(object_name)
        if obj is not None:
            return obj
        for candidate in getattr(doc, "Objects", []):
            if str(getattr(candidate, "Label", "") or "") == object_name:
                return candidate
        return None

    def _point_light_options_config(self) -> dict:
        shadows = bool(self.chk_pointlight_shadows.isChecked())
        falloff = self._point_light_falloff_mode()
        max_shadow_lights = max(0, min(4, int(self.spin_max_shadow_lights.value())))
        attenuation = {
            "Interior": "1 0.30 0.06",
            "Soft": "1 0.08 0.01",
            "Constant": "1 0 0",
        }.get(falloff, "1 0.30 0.06")
        return {
            "auto_detect_luminaires": bool(self.chk_auto_detect_luminaires.isChecked()),
            "light_mode": self._local_light_mode(),
            "shadows": shadows,
            "max_shadow_lights": max_shadow_lights,
            "falloff": falloff,
            "attenuation": attenuation,
            "ambient_intensity": 0.02 if falloff == "Interior" else 0.10,
            "beam_width": exporter_x3d.DEFAULT_SPOT_BEAM_WIDTH,
            "cut_off_angle": exporter_x3d.DEFAULT_SPOT_CUTOFF_ANGLE,
            "shadow_map_size": exporter_x3d.DEFAULT_SPOT_SHADOW_MAP_SIZE,
            "default_lumens": float(self.spin_light_lumens.value()),
            "default_beam_angle_deg": float(self.spin_light_beam_angle.value()),
            "default_cct_kelvin": float(self.spin_light_cct.value()),
        }

    def _apply_architectural_profile(self, log: bool = False) -> None:
        """Apply the reusable settings validated with architectural projects."""
        self._apply_lighting_profile(lighting_profiles.DEFAULT_PROFILE_NAME, log=log)

    def _local_light_mode(self) -> str:
        mode = self.combo_local_light_mode.currentData()
        if mode in {
            exporter_x3d.LIGHT_MODE_SPOT_SHADOW_MAP,
            exporter_x3d.LIGHT_MODE_SPOT_NO_SHADOWS,
            exporter_x3d.LIGHT_MODE_POINT_CLASSIC,
            exporter_x3d.LIGHT_MODE_PHOTOMETRIC,
        }:
            return str(mode)
        return exporter_x3d.LIGHT_MODE_SPOT_NO_SHADOWS

    def _set_local_light_mode(self, mode: str) -> None:
        clean_mode = str(mode or exporter_x3d.LIGHT_MODE_SPOT_NO_SHADOWS)
        index = self.combo_local_light_mode.findData(clean_mode)
        if index < 0:
            index = self.combo_local_light_mode.findData(
                exporter_x3d.LIGHT_MODE_SPOT_NO_SHADOWS
            )
        self.combo_local_light_mode.setCurrentIndex(max(0, index))
        self._on_local_light_mode_changed()

    def _on_local_light_mode_changed(self, *_args) -> None:
        mode = self._local_light_mode()
        classic = mode == exporter_x3d.LIGHT_MODE_POINT_CLASSIC
        limited_spot = mode == exporter_x3d.LIGHT_MODE_SPOT_SHADOW_MAP
        photometric = mode == exporter_x3d.LIGHT_MODE_PHOTOMETRIC
        self.chk_pointlight_shadows.setEnabled(classic)
        self.spin_max_shadow_lights.setEnabled(classic or limited_spot)
        for widget in (
            self.spin_light_lumens,
            self.spin_light_beam_angle,
            self.line_light_candela,
            self.spin_light_cct,
        ):
            widget.setEnabled(photometric)
        if classic:
            self.chk_pointlight_shadows.setToolTip(
                i18n.bi('Respaldo experimental: sombras volumetricas limitadas del algoritmo anterior.', 'Experimental fallback: limited volume shadows from the previous algorithm.')
            )
        elif limited_spot:
            self.chk_pointlight_shadows.setToolTip(
                i18n.bi('Las sombras estan activas y limitadas por Max sombras.', 'Shadows are active and limited by Max shadows.')
            )
        else:
            self.chk_pointlight_shadows.setToolTip(
                i18n.bi('Este control solo aplica al modo PointLight clasico.', 'This control applies only to Classic PointLight mode.')
            )

    def _update_photometric_candela(self, *_args) -> None:
        candela = exporter_x3d.photometric_candela(
            float(self.spin_light_lumens.value()),
            float(self.spin_light_beam_angle.value()),
        )
        self.line_light_candela.setText(f"{candela:.1f}")

    def _point_light_falloff_mode(self) -> str:
        mode = str(self.combo_pointlight_falloff.currentText() or "Interior")
        if mode not in {"Interior", "Soft", "Constant"}:
            return "Interior"
        return mode

    def _set_point_light_falloff_mode(self, mode: str) -> None:
        clean_mode = mode if mode in {"Interior", "Soft", "Constant"} else "Interior"
        index = self.combo_pointlight_falloff.findText(clean_mode)
        if index < 0:
            index = 0
        self.combo_pointlight_falloff.setCurrentIndex(index)

    def _environment_config(self, log: bool = False) -> dict:
        use_skybox = bool(self.chk_environment_skybox.isChecked())
        skybox_dir = self.skybox_dir_line.text().strip()
        detected = self._discover_skybox_dir()
        source = "manual"
        if use_skybox and not exporter_x3d.detect_skybox_faces(skybox_dir):
            if detected:
                skybox_dir = detected
                self.skybox_dir_line.setText(detected)
                if log:
                    FreeCAD.Console.PrintMessage(
                        "[GAMEEXPORT] Skybox folder auto-detected from Castle executable: "
                        + _safe_path_label(detected)
                        + "\n"
                    )
        if detected and skybox_dir == detected:
            source = "castle_executable"
        if use_skybox and log:
            if exporter_x3d.detect_skybox_faces(skybox_dir):
                FreeCAD.Console.PrintMessage(
                    "[GAMEEXPORT] Environment skybox enabled: "
                    + _safe_path_label(skybox_dir)
                    + "\n"
                )
            else:
                FreeCAD.Console.PrintWarning(
                    "[GAMEEXPORT][WARN] Environment skybox enabled but no complete skies folder was found.\n"
                )
        elif log:
            FreeCAD.Console.PrintMessage("[GAMEEXPORT] Environment skybox disabled\n")
        return {
            "use_skybox": use_skybox,
            "skybox_dir": skybox_dir,
            "skybox_source": source,
        }

    def _environment_config_for_sidecar(self) -> dict:
        cfg = self._environment_config(log=False)
        if cfg.get("skybox_source") == "castle_executable":
            cfg["skybox_dir"] = ""
        return cfg

    def _browse_skybox_dir(self):
        start_dir = self.skybox_dir_line.text().strip() or self._discover_skybox_dir() or os.path.expanduser("~")
        selected = QtGui.QFileDialog.getExistingDirectory(
            self.widget,
            i18n.bi("Seleccionar carpeta skies", "Select skies folder"),
            start_dir,
        )
        if selected:
            self.skybox_dir_line.setText(selected)
            self._update_skybox_status()

    def _detect_skybox_dir_from_config(self):
        detected = self._discover_skybox_dir()
        if detected:
            self.skybox_dir_line.setText(detected)
            self.chk_environment_skybox.setChecked(True)
            self._update_skybox_status()
            self.status_label.setText("Cielo detectado: " + detected)
        else:
            self._update_skybox_status()
            self.status_label.setText("No se encontro carpeta skies junto al ejecutable Castle.")

    def _update_skybox_status(self, *_args) -> None:
        if not hasattr(self, "skybox_status_label"):
            return
        folder = self.skybox_dir_line.text().strip() if hasattr(self, "skybox_dir_line") else ""
        faces = exporter_x3d.detect_skybox_faces(folder)
        if not bool(self.chk_environment_skybox.isChecked()):
            if len(faces) == 6:
                self.skybox_status_label.setText("Cielo desactivado. Cubemap valido detectado.")
            else:
                detected = self._discover_skybox_dir()
                if detected:
                    self.skybox_status_label.setText("Cielo desactivado. Detectado junto al ejecutable Castle.")
                else:
                    self.skybox_status_label.setText("Cielo desactivado. Use Detectar o Examinar.")
            return
        if len(faces) == 6:
            self.skybox_status_label.setText("Cubemap completo: 6 imagenes detectadas")
        else:
            detected = self._discover_skybox_dir()
            if detected and detected != folder:
                self.skybox_status_label.setText("Cubemap detectado junto al ejecutable Castle. Pulse Detectar.")
            else:
                self.skybox_status_label.setText("Falta cubemap completo: back, bottom, front, left, right, top")

    def _discover_skybox_dir(self) -> str:
        for candidate in self._skybox_candidate_dirs():
            if exporter_x3d.detect_skybox_faces(str(candidate)):
                return str(candidate)
        return ""

    def _skybox_candidate_dirs(self) -> list[Path]:
        candidates: list[Path] = []

        def add_candidate(path_value) -> None:
            if not path_value:
                return
            try:
                path = Path(str(path_value)).expanduser()
            except Exception:
                return
            if path not in candidates:
                candidates.append(path)

        cge_text = ""
        if hasattr(self, "cge_path_line"):
            cge_text = self.cge_path_line.text().strip()
        if not cge_text and hasattr(self, "cge_path"):
            cge_text = str(self.cge_path or "").strip()

        if cge_text:
            exe_path = Path(cge_text).expanduser()
            bases = [exe_path.parent, exe_path.parent.parent]
            for base in bases:
                add_candidate(base / "example_models" / "skies")
                add_candidate(base / "data" / "example_models" / "skies")

        home = Path.home()
        add_candidate(home / "Desktop" / "castle-model-viewer" / "example_models" / "skies")
        userprofile = os.environ.get("USERPROFILE", "")
        if userprofile:
            add_candidate(Path(userprofile) / "Desktop" / "castle-model-viewer" / "example_models" / "skies")

        return candidates

    def _on_improve_interior_lighting_toggled(self, checked) -> None:
        if bool(checked) and self._material_lighting_mode() == "None":
            self._set_material_lighting_mode("Architectural")

    def _on_material_lighting_mode_changed(self, *_args) -> None:
        if self._material_lighting_mode() != "None":
            self.chk_improve_interior_lighting.setChecked(True)

    def _material_lighting_mode(self) -> str:
        mode = str(self.combo_interior_lighting_mode.currentText() or "None")
        if mode not in {"None", "Soft", "Architectural", "Bright"}:
            return "None"
        return mode

    def _set_material_lighting_mode(self, mode: str) -> None:
        clean_mode = mode if mode in {"None", "Soft", "Architectural", "Bright"} else "None"
        index = self.combo_interior_lighting_mode.findText(clean_mode)
        if index < 0:
            index = 0
        self.combo_interior_lighting_mode.setCurrentIndex(index)

    def _geometry_export_mode(self) -> str:
        mode = self.combo_geometry_export_mode.currentData()
        if mode is None:
            text = str(self.combo_geometry_export_mode.currentText() or "")
            mode = "Classic" if text.startswith("Clasico") else "Optimized"
        return "Classic" if str(mode) == "Classic" else "Optimized"

    def _set_geometry_export_mode(self, mode: str) -> None:
        clean_mode = "Classic" if str(mode) == "Classic" else "Optimized"
        for index in range(self.combo_geometry_export_mode.count()):
            if str(self.combo_geometry_export_mode.itemData(index)) == clean_mode:
                self.combo_geometry_export_mode.setCurrentIndex(index)
                return
        self.combo_geometry_export_mode.setCurrentIndex(
            1 if clean_mode == "Classic" else 0
        )

    def _geometry_export_config(self) -> dict:
        return {
            "mode": self._geometry_export_mode(),
            "minimum_payload_chars": 2048,
        }

    def _normalize_nav_speed(self, speed: float) -> float:
        """Normalize navigation speed and migrate legacy bad default 2000->2."""
        if speed >= 1500.0:
            return 2.0
        return max(0.1, min(10000.0, float(speed)))

    def _point_light_entries(self, doc, export_objects=None, debug_records=None):
        entries = []
        manual_count = 0
        if self.chk_pointlights.isChecked():
            self._update_light_names()
            for data in lights.gather_point_light_data(
                doc,
                self.light_names,
                skip_effective_cge=True,
                debug_records=debug_records,
            ):
                entries.append(self._point_light_entry_dict(data))
                manual_count += 1
            if manual_count == 0:
                FreeCAD.Console.PrintWarning(
                    "[GAMEEXPORT][WARN] Manual point lights enabled but no tagged objects were found.\n"
                )
        cge_data = lights.gather_cge_light_data(doc, export_objects, debug_records)
        if not cge_data and export_objects is not None:
            FreeCAD.Console.PrintWarning(
                "[GAMEEXPORT][WARN] No CGE lights found in export selection; retrying full document scan.\n"
            )
            if debug_records is not None:
                debug_records.append({"event": "cge_fallback_full_document_scan"})
            cge_data = lights.gather_cge_light_data(doc, None, debug_records)
        cge_count = 0
        architectural_profile = self._architectural_profile_is_active()
        for data in cge_data:
            entry = self._point_light_entry_dict(data)
            if architectural_profile:
                entry["radius"] = ARCHITECTURAL_CGE_LIGHT_RADIUS_M
            entries.append(entry)
            cge_count += 1
        auto_count = 0
        if self.chk_auto_detect_luminaires.isChecked():
            blocked_sources = set()
            for entry in entries:
                name = str(entry.get("name", "") or "")
                blocked_sources.add(name.split("_CGE_", 1)[0])
            for data in lights.gather_auto_luminaire_data(doc, export_objects, debug_records):
                source_name = str(data.name or "").split("_CGE_", 1)[0]
                if source_name in blocked_sources:
                    continue
                entries.append(self._point_light_entry_dict(data))
                blocked_sources.add(source_name)
                auto_count += 1
        point_options = self._point_light_options_config()
        shadow_indices = set()
        classic_mode = point_options["light_mode"] == exporter_x3d.LIGHT_MODE_POINT_CLASSIC
        limited_spot_mode = (
            point_options["light_mode"] == exporter_x3d.LIGHT_MODE_SPOT_SHADOW_MAP
        )
        if (
            (limited_spot_mode or (classic_mode and point_options["shadows"]))
            and point_options["max_shadow_lights"] > 0
        ):
            ranked = sorted(
                range(len(entries)),
                key=lambda idx: float(entries[idx].get("intensity", 0.0) or 0.0),
                reverse=True,
            )
            shadow_indices = set(ranked[: point_options["max_shadow_lights"]])
        for index, entry in enumerate(entries):
            entry["light_mode"] = point_options["light_mode"]
            if point_options["light_mode"] == exporter_x3d.LIGHT_MODE_SPOT_SHADOW_MAP:
                entry["shadows"] = index in shadow_indices
            elif point_options["light_mode"] == exporter_x3d.LIGHT_MODE_SPOT_NO_SHADOWS:
                entry["shadows"] = False
            else:
                entry["shadows"] = index in shadow_indices
            entry["falloff"] = point_options["falloff"]
            entry["attenuation"] = point_options["attenuation"]
            entry["ambient_intensity"] = point_options["ambient_intensity"]
            entry["beam_width"] = point_options["beam_width"]
            entry["cut_off_angle"] = point_options["cut_off_angle"]
            entry["shadow_map_size"] = point_options["shadow_map_size"]
            if (
                point_options["light_mode"] == exporter_x3d.LIGHT_MODE_PHOTOMETRIC
                and not bool(entry.get("photometric_configured", False))
            ):
                entry["lumens"] = point_options["default_lumens"]
                entry["beam_angle_deg"] = point_options["default_beam_angle_deg"]
                entry["cct_kelvin"] = point_options["default_cct_kelvin"]
        if entries:
            if architectural_profile and cge_count:
                FreeCAD.Console.PrintMessage(
                    "[GAMEEXPORT] Architectural profile normalized "
                    + str(cge_count)
                    + " configured CGE light ranges to "
                    + f"{ARCHITECTURAL_CGE_LIGHT_RADIUS_M:.1f} m.\n"
                )
            shadowed_count = sum(bool(entry.get("shadows", False)) for entry in entries)
            if (
                (limited_spot_mode or (classic_mode and point_options["shadows"]))
                and shadowed_count < len(entries)
            ):
                FreeCAD.Console.PrintWarning(
                    "[GAMEEXPORT][WARN] Local light shadows limited to "
                    + str(shadowed_count)
                    + " of "
                    + str(len(entries))
                    + " lights to avoid Castle shader resource overflow.\n"
                )
            FreeCAD.Console.PrintMessage(
                "[GAMEEXPORT] Local light entries prepared: "
                + f"manual={manual_count}, cge={cge_count}, auto3d={auto_count}, total={len(entries)}, "
                + "mode="
                + str(point_options["light_mode"])
                + ", "
                + "shadowed="
                + str(shadowed_count)
                + ", falloff="
                + str(point_options["falloff"])
                + "\n"
            )
        elif debug_records is not None:
            debug_records.append({"event": "no_point_lights_prepared"})
        return entries

    @staticmethod
    def _point_light_entry_dict(data):
        return {
            "name": data.name,
            "label": data.label,
            "position_mm": data.position_mm,
            "intensity": data.intensity,
            "color": data.color_rgb,
            "radius": data.radius,
            "lumens": float(getattr(data, "lumens", exporter_x3d.DEFAULT_PHOTOMETRIC_LUMENS)),
            "beam_angle_deg": float(getattr(data, "beam_angle_deg", exporter_x3d.DEFAULT_PHOTOMETRIC_BEAM_ANGLE_DEG)),
            "cct_kelvin": float(getattr(data, "cct_kelvin", exporter_x3d.DEFAULT_PHOTOMETRIC_CCT_K)),
            "photometric_configured": bool(getattr(data, "photometric_configured", False)),
        }

    def _save_debug_snapshot(
        self,
        file_path: Path,
        doc,
        export_objects,
        point_entries,
        debug_records,
        material_cfg=None,
        environment_cfg=None,
        ground_texture_cfg=None,
    ) -> None:
        debug_path = file_path.with_suffix(".gee.debug.json")
        try:
            payload = {
                "debug_version": DEBUG_VERSION,
                "geometry_export": self._geometry_export_config(),
                "document": {
                    "name": str(getattr(doc, "Name", "") or ""),
                    "label": str(getattr(doc, "Label", "") or ""),
                    "file": _safe_path_label(getattr(doc, "FileName", "") or ""),
                },
                "output_x3d": _safe_path_label(file_path),
                "export_object_count": len(export_objects or []),
                "export_objects": [self._debug_object_info(obj) for obj in export_objects or []],
                "point_light_count": len(point_entries or []),
                "point_lights": list(point_entries or []),
                "light_source_names": self._light_source_names_from_entries(point_entries),
                "materials": _sanitize_debug_value(dict(material_cfg or {})),
                "environment": _sanitize_debug_value(dict(environment_cfg or {})),
                "ground_texture": _sanitize_debug_value(dict(ground_texture_cfg or {})),
                "records": list(debug_records or []),
            }
            debug_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8")
            FreeCAD.Console.PrintMessage(
                "[GAMEEXPORT] Debug snapshot saved: " + _safe_path_label(debug_path) + "\n"
            )
        except Exception as exc:
            FreeCAD.Console.PrintWarning("[GAMEEXPORT][WARN] Could not save debug snapshot: " + str(exc) + "\n")

    @staticmethod
    def _light_source_names_from_entries(point_entries) -> list:
        names = []
        seen = set()
        for entry in point_entries or []:
            name = str(entry.get("name", "") or "")
            if "_CGE_" in name:
                name = name.split("_CGE_", 1)[0]
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names

    @staticmethod
    def _debug_object_info(obj):
        if obj is None:
            return None
        placement = lights.get_global_placement(obj)
        base = getattr(placement, "Base", None)
        return {
            "name": str(getattr(obj, "Name", "") or ""),
            "label": str(getattr(obj, "Label", "") or ""),
            "type_id": str(getattr(obj, "TypeId", "") or ""),
            "global_base_mm": [
                float(getattr(base, "x", 0.0)),
                float(getattr(base, "y", 0.0)),
                float(getattr(base, "z", 0.0)),
            ],
        }

    def getStandardButtons(self):
        return _qt_button_mask(QtGui.QDialogButtonBox.Ok, QtGui.QDialogButtonBox.Cancel)

    def accept(self):
        if self._export_scene():
            FreeCADGui.Control.closeDialog()
            return True
        return False

    def reject(self):
        FreeCAD.Console.PrintMessage("[GAMEEXPORT] Export dialog cancelled\n")
        FreeCADGui.Control.closeDialog()
        return True

    def _collect_export_objects(self, doc, gamestart_obj):
        export_names = [
            self.list_export.item(i).data(QtCore.Qt.UserRole)
            for i in range(self.list_export.count())
        ]
        export_objects = []
        for name in export_names:
            obj = doc.getObject(name)
            if obj is not None and obj is not gamestart_obj:
                export_objects.append(obj)

        automatic_scene = bool(self.chk_automatic_3d_scene.isChecked())
        include_hidden = bool(self.chk_include_hidden_3d_objects.isChecked())
        if automatic_scene:
            FreeCAD.Console.PrintMessage(
                "[GAMEEXPORT] Automatic 3D scene enabled; using reusable scene policy\n"
            )
        elif not export_objects:
            FreeCAD.Console.PrintMessage("[GAMEEXPORT] Export list empty, using entire document\n")
        return exporter_x3d.resolve_scene_objects(
            doc,
            export_objects,
            excluded_objects=[gamestart_obj] if gamestart_obj is not None else [],
            automatic_3d_scene=automatic_scene,
            include_hidden_objects=include_hidden,
        )

    def _diagnose_export_selection(self):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            self.status_label.setText("No hay documento activo.")
            return

        gamestart_label = self.gamestart_line.text().strip() or "GameStart"
        gamestart_obj = gamestart.find_gamestart(doc, gamestart_label)
        export_objects = self._collect_export_objects(doc, gamestart_obj)
        if not export_objects:
            self.status_label.setText("No hay objetos para diagnosticar.")
            return

        diag = exporter_x3d.diagnose_export_candidates(export_objects, log=True)
        total = int(diag.get("total", 0))
        skipped = len(diag.get("skipped", []))
        exportable = len(diag.get("exportable", []))
        self.status_label.setText(
            f"Diagnostico: {exportable}/{total} exportables, {skipped} omitidos (ver consola)."
        )

    def _export_web_preview(self):
        self._export_scene(web_preview_enabled=True)

    def _export_scene(self, web_preview_enabled: bool = False):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            FreeCAD.Console.PrintError("[GAMEEXPORT] No active document to export\n")
            return False

        gamestart_label = self.gamestart_line.text().strip() or "GameStart"
        gamestart_obj = gamestart.find_gamestart(doc, gamestart_label)
        export_objects = self._collect_export_objects(doc, gamestart_obj)

        if not export_objects:
            FreeCAD.Console.PrintError("[GAMEEXPORT] No geometry selected for export\n")
            return False

        output_dir = self.output_dir_line.text().strip()
        base_name = self.base_name_line.text().strip()
        if not output_dir:
            self._browse_output_dir()
            output_dir = self.output_dir_line.text().strip()
            if not output_dir:
                FreeCAD.Console.PrintWarning(
                    "[GAMEEXPORT] Export cancelled: no output folder was selected\n"
                )
                return False
        if not base_name:
            base_name = doc.Label.replace(" ", "_") or doc.Name

        safe_base_name = normalize_base_name(base_name)

        requested_output_dir = output_dir
        try:
            output_dir, output_dir_created = ensure_output_directory(output_dir)
        except (OSError, ValueError) as exc:
            FreeCAD.Console.PrintError(
                "[GAMEEXPORT][ERROR] Cannot prepare output folder: requested="
                + repr(_safe_path_label(requested_output_dir))
                + ", error_type="
                + type(exc).__name__
                + "\n"
            )
            return False
        self.output_dir_line.setText(output_dir)
        output_action = "created" if output_dir_created else "using existing"
        FreeCAD.Console.PrintMessage(
            "[GAMEEXPORT] Output folder "
            + output_action
            + ": "
            + _safe_path_label(output_dir)
            + "\n"
        )

        file_path = Path(output_dir) / (safe_base_name + ".x3d")
        gamestart_meta = gamestart.get_metadata(gamestart_obj) if gamestart_obj else None
        light_debug_records = []
        point_light_entries = self._point_light_entries(doc, export_objects, light_debug_records)
        lighting_cfg = {
            "global": self._global_light_config(),
            "point_lights": point_light_entries,
            "navigation": self._navigation_config(),
        }
        material_cfg = self._material_lighting_config()
        material_cfg["light_source_names"] = self._light_source_names_from_entries(point_light_entries)
        material_cfg["object_assignments"] = material_assignments.collect_assignments(
            export_objects, enabled_only=True
        )
        environment_cfg = self._environment_config(log=True)
        ground_texture_cfg = self._ground_texture_config(log=True)
        self._save_debug_snapshot(
            file_path,
            doc,
            export_objects,
            point_light_entries,
            light_debug_records,
            material_cfg,
            environment_cfg,
            ground_texture_cfg,
        )
        try:
            exporter_x3d.export_to_x3d(
                export_objects,
                file_path,
                gamestart_meta,
                lighting_cfg,
                material_cfg,
                environment_cfg,
                ground_texture_cfg,
                self._geometry_export_config(),
            )
        except Exception as exc:
            FreeCAD.Console.PrintError("[GAMEEXPORT] Export failed: " + str(exc) + "\n")
            return False

        # Persist last choices
        persist_output_settings(self.params, output_dir, base_name, self.doc_path)
        self.params.SetBool("launch_cge", bool(self.launch_checkbox.isChecked()))
        self.params.SetString("x3d_geometry_mode", self._geometry_export_mode())
        self.cge_path = self.cge_path_line.text().strip()
        self.params.SetString("cge_path", self.cge_path)
        self.params.SetFloat("nav_speed", float(self.spin_nav_speed.value()))
        self.params.SetFloat("nav_eye_height_mm", float(self.spin_eye_height_mm.value()))
        self.params.SetString("gamestart_label", gamestart_label)
        self.params.SetBool("gl_enabled", bool(self.chk_global_light.isChecked()))
        self.params.SetFloat("gl_yaw", float(self.spin_gl_yaw.value()))
        self.params.SetFloat("gl_pitch", float(self.spin_gl_pitch.value()))
        self.params.SetFloat("gl_intensity", float(self.spin_gl_intensity.value()))
        self.params.SetBool("camera_fill_enabled", bool(self.chk_camera_fill.isChecked()))
        self.params.SetFloat(
            "camera_fill_intensity", float(self.spin_camera_fill_intensity.value())
        )
        self.params.SetBool("gl_shadows", bool(self.chk_gl_shadows.isChecked()))
        self.params.SetString("gl_color", self._color_to_param_string(self.global_light_color))
        self.params.SetBool("export_pointlights", bool(self.chk_pointlights.isChecked()))
        self.params.SetBool(
            "auto_detect_luminaires", bool(self.chk_auto_detect_luminaires.isChecked())
        )
        self.params.SetString("local_light_mode", self._local_light_mode())
        self.params.SetBool(
            "include_hidden_3d_objects",
            bool(self.chk_include_hidden_3d_objects.isChecked()),
        )
        self.params.SetBool(
            "automatic_3d_scene",
            bool(self.chk_automatic_3d_scene.isChecked()),
        )
        self.params.SetBool("pointlight_shadows", bool(self.chk_pointlight_shadows.isChecked()))
        self.params.SetInt("pointlight_max_shadows", int(self.spin_max_shadow_lights.value()))
        self.params.SetString("pointlight_shadow_version", "limited-v1")
        self.params.SetString("pointlight_falloff", self._point_light_falloff_mode())
        self.params.SetFloat("photometric_lumens", float(self.spin_light_lumens.value()))
        self.params.SetFloat("photometric_beam_angle_deg", float(self.spin_light_beam_angle.value()))
        self.params.SetFloat("photometric_cct_kelvin", float(self.spin_light_cct.value()))
        self.params.SetBool(
            "improve_interior_lighting", bool(self.chk_improve_interior_lighting.isChecked())
        )
        self.params.SetString("interior_lighting_mode", self._material_lighting_mode())
        self.params.SetBool("env_use_skybox", bool(self.chk_environment_skybox.isChecked()))
        self.params.SetString("env_skybox_dir", self.skybox_dir_line.text().strip())
        self.params.SetBool("ground_texture_enabled", bool(self.chk_ground_texture.isChecked()))
        self.params.SetString("ground_texture_object", self.ground_object_line.text().strip())
        self.params.SetString("ground_texture_path", self.ground_texture_line.text().strip())
        self.params.SetFloat("ground_texture_repeat_s", float(self.spin_ground_repeat_s.value()))
        self.params.SetFloat("ground_texture_repeat_t", float(self.spin_ground_repeat_t.value()))
        self.params.SetBool("ground_texture_planar_uv", bool(self.chk_ground_planar_uv.isChecked()))

        self._update_export_names()
        self._save_sidecar(output_dir, base_name, gamestart_label)

        if web_preview_enabled:
            try:
                html_path = web_preview.generate_x3dom_preview(file_path)
                FreeCAD.Console.PrintMessage(
                    "[GAMEEXPORT] Web preview HTML generated: " + _safe_path_label(html_path) + "\n"
                )
                browser_opened = web_preview.open_preview(html_path)
                preview_url = web_preview.get_active_preview_url()
                if browser_opened:
                    FreeCAD.Console.PrintMessage(
                        "[GAMEEXPORT] Opening web preview in default browser: "
                        + str(preview_url or "HTTP URL unavailable")
                        + "\n"
                    )
                else:
                    FreeCAD.Console.PrintWarning("[GAMEEXPORT][WARN] Browser did not confirm web preview open\n")
                self.status_label.setText(
                    "Vista previa Web: " + str(preview_url or html_path)
                )
            except Exception as exc:
                FreeCAD.Console.PrintError("[GAMEEXPORT] Web preview failed: " + str(exc) + "\n")
                self.status_label.setText("No se pudo generar la vista previa Web.")
                return False
        elif self.launch_checkbox.isChecked():
            self._launch_castle_engine(str(file_path))

        if not web_preview_enabled:
            self.status_label.setText("Exportacion completada: " + str(file_path))
        return True

    def _launch_castle_engine(self, file_path):
        if not self._ensure_castle_executable(prompt_if_missing=True):
            return False
        cge_path = self.cge_path.strip()
        try:
            subprocess.Popen([cge_path, file_path])
            FreeCAD.Console.PrintMessage("[GAMEEXPORT] Launching Castle Engine\n")
            return True
        except Exception as exc:
            FreeCAD.Console.PrintError("[GAMEEXPORT] Failed to launch Castle Engine: " + str(exc) + "\n")
            return False


__all__ = ["ExportTaskPanel"]
