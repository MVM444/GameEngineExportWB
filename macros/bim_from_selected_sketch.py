"""Generic BIM doors/windows from the selected sketch.

This helper is intentionally independent from GameEngineExport quick examples.
The selected sketch must contain line segments representing centerlines of
openings. Both modes create Arch Window objects from generated Sketcher
profiles, matching the BIM/Arch Window command workflow.
"""

from __future__ import annotations

import math
import time

import FreeCAD
import Part

try:
    import FreeCADGui
except Exception:  # pragma: no cover - FreeCAD runtime only
    FreeCADGui = None

try:
    from PySide import QtGui
except Exception:  # pragma: no cover - FreeCAD runtime only
    QtGui = None

try:
    import Arch
except Exception:  # pragma: no cover - FreeCAD runtime only
    Arch = None


LOG_PREFIX = "[BIM-SKETCH] "

DEFAULT_DOOR_HEIGHT = 2100.0
DEFAULT_WINDOW_SILL = 900.0
DEFAULT_WINDOW_HEIGHT = 1200.0
MIN_DEDUCED_WINDOW_HEIGHT = 300.0


def _msg(text):
    FreeCAD.Console.PrintMessage(LOG_PREFIX + str(text) + "\n")


def _warn(text):
    FreeCAD.Console.PrintWarning(LOG_PREFIX + str(text) + "\n")


def _safe_name(text):
    value = str(text).strip()
    for old, new in {
        " ": "_",
        "-": "_",
        "/": "_",
        "\\": "_",
        ".": "_",
        "(": "",
        ")": "",
    }.items():
        value = value.replace(old, new)
    return "".join(ch for ch in value if ch.isalnum() or ch == "_") or "Object"


def _set_prop(obj, prop_type, name, group, desc, value):
    try:
        if not hasattr(obj, name):
            obj.addProperty(prop_type, name, group, desc)
        setattr(obj, name, value)
    except Exception:
        pass


def _set_view(obj, color=None, transparency=None):
    try:
        if color is not None:
            obj.ViewObject.ShapeColor = color
            obj.ViewObject.LineColor = color
        if transparency is not None:
            obj.ViewObject.Transparency = int(transparency)
    except Exception:
        pass


def _selected_sketch():
    if FreeCADGui is None:
        raise RuntimeError("FreeCADGui no esta disponible.")
    selection = list(FreeCADGui.Selection.getSelection() or [])
    sketches = [obj for obj in selection if "Sketch" in str(getattr(obj, "TypeId", ""))]
    if not sketches:
        raise RuntimeError("Seleccione un sketch con lineas de centro para puertas o ventanas.")
    if len(sketches) > 1:
        _warn("Hay varios sketches seleccionados; se usara el primero: " + str(sketches[0].Label))
    return sketches[0]


def _iter_segments(sketch):
    placement = getattr(sketch, "Placement", FreeCAD.Placement())
    for index, geo in enumerate(list(getattr(sketch, "Geometry", []) or [])):
        try:
            if hasattr(sketch, "getConstruction") and sketch.getConstruction(index):
                continue
        except Exception:
            pass
        if not hasattr(geo, "StartPoint") or not hasattr(geo, "EndPoint"):
            continue
        p1 = placement.multVec(geo.StartPoint)
        p2 = placement.multVec(geo.EndPoint)
        if p1.distanceToPoint(p2) > 50.0:
            yield index, p1, p2


def _segment_info(p1, p2):
    dx = p2.x - p1.x
    dy = p2.y - p1.y
    length = math.sqrt(dx * dx + dy * dy)
    if length <= 0.0:
        return None
    return {
        "length": length,
        "horizontal": abs(dx) >= abs(dy),
    }


def _segment_base_z(p1, p2):
    return (float(p1.z) + float(p2.z)) / 2.0


def _world_points(sketch):
    placement = getattr(sketch, "Placement", FreeCAD.Placement())
    points = []
    for geo in list(getattr(sketch, "Geometry", []) or []):
        for attr in ("StartPoint", "EndPoint", "Center"):
            if hasattr(geo, attr):
                try:
                    points.append(placement.multVec(getattr(geo, attr)))
                except Exception:
                    pass
    return points


def _deduce_window_height_from_sketch(sketch):
    points = _world_points(sketch)
    if not points:
        return None
    zs = [float(point.z) for point in points]
    z_span = max(zs) - min(zs)
    if z_span >= MIN_DEDUCED_WINDOW_HEIGHT:
        return z_span
    for attr in ("WindowHeight_mm", "Height_mm", "OpeningHeight_mm"):
        if hasattr(sketch, attr):
            try:
                value = float(getattr(sketch, attr))
                if value > 0:
                    return value
            except Exception:
                pass
    return None


