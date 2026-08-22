"""Scene TaskPanel for Game Engine Export WB.

Descripcion rapida: panel principal con pestañas para escena, configuracion y texto informativo.
Fecha y hora: 2025-10-13 13:54 UTC.
Instrucciones clave:
- Mantener interfaz bilingue ES/EN con cadenas ASCII.
- Respetar requisitos de escala, rotacion, GameStart y luces en futuras implementaciones.
- Mostrar mensajes en consola con prefijo [GAMEEXPORT] para depuracion.
- Evitar logica de exportacion aun, solo estructura y placeholders.
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

import os

from PySide import QtCore, QtGui

from . import panel_config
from . import panel_info


class TaskPanel:
    """Main TaskPanel with tabs for scene setup, config and information."""

    def __init__(self):
        FreeCAD = __import__("FreeCAD")
        FreeCAD.Console.PrintMessage("[GAMEEXPORT] Building TaskPanel widgets\n")
        self.widget = QtGui.QWidget()
        self.widget.setWindowTitle("Game Engine Export")
        self._object_map = {}

        layout = QtGui.QVBoxLayout(self.widget)
        self.tab = QtGui.QTabWidget()
        layout.addWidget(self.tab)

        self.scene_tab = self._build_scene_tab()
        self.config_tab = panel_config.build_config_tab()
        self.info_tab = panel_info.build_info_tab()

        self.tab.addTab(self.scene_tab, "Escena / Scene")
        self.tab.addTab(self.config_tab, "Config & Profiles")
        self.tab.addTab(self.info_tab, "Informacion / Information")

        self._connect_signals()
        self._register_shortcuts()
        self._apply_output_defaults()

    def _build_scene_tab(self):
        """Create widgets for the scene tab."""
        tab = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(tab)

        root_group = QtGui.QGroupBox("Raiz / Root")
        root_layout = QtGui.QHBoxLayout(root_group)
        self.root_line = QtGui.QLineEdit()
        self.root_line.setReadOnly(True)
        root_layout.addWidget(self.root_line)
        self.btn_use_selection = QtGui.QPushButton("Tomar seleccion / Use selection")
        self.btn_use_selection.setToolTip("ES: Establece el grupo principal de la escena.\nEN: Set the main scene group.")
        root_layout.addWidget(self.btn_use_selection)
        layout.addWidget(root_group)

        objects_group = QtGui.QGroupBox("Objetos / Objects")
        objects_layout = QtGui.QVBoxLayout(objects_group)
        list_layout = QtGui.QHBoxLayout()
        self.list_available = QtGui.QListWidget()
        self.list_available.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        list_layout.addWidget(self.list_available)
        btn_layout = QtGui.QVBoxLayout()
        self.btn_move_right = QtGui.QPushButton(">>")
        self.btn_move_left = QtGui.QPushButton("<<")
        btn_layout.addWidget(self.btn_move_right)
        btn_layout.addWidget(self.btn_move_left)
        btn_layout.addStretch()
        list_layout.addLayout(btn_layout)
        self.list_export = QtGui.QListWidget()
        self.list_export.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        list_layout.addWidget(self.list_export)
        objects_layout.addLayout(list_layout)

        actions_layout = QtGui.QHBoxLayout()
        self.btn_refresh = QtGui.QPushButton("Actualizar lista / Refresh list")
        self.btn_refresh.setToolTip("ES: Escanea subarbol y actualiza los objetos disponibles.\nEN: Scan subtree and refresh available objects.")
        self.btn_clear = QtGui.QPushButton("Limpiar lista / Clear list")
        self.btn_use_3d_selection = QtGui.QPushButton("Tomar seleccion 3D / Use 3D selection")
        self.btn_use_3d_selection.setToolTip("ES: Agrega la seleccion activa en 3D a la lista A exportar. Atajo: Ctrl+B.\nEN: Add active 3D selection to the To export list. Shortcut: Ctrl+B.")
        actions_layout.addWidget(self.btn_refresh)
        actions_layout.addWidget(self.btn_clear)
        actions_layout.addWidget(self.btn_use_3d_selection)
        objects_layout.addLayout(actions_layout)

        info_label = QtGui.QLabel("ES: Si la lista A exportar queda vacia se exporta todo el subarbol.\nEN: If the To export list is empty the whole subtree is exported.")
        info_label.setWordWrap(True)
        objects_layout.addWidget(info_label)
        layout.addWidget(objects_group)

        gamestart_group = QtGui.QGroupBox("GameStart")
        gamestart_layout = QtGui.QHBoxLayout(gamestart_group)
        self.gamestart_line = QtGui.QLineEdit()
        self.gamestart_line.setText("GameStart")
        gamestart_layout.addWidget(self.gamestart_line)
        self.btn_create_gamestart = QtGui.QPushButton("Crear / Create")
        gamestart_layout.addWidget(self.btn_create_gamestart)
        self.label_gamestart_state = QtGui.QLabel("GameStart no encontrado")
        gamestart_layout.addWidget(self.label_gamestart_state)
        self.btn_create_gamestart.setToolTip("ES: Crea un marcador (cono+base). Sus propiedades definen el Viewpoint inicial.\nEN: Creates a marker (cone+base). Its properties define the initial Viewpoint.")
        layout.addWidget(gamestart_group)

        light_group = QtGui.QGroupBox("Luz global / Global light")
        light_layout = QtGui.QGridLayout(light_group)
        self.chk_global_light = QtGui.QCheckBox("Habilitar / Enable")
        light_layout.addWidget(self.chk_global_light, 0, 0, 1, 2)
        light_layout.addWidget(QtGui.QLabel("Yaw (deg)"), 1, 0)
        self.spin_gl_yaw = QtGui.QDoubleSpinBox()
        self.spin_gl_yaw.setRange(-360.0, 360.0)
        light_layout.addWidget(self.spin_gl_yaw, 1, 1)
        light_layout.addWidget(QtGui.QLabel("Pitch (deg)"), 2, 0)
        self.spin_gl_pitch = QtGui.QDoubleSpinBox()
        self.spin_gl_pitch.setRange(-360.0, 360.0)
        light_layout.addWidget(self.spin_gl_pitch, 2, 1)
        light_layout.addWidget(QtGui.QLabel("Intensidad / Intensity"), 3, 0)
        self.spin_gl_intensity = QtGui.QDoubleSpinBox()
        self.spin_gl_intensity.setRange(0.0, 5.0)
        self.spin_gl_intensity.setSingleStep(0.1)
        light_layout.addWidget(self.spin_gl_intensity, 3, 1)
        self.btn_gl_color = QtGui.QPushButton("Color... / Color...")
        light_layout.addWidget(self.btn_gl_color, 4, 0)
        self.btn_gl_time = QtGui.QPushButton("Hora solar... / Solar time...")
        light_layout.addWidget(self.btn_gl_time, 4, 1)
        self.chk_global_light.setToolTip("ES: DirectionalLight con direccion a partir de yaw/pitch.\nEN: DirectionalLight; direction from yaw/pitch.")
        layout.addWidget(light_group)

        lights_group = QtGui.QGroupBox("Luces de escena / Scene lights")
        lights_layout = QtGui.QVBoxLayout(lights_group)
        self.chk_pointlights = QtGui.QCheckBox("Exportar PointLights / Export point lights")
        lights_layout.addWidget(self.chk_pointlights)
        btn_lights_layout = QtGui.QHBoxLayout()
        self.btn_add_light = QtGui.QPushButton("Agregar seleccion como luz / Add selection as light")
        self.btn_remove_light = QtGui.QPushButton("Quitar seleccion como luz / Remove selection as light")
        btn_lights_layout.addWidget(self.btn_add_light)
        btn_lights_layout.addWidget(self.btn_remove_light)
        lights_layout.addLayout(btn_lights_layout)
        layout.addWidget(lights_group)

        output_group = QtGui.QGroupBox("Salida / Output")
        output_layout = QtGui.QGridLayout(output_group)
        output_layout.addWidget(QtGui.QLabel("Carpeta / Folder"), 0, 0)
        self.output_dir_line = QtGui.QLineEdit()
        output_layout.addWidget(self.output_dir_line, 0, 1)
        self.btn_output_browse = QtGui.QPushButton("Examinar / Browse")
        output_layout.addWidget(self.btn_output_browse, 0, 2)
        output_layout.addWidget(QtGui.QLabel("Nombre base / Base name"), 1, 0)
        self.output_base_line = QtGui.QLineEdit()
        output_layout.addWidget(self.output_base_line, 1, 1, 1, 2)
        self.chk_launch_cge = QtGui.QCheckBox("Lanzar Castle Engine al exportar / Launch CGE after export")
        output_layout.addWidget(self.chk_launch_cge, 2, 0, 1, 3)
        layout.addWidget(output_group)

        self.btn_export = QtGui.QPushButton("Exportar X3D / Export X3D")
        self.btn_export.setToolTip("ES: Exporta a X3D con mm->m y rotacion -90 X; inserta Viewpoint y luces.\nEN: Export to X3D with mm->m and -90 X rotation; inserts Viewpoint and lights.")
        layout.addWidget(self.btn_export)

        footer = QtGui.QLabel(
            "ES: FreeCAD trabaja en mm; el X3D usa metros y aplica rotacion -90 en X. Evita acentos en nombres.\n"
            "EN: FreeCAD works in mm; output X3D uses meters with -90 X rotation. Avoid accents in names."
        )
        footer.setWordWrap(True)
        layout.addWidget(footer)

        layout.addStretch()
        return tab

    def _connect_signals(self):
        """Connect panel actions."""
        self.btn_use_selection.clicked.connect(self._on_use_selection_as_root)
        self.btn_refresh.clicked.connect(self._on_refresh_list)
        self.btn_clear.clicked.connect(self.list_export.clear)
        self.btn_move_right.clicked.connect(lambda: self._move_items(self.list_available, self.list_export))
        self.btn_move_left.clicked.connect(lambda: self._move_items(self.list_export, self.list_available))
        self.btn_use_3d_selection.clicked.connect(self._on_use_3d_selection)

    def _register_shortcuts(self):
        """Register keyboard shortcuts for common actions."""
        self.shortcut_use_3d_selection = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+B"), self.widget)
        self.shortcut_use_3d_selection.setContext(QtCore.Qt.ApplicationShortcut)
        self.shortcut_use_3d_selection.activated.connect(self._on_use_3d_selection)

    def _on_use_selection_as_root(self):
        """Set current selection as root and refresh object list."""
        FreeCAD = __import__("FreeCAD")
        FreeCADGui = __import__("FreeCADGui")
        selection = FreeCADGui.Selection.getSelection()
        if not selection:
            FreeCAD.Console.PrintWarning("[GAMEEXPORT] No selection to set as root\n")
            return

        root = selection[0]
        root_label = getattr(root, "Label", "") or getattr(root, "Name", "")
        self.root_line.setText(root_label)
        FreeCAD.Console.PrintMessage(f"[GAMEEXPORT] Root set from selection: {root_label}\n")
        self._on_refresh_list()

    def _on_refresh_list(self):
        """Refresh available objects from root subtree or active selection."""
        FreeCAD = __import__("FreeCAD")
        FreeCADGui = __import__("FreeCADGui")

        self.list_available.clear()
        self._object_map = {}

        pool = []
        root_label = self.root_line.text().strip()
        doc = getattr(FreeCAD, "ActiveDocument", None)

        if doc and root_label:
            for obj in getattr(doc, "Objects", []):
                if getattr(obj, "Label", "") == root_label:
                    pool = self._collect_subtree(obj)
                    break

        if not pool:
            selection = FreeCADGui.Selection.getSelection()
            for obj in selection:
                pool.extend(self._collect_subtree(obj))

        dedup = []
        seen = set()
        for obj in pool:
            name = getattr(obj, "Name", "")
            if name and name not in seen:
                seen.add(name)
                dedup.append(obj)

        for obj in dedup:
            label = getattr(obj, "Label", "") or getattr(obj, "Name", "")
            self._object_map[label] = obj
            self.list_available.addItem(label)

        FreeCAD.Console.PrintMessage(f"[GAMEEXPORT] Refreshed available objects: {len(dedup)}\n")

    def _collect_subtree(self, obj):
        """Collect object and OutList subtree."""
        items = [obj]
        for child in getattr(obj, "OutList", []) or []:
            items.extend(self._collect_subtree(child))
        return items

    def _on_use_3d_selection(self):
        """Add current 3D selection directly into the export list."""
        FreeCAD = __import__("FreeCAD")
        FreeCADGui = __import__("FreeCADGui")
        selection = FreeCADGui.Selection.getSelection()
        if not selection:
            FreeCAD.Console.PrintWarning("[GAMEEXPORT] No 3D selection to add to export list\n")
            return

        added = 0
        export_items = {self.list_export.item(i).text() for i in range(self.list_export.count())}
        for obj in selection:
            label = getattr(obj, "Label", "") or getattr(obj, "Name", "")
            if label not in export_items:
                self.list_export.addItem(label)
                export_items.add(label)
                self._object_map[label] = obj
                added += 1

        FreeCAD.Console.PrintMessage(f"[GAMEEXPORT] Added {added} selected objects to export list\n")

    def _move_items(self, source, target):
        """Move selected list items between list widgets without duplicates."""
        target_text = {target.item(i).text() for i in range(target.count())}
        selected = source.selectedItems()
        for item in selected:
            text = item.text()
            if text not in target_text:
                target.addItem(text)
                target_text.add(text)
            source.takeItem(source.row(item))

    def _apply_output_defaults(self):
        """Populate output folder and base name from the active document when possible."""
        FreeCAD = __import__("FreeCAD")
        doc = getattr(FreeCAD, "ActiveDocument", None)
        if not doc:
            FreeCAD.Console.PrintMessage("[GAMEEXPORT] No active document; output defaults not set\n")
            return

        filename = getattr(doc, "FileName", "") or ""
        label = getattr(doc, "Label", "") or ""
        folder = os.path.dirname(filename) if filename else ""
        base = os.path.splitext(os.path.basename(filename))[0] if filename else label

        if not self.output_dir_line.text() and folder:
            self.output_dir_line.setText(folder)
            FreeCAD.Console.PrintMessage(f"[GAMEEXPORT] Output folder default set to {folder}\n")

        if not self.output_base_line.text() and base:
            self.output_base_line.setText(base)
            FreeCAD.Console.PrintMessage(f"[GAMEEXPORT] Output base name default set to {base}\n")

        if not folder and not base:
            FreeCAD.Console.PrintMessage("[GAMEEXPORT] No defaults could be derived from the document\n")

    def getStandardButtons(self):
        """FreeCAD TaskPanel API: hide standard buttons."""
        return int(QtGui.QDialogButtonBox.Close)

    def accept(self):
        """Handle dialog accept (placeholder)."""
        FreeCAD = __import__("FreeCAD")
        FreeCAD.Console.PrintMessage("[GAMEEXPORT] Accept pressed (no action)\n")

    def reject(self):
        """Handle dialog reject."""
        FreeCAD = __import__("FreeCAD")
        FreeCAD.Console.PrintMessage("[GAMEEXPORT] Reject pressed\n")


__all__ = ["TaskPanel"]
