"""Conditional X3D export followed by Castle Game Engine launch.

Descripcion: reutiliza el X3D existente cuando la escena y la configuracion no
han cambiado desde la ultima exportacion. Si detecta cambios, genera un X3D
nuevo antes de lanzar Castle.
Fecha y hora: 2026-08-22 10:58 America/Costa_Rica.
Instrucciones clave:
- Mantener codigo, comentarios y mensajes en ASCII.
- No usar solamente fechas del FCStd: tambien existen cambios sin guardar.
- Guardar la huella de exportacion dentro del sidecar existente del documento.
- Mantener mensajes de depuracion con el prefijo [GAMEEXPORT].
"""

import hashlib
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import FreeCAD
import FreeCADGui

from .. import i18n


ICON_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "resources",
        "icons",
        "export_launch_x3d.svg",
    )
).replace(os.sep, "/")

FINGERPRINT_VERSION = "gameexport-scene-v6-camera-fill"
SIDECAR_CACHE_KEY = "export_launch_cache"
VIEW_PROPERTIES = (
    "Visibility",
    "ShapeColor",
    "LineColor",
    "PointColor",
    "Transparency",
    "DisplayMode",
    "LineWidth",
    "PointSize",
)
# ``ShapeMaterial`` stringifies with a process-local memory address (for
# example ``<Material at 000001...>``), so hashing it forces a false cache miss
# on every panel instance. Visible material state is already represented by
# ViewObject colors/transparency and the explicit GEE material properties.
SKIPPED_PROPERTIES = {"Shape", "Mesh", "Proxy", "ShapeMaterial"}


def _get_open_panel_module():
    module_name = "GameEngineExportWB.commands.cmd_open_panel"
    return sys.modules.get(module_name) or importlib.import_module(module_name)


def _update_hash(digest, value):
    digest.update(str(value).encode("utf-8", errors="replace"))
    digest.update(b"\x00")


def _stable_value(value, depth=0):
    """Convert common FreeCAD values to deterministic JSON-safe data."""
    if depth > 5:
        return str(type(value).__name__)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_stable_value(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _stable_value(value[key], depth + 1)
            for key in sorted(value, key=lambda item: str(item))
        }

    name = getattr(value, "Name", None)
    document = getattr(value, "Document", None)
    if name is not None and document is not None:
        return {
            "document": str(getattr(document, "Name", "") or ""),
            "object": str(name),
        }

    if all(hasattr(value, axis) for axis in ("x", "y", "z")):
        return [float(value.x), float(value.y), float(value.z)]

    numeric_value = getattr(value, "Value", None)
    if isinstance(numeric_value, (int, float)):
        return {
            "value": float(numeric_value),
            "unit": str(getattr(value, "Unit", "") or ""),
        }

    text = str(value)
    if " at 0x" in text:
        return str(type(value).__name__)
    return text


def _placement_data(placement):
    if placement is None:
        return None
    base = getattr(placement, "Base", None)
    rotation = getattr(placement, "Rotation", None)
    quaternion = getattr(rotation, "Q", None)
    return {
        "base": [
            float(getattr(base, "x", 0.0)),
            float(getattr(base, "y", 0.0)),
            float(getattr(base, "z", 0.0)),
        ],
        "rotation_q": [float(value) for value in quaternion]
        if quaternion is not None
        else str(rotation or ""),
    }


def _linked_geometry_source(obj):
    source = obj
    visited = set()
    while source is not None and id(source) not in visited:
        visited.add(id(source))
        linked = getattr(source, "LinkedObject", None)
        if linked is None:
            break
        source = linked
    return source or obj