def _ask_window_height(sketch):
    deduced = _deduce_window_height_from_sketch(sketch)
    default_height = float(deduced or DEFAULT_WINDOW_HEIGHT)
    if QtGui is None:
        return default_height, bool(deduced)

    dialog = QtGui.QDialog()
    dialog.setWindowTitle("Ventanas BIM desde sketch")
    layout = QtGui.QVBoxLayout(dialog)
    form = QtGui.QFormLayout()

    height_spin = QtGui.QDoubleSpinBox()
    height_spin.setRange(100.0, 10000.0)
    height_spin.setDecimals(0)
    height_spin.setSingleStep(100.0)
    height_spin.setValue(default_height)
    form.addRow("Altura ventana mm", height_spin)

    deduce_check = QtGui.QCheckBox("Deducir altura del buque si el sketch lo permite")
    deduce_check.setChecked(deduced is not None)
    deduce_check.setEnabled(deduced is not None)
    form.addRow("", deduce_check)

    base_label = QtGui.QLabel("La cota Z del sketch/linea se usara como base o antepecho.")
    form.addRow("", base_label)
    if deduced is not None:
        form.addRow("Altura deducida mm", QtGui.QLabel(str(round(deduced, 1))))

    layout.addLayout(form)
    buttons = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    if dialog.exec_() != QtGui.QDialog.Accepted:
        raise RuntimeError("Operacion cancelada.")
    if deduce_check.isChecked() and deduced is not None:
        return float(deduced), True
    return float(height_spin.value()), False


def _add_rect(sketch, x0, y0, width, height):
    pts = [
        FreeCAD.Vector(x0, y0, 0),
        FreeCAD.Vector(x0 + width, y0, 0),
        FreeCAD.Vector(x0 + width, y0 + height, 0),
        FreeCAD.Vector(x0, y0 + height, 0),
    ]
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
        sketch.addGeometry(Part.LineSegment(pts[a], pts[b]), False)


def _make_profile_sketch(doc, group, name, p1, p2, z0, height, mode, source_sketch, color):
    info = _segment_info(p1, p2)
    if info is None:
        raise RuntimeError("Segmento invalido para crear perfil BIM.")
    length = float(info["length"])
    angle_deg = math.degrees(math.atan2(p2.y - p1.y, p2.x - p1.x))
    profile = doc.addObject("Sketcher::SketchObject", _safe_name(name))
    profile.Label = name

    # Local X follows the buque centerline; local Y is vertical global Z.
    rot_x_to_vertical = FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90)
    rot_z_to_segment = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), angle_deg)
    profile.Placement = FreeCAD.Placement(
        FreeCAD.Vector(p1.x, p1.y, z0),
        rot_z_to_segment.multiply(rot_x_to_vertical),
    )
    _add_rect(profile, 0.0, 0.0, length, height)
    if mode in {"doors", "windows"}:
        inset = max(10.0, min(100.0, length * 0.12, height * 0.12))
        if length > inset * 2.0 and height > inset * 2.0:
            _add_rect(profile, inset, inset, length - inset * 2.0, height - inset * 2.0)

    group.addObject(profile)
    _set_prop(profile, "App::PropertyString", "GEE_Role", "GameEngineExport", "Rol GameEngineExport", "bim_arch_window_profile_sketch")
    _set_prop(profile, "App::PropertyString", "GEE_BIMTool", "GameEngineExport", "Herramienta BIM usada", "Arch_Window")
    _set_prop(profile, "App::PropertyLink", "SourceSketch", "GameEngineExport", "Sketch fuente", source_sketch)
    _set_prop(profile, "App::PropertyFloat", "Width_mm", "GameEngineExport", "Ancho", length)
    _set_prop(profile, "App::PropertyFloat", "Height_mm", "GameEngineExport", "Altura", float(height))
    _set_view(profile, color=color, transparency=0)
    return profile, length


def _window_parts(mode):
    if mode == "doors":
        return [
            "Frame",
            "Frame",
            "Wire0,Wire1",
            "60",
            "0",
            "Door",
            "Solid panel",
            "Wire1,Edge8,Mode1",
            "40",
            "0",
        ]
    return [
        "Frame",
        "Frame",
        "Wire0,Wire1",
        "60",
        "0",
        "Glass",
        "Glass panel",
        "Wire1",
        "10",
        "25",
    ]


