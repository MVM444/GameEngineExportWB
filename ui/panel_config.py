"""Configuration tab for Game Engine Export WB.

Descripcion rapida: controles de configuracion global y perfiles.
Fecha y hora: 2025-10-13 13:54 UTC.
Instrucciones clave:
- Mantener controles preparados para integracion con persistencia ParamGet.
- Evitar acentos y mantener comentarios claros.
- Proveer tooltips bilingues.
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

from PySide import QtGui


def build_config_tab():
    """Return the configuration QWidget."""
    tab = QtGui.QWidget()
    layout = QtGui.QVBoxLayout(tab)

    info_label = QtGui.QLabel(
        "Salida y nombre base se ajustan en la pestana Escena para evitar duplicacion.\n"
        "Output folder and base name live in the Scene tab to avoid duplication."
    )
    info_label.setWordWrap(True)
    layout.addWidget(info_label)

    cge_group = QtGui.QGroupBox("Castle Engine")
    cge_layout = QtGui.QHBoxLayout(cge_group)
    cge_layout.addWidget(QtGui.QLabel("Ruta ejecutable / Executable path"))
    cge_layout.addStretch()
    layout.addWidget(cge_group)

    path_layout = QtGui.QHBoxLayout()
    cge_layout.addLayout(path_layout)
    path_layout.addWidget(QtGui.QLabel("Ruta / Path"))
    cge_path = QtGui.QLineEdit()
    path_layout.addWidget(cge_path)
    btn_browse = QtGui.QPushButton("Examinar / Browse")
    path_layout.addWidget(btn_browse)
    cge_path.setToolTip("ES: Selecciona el ejecutable de Castle Game Engine.\nEN: Select the Castle Game Engine executable.")

    options_group = QtGui.QGroupBox("Opciones globales / Global options")
    options_layout = QtGui.QVBoxLayout(options_group)
    chk_triangulate = QtGui.QCheckBox("Triangular mallas / Triangulate meshes")
    chk_freeze = QtGui.QCheckBox("Congelar colores en materiales / Freeze colors")
    chk_restore = QtGui.QCheckBox("Restaurar ultima sesion / Restore last session")
    options_layout.addWidget(chk_triangulate)
    options_layout.addWidget(chk_freeze)
    options_layout.addWidget(chk_restore)
    layout.addWidget(options_group)

    presets_group = QtGui.QGroupBox("Perfiles / Presets")
    presets_layout = QtGui.QVBoxLayout(presets_group)
    name_layout = QtGui.QHBoxLayout()
    name_layout.addWidget(QtGui.QLabel("Nombre / Name"))
    presets_name = QtGui.QLineEdit()
    name_layout.addWidget(presets_name)
    presets_layout.addLayout(name_layout)

    buttons_layout = QtGui.QHBoxLayout()
    btn_save = QtGui.QPushButton("Guardar / Save")
    btn_load = QtGui.QPushButton("Cargar / Load")
    buttons_layout.addWidget(btn_save)
    buttons_layout.addWidget(btn_load)
    presets_layout.addLayout(buttons_layout)

    sidecar_layout = QtGui.QHBoxLayout()
    sidecar_label = QtGui.QLabel("Sidecar: <DocStem>.gee.json")
    btn_force = QtGui.QPushButton("Forzar guardar / Force save")
    sidecar_layout.addWidget(sidecar_label)
    sidecar_layout.addWidget(btn_force)
    presets_layout.addLayout(sidecar_layout)
    layout.addWidget(presets_group)

    layout.addStretch()
    return tab


__all__ = ["build_config_tab"]