def _shape_digest(obj, cache):
    source = _linked_geometry_source(obj)
    source_doc = getattr(getattr(source, "Document", None), "Name", "")
    cache_key = (str(source_doc or ""), str(getattr(source, "Name", "") or ""))
    if cache_key in cache:
        return cache[cache_key]

    shape = getattr(source, "Shape", None)
    if shape is None:
        shape = getattr(obj, "Shape", None)
    if shape is None or bool(getattr(shape, "isNull", lambda: True)()):
        cache[cache_key] = ""
        return ""

    geometry_hash = hashlib.sha256()
    try:
        brep = shape.exportBrepToString()
        geometry_hash.update(str(brep).encode("utf-8", errors="replace"))
    except Exception:
        bbox = getattr(shape, "BoundBox", None)
        fallback = {
            "bbox": [
                float(getattr(bbox, key, 0.0))
                for key in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax")
            ],
            "volume": float(getattr(shape, "Volume", 0.0) or 0.0),
            "area": float(getattr(shape, "Area", 0.0) or 0.0),
            "length": float(getattr(shape, "Length", 0.0) or 0.0),
            "vertices": len(getattr(shape, "Vertexes", []) or []),
            "edges": len(getattr(shape, "Edges", []) or []),
            "faces": len(getattr(shape, "Faces", []) or []),
            "solids": len(getattr(shape, "Solids", []) or []),
        }
        geometry_hash.update(
            json.dumps(fallback, sort_keys=True, separators=(",", ":")).encode("ascii")
        )
    result = geometry_hash.hexdigest()
    cache[cache_key] = result
    return result


def _mesh_digest(obj, cache):
    source = _linked_geometry_source(obj)
    source_doc = getattr(getattr(source, "Document", None), "Name", "")
    cache_key = (str(source_doc or ""), str(getattr(source, "Name", "") or ""))
    if cache_key in cache:
        return cache[cache_key]

    mesh = getattr(source, "Mesh", None)
    if mesh is None:
        mesh = getattr(obj, "Mesh", None)
    if mesh is None:
        cache[cache_key] = ""
        return ""

    mesh_hash = hashlib.sha256()
    try:
        topology = getattr(mesh, "Topology")
        mesh_hash.update(repr(topology).encode("utf-8", errors="replace"))
    except Exception:
        bbox = getattr(mesh, "BoundBox", None)
        fallback = {
            "bbox": [
                float(getattr(bbox, key, 0.0))
                for key in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax")
            ],
            "points": int(getattr(mesh, "CountPoints", 0) or 0),
            "facets": int(getattr(mesh, "CountFacets", 0) or 0),
        }
        mesh_hash.update(
            json.dumps(fallback, sort_keys=True, separators=(",", ":")).encode("ascii")
        )
    result = mesh_hash.hexdigest()
    cache[cache_key] = result
    return result


def _object_fingerprint_data(obj, panel_module, shape_cache, mesh_cache):
    properties = {}
    for prop_name in sorted(getattr(obj, "PropertiesList", []) or []):
        if prop_name in SKIPPED_PROPERTIES:
            continue
        try:
            value = obj.getPropertyByName(prop_name)
            properties[prop_name] = _stable_value(value)
        except Exception:
            continue

    view_data = {}
    view_object = getattr(obj, "ViewObject", None)
    if view_object is not None:
        for prop_name in VIEW_PROPERTIES:
            try:
                view_data[prop_name] = _stable_value(getattr(view_object, prop_name))
            except Exception:
                continue

    try:
        global_placement = panel_module.lights.get_global_placement(obj)
    except Exception:
        global_placement = getattr(obj, "Placement", None)

    return {
        "name": str(getattr(obj, "Name", "") or ""),
        "label": str(getattr(obj, "Label", "") or ""),
        "type_id": str(getattr(obj, "TypeId", "") or ""),
        "global_placement": _placement_data(global_placement),
        "shape": _shape_digest(obj, shape_cache),
        "mesh": _mesh_digest(obj, mesh_cache),
        "properties": properties,
        "view": view_data,
    }