def _make_arch_window(doc, group, name, base, role, width, height, sill, open_percent, color, mode):
    if Arch is None or not hasattr(Arch, "makeWindow"):
        raise RuntimeError("Arch.makeWindow no esta disponible. Active el workbench BIM/Arch.")

    parts = _window_parts(mode)
    try:
        obj = Arch.makeWindow(baseobj=base, parts=parts, name=_safe_name(name))
    except TypeError:
        obj = Arch.makeWindow(base, None, None, parts, _safe_name(name))

    group.addObject(obj)
    obj.Label = name
    try:
        obj.Width = float(width)
    except Exception:
        pass
    try:
        obj.Height = float(height)
    except Exception:
        pass
    if mode == "doors":
        try:
            obj.IfcType = "Door"
        except Exception:
            pass
    elif mode == "windows":
        try:
            obj.IfcType = "Window"
        except Exception:
            pass
    _set_prop(obj, "App::PropertyString", "GEE_Role", "GameEngineExport", "Rol GameEngineExport", role)
    _set_prop(obj, "App::PropertyString", "GEE_BIMType", "GameEngineExport", "Tipo BIM", role)
    _set_prop(obj, "App::PropertyString", "GEE_BIMTool", "GameEngineExport", "Herramienta BIM usada", "Arch_Window")
    _set_prop(obj, "App::PropertyLink", "GEE_BaseProfile", "GameEngineExport", "Perfil base", base)
    _set_prop(obj, "App::PropertyFloat", "Height_mm", "GameEngineExport", "Altura", float(height))
    _set_prop(obj, "App::PropertyFloat", "Sill_mm", "GameEngineExport", "Antepecho", float(sill))
    _set_prop(obj, "App::PropertyFloat", "GEE_OpeningPercent", "GameEngineExport", "Apertura porcentual", float(open_percent))
    for attr in ("Opening", "Open", "OpeningPercent"):
        if hasattr(obj, attr):
            try:
                setattr(obj, attr, float(open_percent))
            except Exception:
                pass
    # Keep the BIM object opaque; transparency here affects frames too.
    _set_view(obj, color=color, transparency=0)
    return obj


def _make_group(doc, sketch, mode):
    label = ("BIM_Puertas_desde_" if mode == "doors" else "BIM_Ventanas_desde_") + str(sketch.Name)
    group = doc.addObject("App::DocumentObjectGroup", _safe_name(label + "_" + str(int(time.time()))))
    group.Label = label
    _set_prop(group, "App::PropertyLink", "SourceSketch", "GameEngineExport", "Sketch fuente", sketch)
    _set_prop(group, "App::PropertyString", "GEE_Role", "GameEngineExport", "Rol GameEngineExport", mode + "_from_selected_sketch")
    _set_prop(group, "App::PropertyString", "GEE_BIMTool", "GameEngineExport", "Herramienta BIM usada", "Arch_Window")
    return group


def run(mode):
    if mode not in {"doors", "windows"}:
        raise ValueError("mode debe ser 'doors' o 'windows'")
    doc = FreeCAD.ActiveDocument
    if doc is None:
        raise RuntimeError("No hay documento activo.")
    sketch = _selected_sketch()
    segments = list(_iter_segments(sketch))
    if not segments:
        raise RuntimeError("El sketch seleccionado no tiene lineas validas.")

    window_height = DEFAULT_WINDOW_HEIGHT
    window_height_deduced = False
    if mode == "windows":
        window_height, window_height_deduced = _ask_window_height(sketch)

    transaction_name = "Crear puertas BIM desde sketch" if mode == "doors" else "Crear ventanas BIM desde sketch"
    doc.openTransaction(transaction_name)
    try:
        group = _make_group(doc, sketch, mode)
        if mode == "windows":
            _set_prop(group, "App::PropertyFloat", "WindowHeight_mm", "GameEngineExport", "Altura ventana", float(window_height))
            _set_prop(group, "App::PropertyBool", "WindowHeightDeduced", "GameEngineExport", "Altura deducida", bool(window_height_deduced))
        created = 0
        for index, p1, p2 in segments:
            if mode == "doors":
                z_base = _segment_base_z(p1, p2)
                base, width = _make_profile_sketch(
                    doc,
                    group,
                    "BIM_Door_ArchWindow_Profile_%02d" % (index + 1),
                    p1,
                    p2,
                    z_base,
                    DEFAULT_DOOR_HEIGHT,
                    "doors",
                    sketch,
                    (0.85, 0.35, 0.10),
                )
                doc.recompute()
                opening = _make_arch_window(
                    doc,
                    group,
                    "BIM_Door_Open100_%02d" % (index + 1),
                    base,
                    "bim_door_open_100",
                    width,
                    DEFAULT_DOOR_HEIGHT,
                    z_base,
                    100.0,
                    (0.85, 0.35, 0.10),
                    "doors",
                )
                _set_prop(opening, "App::PropertyLink", "SourceSketch", "GameEngineExport", "Sketch fuente", sketch)
            else:
                sill = _segment_base_z(p1, p2)
                base, width = _make_profile_sketch(
                    doc,
                    group,
                    "BIM_Window_ArchWindow_Profile_%02d" % (index + 1),
                    p1,
                    p2,
                    sill,
                    window_height,
                    "windows",
                    sketch,
                    (0.12, 0.62, 0.88),
                )
                doc.recompute()
                opening = _make_arch_window(
                    doc,
                    group,
                    "BIM_Window_%02d" % (index + 1),
                    base,
                    "bim_window",
                    width,
                    window_height,
                    sill,
                    0.0,
                    (0.12, 0.62, 0.88),
                    "windows",
                )
                _set_prop(opening, "App::PropertyLink", "SourceSketch", "GameEngineExport", "Sketch fuente", sketch)
            created += 1

        doc.recompute()
        doc.commitTransaction()
    except Exception:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise

    if FreeCADGui is not None:
        try:
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(group)
            FreeCADGui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
    _msg("Listo. Modo=%s | Sketch=%s | Elementos=%d | Grupo=%s" % (mode, sketch.Label, created, group.Label))
    return group