def _panel_settings(panel):
    panel._update_export_names()
    panel._update_light_names()
    settings = {
        "root_names": sorted(str(name) for name in panel.root_names),
        "export_names": sorted(str(name) for name in panel.export_names),
        "scene_lights": sorted(str(name) for name in panel.light_names),
        "gamestart_label": panel.gamestart_line.text().strip() or "GameStart",
        "automatic_3d_scene": bool(panel.chk_automatic_3d_scene.isChecked()),
        "include_hidden_3d_objects": bool(
            panel.chk_include_hidden_3d_objects.isChecked()
        ),
        "export_pointlights": bool(panel.chk_pointlights.isChecked()),
        "auto_detect_luminaires": bool(panel.chk_auto_detect_luminaires.isChecked()),
        "global_light": panel._global_light_config(),
        "navigation": panel._navigation_config(),
        "materials": panel._material_lighting_config(),
        "environment": panel._environment_config_for_sidecar(),
        "point_light_options": panel._point_light_options_config(),
        "ground_texture": panel._ground_texture_config(),
        "geometry_export": panel._geometry_export_config(),
    }
    return _stable_value(settings)


def _scene_fingerprint(panel, panel_module):
    doc = FreeCAD.ActiveDocument
    if doc is None:
        raise RuntimeError("No active document")

    gamestart_label = panel.gamestart_line.text().strip() or "GameStart"
    gamestart_obj = panel_module.gamestart.find_gamestart(doc, gamestart_label)
    export_objects = panel._collect_export_objects(doc, gamestart_obj)
    if not export_objects:
        raise RuntimeError("No geometry selected for export")

    digest = hashlib.sha256()
    _update_hash(digest, FINGERPRINT_VERSION)
    _update_hash(digest, getattr(doc, "Name", ""))
    _update_hash(digest, getattr(doc, "Label", ""))
    _update_hash(
        digest,
        json.dumps(_panel_settings(panel), sort_keys=True, separators=(",", ":")),
    )

    if gamestart_obj is not None:
        metadata = panel_module.gamestart.get_metadata(gamestart_obj)
        _update_hash(
            digest,
            json.dumps(_stable_value(metadata), sort_keys=True, separators=(",", ":")),
        )

    shape_cache = {}
    mesh_cache = {}
    for obj in sorted(export_objects, key=lambda item: str(getattr(item, "Name", ""))):
        payload = _object_fingerprint_data(
            obj, panel_module, shape_cache, mesh_cache
        )
        _update_hash(
            digest,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )

    FreeCAD.Console.PrintMessage(
        "[GAMEEXPORT] Scene fingerprint calculated for "
        + str(len(export_objects))
        + " objects\n"
    )
    return digest.hexdigest()


def _current_x3d_path(panel, panel_module):
    output_dir = panel.output_dir_line.text().strip()
    base_name = panel.base_name_line.text().strip()
    doc = FreeCAD.ActiveDocument
    if not output_dir or doc is None:
        return None
    if not base_name:
        base_name = str(getattr(doc, "Label", "") or getattr(doc, "Name", "Scene"))
    safe_name = panel_module.normalize_base_name(base_name)
    return Path(output_dir) / (safe_name + ".x3d")


def _same_path(left, right):
    if not left or not right:
        return False
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def _cache_matches(panel, panel_module, x3d_path, fingerprint):
    if x3d_path is None or not x3d_path.is_file():
        return False, "X3D file does not exist"
    data = panel.sidecar_data if isinstance(panel.sidecar_data, dict) else {}
    cache = data.get(SIDECAR_CACHE_KEY)
    if not isinstance(cache, dict):
        return False, "no previous fingerprint"
    if cache.get("version") != FINGERPRINT_VERSION:
        return False, "fingerprint version changed"
    if not _same_path(cache.get("x3d_path"), x3d_path):
        return False, "X3D output path changed"
    try:
        stat = x3d_path.stat()
    except OSError:
        return False, "X3D file cannot be inspected"
    if int(cache.get("x3d_size", -1)) != int(stat.st_size):
        return False, "X3D file size changed"
    if int(cache.get("x3d_mtime_ns", -1)) != int(stat.st_mtime_ns):
        return False, "X3D file timestamp changed"
    if cache.get("fingerprint") != fingerprint:
        return False, "model or export configuration changed"
    return True, "model and export configuration are unchanged"


def _save_export_cache(panel, panel_module, x3d_path, fingerprint):
    if panel.doc_path is None or x3d_path is None or not x3d_path.is_file():
        FreeCAD.Console.PrintWarning(
            "[GAMEEXPORT][WARN] Export fingerprint was not saved\n"
        )
        return
    stat = x3d_path.stat()
    data = panel_module.persist.load_sidecar(panel.doc_path) or {}
    data[SIDECAR_CACHE_KEY] = {
        "version": FINGERPRINT_VERSION,
        "fingerprint": fingerprint,
        "x3d_path": str(x3d_path),
        "x3d_size": int(stat.st_size),
        "x3d_mtime_ns": int(stat.st_mtime_ns),
        "saved_utc": datetime.now(timezone.utc).isoformat(),
    }
    panel_module.persist.save_sidecar(panel.doc_path, data)
    panel.sidecar_data = data
    FreeCAD.Console.PrintMessage(
        "[GAMEEXPORT] Export fingerprint saved in document sidecar\n"
    )


class CommandClass:
    """Reuse a valid X3D or export again, then launch Castle."""

    CommandName = "GameEngineExport_ExportAndLaunch"

    def GetResources(self):  # noqa: N802
        return {
            "MenuText": i18n.bi("Exportar X3D y lanzar Castle", "Export X3D and launch Castle"),
            "ToolTip": i18n.bi(
                "Si el modelo no cambio, abre el X3D existente en Castle. Si cambio, genera un X3D nuevo antes de abrirlo.",
                "If the model did not change, open the existing X3D in Castle. If it changed, generate a new X3D first.",
            ),
            "Pixmap": ICON_PATH,
        }

    def Activated(self):  # noqa: N802
        FreeCAD.Console.PrintMessage(
            "[GAMEEXPORT] Conditional X3D export and Castle launch requested\n"
        )
        try:
            if (
                hasattr(FreeCADGui.Control, "activeDialog")
                and FreeCADGui.Control.activeDialog()
            ):
                FreeCADGui.Control.closeDialog()
        except Exception as exc:
            FreeCAD.Console.PrintWarning(
                "[GAMEEXPORT][WARN] Could not close active dialog: "
                + str(exc)
                + "\n"
            )

        try:
            open_panel = _get_open_panel_module()
            panel_module = open_panel._reload_export_runtime()
            panel = panel_module.ExportTaskPanel()
        except Exception as exc:
            FreeCAD.Console.PrintError(
                "[GAMEEXPORT] Could not prepare one-click export: "
                + str(exc)
                + "\n"
            )
            return

        if not panel._ensure_castle_executable(prompt_if_missing=True):
            return

        x3d_path = _current_x3d_path(panel, panel_module)
        try:
            fingerprint = _scene_fingerprint(panel, panel_module)
        except Exception as exc:
            FreeCAD.Console.PrintWarning(
                "[GAMEEXPORT][WARN] Could not calculate scene fingerprint: "
                + str(exc)
                + ". A new X3D will be generated.\n"
            )
            fingerprint = ""

        cache_matches = False
        cache_reason = "fingerprint unavailable"
        if fingerprint:
            cache_matches, cache_reason = _cache_matches(
                panel, panel_module, x3d_path, fingerprint
            )

        if cache_matches:
            FreeCAD.Console.PrintMessage(
                "[GAMEEXPORT] No changes detected; reusing existing X3D: "
                + x3d_path.name
                + "\n"
            )
            panel._launch_castle_engine(str(x3d_path))
            return

        FreeCAD.Console.PrintMessage(
            "[GAMEEXPORT] New export required: " + cache_reason + "\n"
        )
        panel.launch_checkbox.setChecked(True)
        if not panel._export_scene():
            return

        x3d_path = _current_x3d_path(panel, panel_module)
        try:
            fingerprint = _scene_fingerprint(panel, panel_module)
            _save_export_cache(panel, panel_module, x3d_path, fingerprint)
        except Exception as exc:
            FreeCAD.Console.PrintWarning(
                "[GAMEEXPORT][WARN] Export completed but its fingerprint could not be saved: "
                + str(exc)
                + "\n"
            )

        FreeCAD.Console.PrintMessage(
            "[GAMEEXPORT] Conditional X3D export and Castle launch completed\n"
        )

    def IsActive(self):  # noqa: N802
        return FreeCAD.ActiveDocument is not None
