"""X3D exporter helpers for Game Engine Export WB.

Descripcion rapida: exporta via FreeCADGui y aplica conversion fija de ejes.
Fecha y hora: 2026-03-11 17:50 UTC.
Instrucciones clave:
- Mantener logs con prefijo [GAMEEXPORT].
- Aplicar siempre mm->m (0.001) y rotacion -90 en X para pasar Z-up a Y-up.
- Soportar salida X3D comprimida (gzip) sin romper decode UTF-8.
"""

from __future__ import annotations

import gzip
import hashlib
import math
import re
import shutil
import unicodedata
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import xml.etree.ElementTree as ET

from . import material_assignments


LOG_PREFIX = "[GAMEEXPORT] "
DEBUG_VERSION = "2026-08-19-object-materials-mirror-v1"
SCALE_VECTOR = "0.001 0.001 0.001"
ROTATION_VECTOR = "1 0 0 -1.57079632679"
TRANSFORM_DEF = "FreeCAD_mm_to_m"
X3D_DOCTYPE = '<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 3.2//EN" "http://www.web3d.org/specifications/x3d-3.2.dtd">'
DEFAULT_NAV_SPEED = 2.0
DEFAULT_EYE_HEIGHT_MM = 1600.0
DEFAULT_STEP_HEIGHT_MM = 350.0
DEFAULT_GROUND_ELEVATION_MM = 0.0
DEFAULT_GROUND_MARGIN_MM = 1000.0
DEFAULT_GROUND_THICKNESS_MM = 200.0
GROUND_COLLISION_DEF = "GameExport_WalkGroundCollision"
LIGHT_DEF_PREFIX = "GameExport_"
DEFAULT_POINT_LIGHT_AMBIENT_INTENSITY = 0.18
MAX_POINT_LIGHT_SHADOWS = 4
MAX_SPOT_LIGHT_SHADOWS = 4
LIGHT_MODE_SPOT_SHADOW_MAP = "SpotShadowMap"
LIGHT_MODE_SPOT_NO_SHADOWS = "SpotNoShadows"
LIGHT_MODE_POINT_CLASSIC = "PointLightClassic"
LIGHT_MODE_PHOTOMETRIC = "PhotometricSpot"
DEFAULT_SPOT_BEAM_WIDTH = 0.59
DEFAULT_SPOT_CUTOFF_ANGLE = 0.79
DEFAULT_SPOT_SHADOW_MAP_SIZE = 256
DEFAULT_PHOTOMETRIC_LUMENS = 3600.0
DEFAULT_PHOTOMETRIC_BEAM_ANGLE_DEG = 120.0
DEFAULT_PHOTOMETRIC_CCT_K = 4000.0
EMITTER_MATERIAL_DEF_PREFIX = "GameExport_Emitter_"
GROUND_TEXTURE_MATERIAL_DEF_PREFIX = "GameExport_GroundTexture_"
INSTANCE_DEF_PREFIX = "GameExport_Instance_"
DEFAULT_GEOMETRY_EXPORT_MODE = "Optimized"
MIN_INSTANCE_PAYLOAD_CHARS = 2048
GROUND_TEXTURE_FALLBACK_KEYWORDS = (
    ("terrain", 100),
    ("ground", 90),
    ("suelo", 90),
    ("zacate", 90),
    ("cesped", 90),
    ("grass", 90),
    ("site", 60),
    ("floor", 45),
    ("slab", 45),
    ("piso", 45),
)
MATERIAL_LIGHTING_PROFILES = {
    "Soft": {
        "ambientIntensity": "0.35",
        # Default X3D diffuseColor is 0.8, so this keeps approximately the
        # former 0.06 visible lift while preserving the source hue.
        "emissiveFactor": 0.075,
        "shininess": "0.10",
    },
    "Architectural": {
        "ambientIntensity": "0.50",
        "emissiveFactor": 0.15,
        "shininess": "0.10",
    },
    "Bright": {
        "ambientIntensity": "0.65",
        "emissiveFactor": 0.225,
        "shininess": "0.05",
    },
}
MATERIAL_TAG_RE = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?Material\b[^>]*>")
MATERIAL_PROFILE_ATTR_RE = re.compile(
    r"\s+(?:ambientIntensity|emissiveColor|shininess)\s*=\s*(?:\"[^\"]*\"|'[^']*')"
)
MATERIAL_DIFFUSE_COLOR_RE = re.compile(
    r"\bdiffuseColor\s*=\s*([\"'])([^\"']+)\1"
)
MATERIAL_USE_RE = re.compile(r"\bUSE\s*=\s*([\"'])[^\"']+\1")
SKYBOX_FACE_SUFFIXES = {
    "backUrl": "back",
    "bottomUrl": "bottom",
    "frontUrl": "front",
    "leftUrl": "left",
    "rightUrl": "right",
    "topUrl": "top",
}
SKYBOX_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PLANAR_HELPER_KEYWORDS = (
    "(plano)",
    "_plano",
    "2d symbol",
    "simbolo 2d",
    "symbol2d",
    "simbolo2d",
    "_2d",
    "2d_",
    "info2d",
)
INTERNAL_CONTAINER_KEYWORDS = (
    " master",
    "masters",
    "library",
    "biblioteca",
    "_lib",
    "lib_",
    " internal",
    "interno",
    "reference",
    "referencia",
    "prototype",
    "prototipo",
    "catalog",
    "catalogo",
)


def export_to_x3d(
    objects: Iterable[object],
    output_path: Path,
    gamestart_meta: Optional[Dict[str, object]] = None,
    lighting_cfg: Optional[Dict[str, object]] = None,
    material_cfg: Optional[Dict[str, object]] = None,
    environment_cfg: Optional[Dict[str, object]] = None,
    ground_texture_cfg: Optional[Dict[str, object]] = None,
    geometry_export_cfg: Optional[Dict[str, object]] = None,
) -> Path:
    """Export selected objects to X3D and run postprocessing."""
    FreeCAD = __import__("FreeCAD")
    FreeCADGui = __import__("FreeCADGui")

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    object_list = [obj for obj in objects if obj is not None]
    if not object_list:
        raise ValueError("No objects provided for export")

    diag = diagnose_export_candidates(object_list, log=True)
    exportable = diag["exportable"]
    skipped = diag["skipped"]

    if not exportable:
        raise ValueError("No exportable geometry found in selection")

    FreeCAD.Console.PrintMessage(
        LOG_PREFIX + f"Exporting {len(exportable)} objects to {out_path.name}\n"
    )
    export_function = getattr(FreeCADGui, "export", None)
    export_backend = "FreeCADGui.export"
    if not callable(export_function):
        ImportGui = __import__("ImportGui")
        export_function = ImportGui.export
        export_backend = "ImportGui.export"
    FreeCAD.Console.PrintMessage(LOG_PREFIX + "X3D export backend: " + export_backend + "\n")
    with _temporary_export_visibility(exportable):
        export_function(exportable, str(out_path))
    prepared_material_cfg = _material_cfg_with_light_source_indices(material_cfg, exportable)
    prepared_material_cfg = _material_cfg_with_object_assignments(prepared_material_cfg, exportable)
    decorate_x3d(
        out_path,
        gamestart_meta,
        lighting_cfg,
        prepared_material_cfg,
        environment_cfg,
        _ground_texture_cfg_with_object_indices(ground_texture_cfg, exportable),
        geometry_export_cfg,
    )
    return out_path


def diagnose_export_candidates(
    objects: Iterable[object], log: bool = False, max_rows: int = 25
) -> Dict[str, object]:
    """Return exportability diagnostics for the provided objects."""
    object_list = [obj for obj in objects if obj is not None]
    exportable, skipped = _split_exportables(object_list)
    if log and skipped:
        _log_skipped_objects(skipped, max_rows=max_rows)
    return {
        "total": len(object_list),
        "exportable": exportable,
        "skipped": skipped,
    }


@contextmanager
def _temporary_export_visibility(objects: Iterable[object]):
    """Expose selected geometry during export and restore every view state.

    FreeCAD GUI exporters can omit an explicitly supplied object when its
    ViewObject or a parent group is hidden. Device links often live in hidden
    drafting groups, so the export must temporarily expose the complete parent
    chain. Only GUI visibility changes in memory; document properties and the
    FCStd file are not saved or modified.
    """
    changed = []
    seen = set()
    candidates = []
    documents = []

    def add_candidate(obj) -> None:
        if obj is None or id(obj) in seen:
            return
        seen.add(id(obj))
        candidates.append(obj)
        for parent in list(getattr(obj, "InList", []) or []):
            add_candidate(parent)

    for obj in list(objects or []):
        add_candidate(obj)

    for obj in candidates:
        doc = getattr(obj, "Document", None)
        if doc is not None and all(doc is not known for known in documents):
            documents.append(doc)

    snapshot_objects = []
    for doc in documents:
        snapshot_objects.extend(list(getattr(doc, "Objects", []) or []))
    if not snapshot_objects:
        snapshot_objects = list(candidates)

    visibility_snapshot = []
    snapshot_seen = set()
    for obj in snapshot_objects:
        if obj is None or id(obj) in snapshot_seen:
            continue
        snapshot_seen.add(id(obj))
        view = getattr(obj, "ViewObject", None)
        if view is None or not hasattr(view, "Visibility"):
            continue
        try:
            visibility_snapshot.append((view, bool(view.Visibility)))
        except Exception:
            continue

    try:
        for obj in candidates:
            view = getattr(obj, "ViewObject", None)
            if view is None or not hasattr(view, "Visibility"):
                continue
            try:
                original = bool(view.Visibility)
                if not original:
                    view.Visibility = True
                    changed.append((view, original, str(getattr(obj, "Name", "") or "Unknown")))
            except Exception:
                continue
        if changed:
            FreeCAD = __import__("FreeCAD")
            FreeCAD.Console.PrintMessage(
                LOG_PREFIX
                + "Temporary export visibility enabled: "
                + str(len(changed))
                + " objects/groups\n"
            )
        yield
    finally:
        # Parent group visibility can change child states as a side effect.
        # Repeat restoration passes over the complete document snapshot until
        # every direct ViewObject.Visibility value matches its original value.
        for _pass_index in range(5):
            restore_count = 0
            for view, original in visibility_snapshot:
                try:
                    if bool(view.Visibility) != original:
                        view.Visibility = original
                        restore_count += 1
                except Exception:
                    pass
            if restore_count == 0:
                break
        if changed:
            try:
                FreeCAD = __import__("FreeCAD")
                FreeCAD.Console.PrintMessage(
                    LOG_PREFIX
                    + "Temporary export visibility restored: "
                    + str(len(changed))
                    + " objects/groups\n"
                )
            except Exception:
                pass


def collect_default_scene_objects(
    doc,
    excluded_objects: Optional[Iterable[object]] = None,
    include_hidden_objects: bool = True,
    include_hidden_links: Optional[bool] = None,
) -> List[object]:
    """Collect a reusable default 3D scene without relying on object names.

    Visible exportable geometry is always included. Hidden objects with a real
    solid or mesh are included when requested because projects commonly hide
    ceilings, columns, device groups or furniture while keeping them part of
    the deliverable. Linked library masters remain excluded to avoid duplicate
    geometry.

    GameExportInclude and GameExportExclude boolean properties provide explicit
    per-object overrides when a document needs a special case.
    """
    if doc is None:
        return []
    if include_hidden_links is not None:
        # Backward-compatible alias used by Workbench versions before the
        # policy expanded from linked instances to every hidden 3D object.
        include_hidden_objects = bool(include_hidden_links)
    excluded_ids = {id(obj) for obj in list(excluded_objects or []) if obj is not None}
    objects = list(getattr(doc, "Objects", []) or [])
    linked_master_ids = _linked_master_ids(objects)
    selected = []
    skipped_2d = 0
    skipped_hidden = 0
    skipped_masters = 0
    skipped_internal = 0
    selected_hidden_objects = 0
    selected_forced = 0
    skipped_forced = 0

    for obj in objects:
        if obj is None or id(obj) in excluded_ids:
            continue
        override = _object_export_override(obj)
        if override is False:
            skipped_forced += 1
            continue
        if id(obj) in linked_master_ids and override is not True:
            skipped_masters += 1
            continue
        if _is_internal_container_member(obj) and override is not True:
            skipped_internal += 1
            continue
        ok, reason = _is_exportable_object(obj)
        if not ok:
            if "2D" in reason or "planar" in reason or "wire" in reason:
                skipped_2d += 1
            continue
        if override is True:
            selected.append(obj)
            selected_forced += 1
            continue
        if not _is_object_visible(obj):
            if include_hidden_objects and _has_solid_or_mesh_geometry(obj):
                selected.append(obj)
                selected_hidden_objects += 1
                continue
            skipped_hidden += 1
            continue
        selected.append(obj)

    FreeCAD = __import__("FreeCAD")
    FreeCAD.Console.PrintMessage(
        LOG_PREFIX
        + "Default 3D scene selection: selected="
        + str(len(selected))
        + ", skipped_2d="
        + str(skipped_2d)
        + ", skipped_hidden="
        + str(skipped_hidden)
        + ", skipped_linked_masters="
        + str(skipped_masters)
        + ", skipped_internal_library="
        + str(skipped_internal)
        + ", selected_hidden_3d_objects="
        + str(selected_hidden_objects)
        + ", selected_forced="
        + str(selected_forced)
        + ", skipped_forced="
        + str(skipped_forced)
        + "\n"
    )
    return selected


def complete_scene_objects_with_hidden_3d(
    doc,
    selected_objects: Optional[Iterable[object]] = None,
    excluded_objects: Optional[Iterable[object]] = None,
) -> List[object]:
    """Append valid hidden 3D geometry to an explicit scene selection.

    Saved sidecars often contain an explicit export list. That list must not
    disable scene completion because ceilings, columns and equipment may have
    been hidden after the list was created. Existing explicit entries remain
    untouched and only hidden candidates from the reusable default policy are
    appended.
    """
    excluded_ids = {
        id(obj) for obj in list(excluded_objects or []) if obj is not None
    }
    completed = []
    seen_ids = set()
    for obj in list(selected_objects or []):
        if obj is None or id(obj) in excluded_ids or id(obj) in seen_ids:
            continue
        completed.append(obj)
        seen_ids.add(id(obj))

    appended = 0
    candidates = collect_default_scene_objects(
        doc,
        excluded_objects=excluded_objects,
        include_hidden_objects=True,
    )
    for obj in candidates:
        if id(obj) in seen_ids or _is_object_visible(obj):
            continue
        completed.append(obj)
        seen_ids.add(id(obj))
        appended += 1

    FreeCAD = __import__("FreeCAD")
    FreeCAD.Console.PrintMessage(
        LOG_PREFIX
        + "Explicit scene completion: base="
        + str(len(completed) - appended)
        + ", hidden_3d_added="
        + str(appended)
        + ", total="
        + str(len(completed))
        + "\n"
    )
    return completed


def resolve_scene_objects(
    doc,
    selected_objects: Optional[Iterable[object]] = None,
    excluded_objects: Optional[Iterable[object]] = None,
    automatic_3d_scene: bool = True,
    include_hidden_objects: bool = True,
) -> List[object]:
    """Resolve automatic or explicit panel selection through one API."""
    explicit = [obj for obj in list(selected_objects or []) if obj is not None]
    if automatic_3d_scene:
        return collect_default_scene_objects(
            doc,
            excluded_objects=excluded_objects,
            include_hidden_objects=include_hidden_objects,
        )
    if not explicit:
        return collect_default_scene_objects(
            doc,
            excluded_objects=excluded_objects,
            include_hidden_objects=include_hidden_objects,
        )
    if include_hidden_objects:
        return complete_scene_objects_with_hidden_3d(
            doc,
            explicit,
            excluded_objects=excluded_objects,
        )
    excluded_ids = {
        id(obj) for obj in list(excluded_objects or []) if obj is not None
    }
    resolved = []
    seen_ids = set()
    for obj in explicit:
        if id(obj) in excluded_ids or id(obj) in seen_ids:
            continue
        resolved.append(obj)
        seen_ids.add(id(obj))
    return resolved


def decorate_x3d(
    path: Path,
    gamestart_meta: Optional[Dict[str, object]] = None,
    lighting_cfg: Optional[Dict[str, object]] = None,
    material_cfg: Optional[Dict[str, object]] = None,
    environment_cfg: Optional[Dict[str, object]] = None,
    ground_texture_cfg: Optional[Dict[str, object]] = None,
    geometry_export_cfg: Optional[Dict[str, object]] = None,
) -> None:
    """Apply mandatory axis conversion and keep output format (plain/gzip)."""
    FreeCAD = __import__("FreeCAD")

    file_path = Path(path)
    if not file_path.exists():
        FreeCAD.Console.PrintWarning(
            LOG_PREFIX + f"decorate_x3d skipped, file missing: {file_path.name}\n"
        )
        return

    target_gzip = file_path.suffix.lower() == ".x3dz"
    xml_text, was_gzip = _read_x3d_text(file_path)
    if xml_text is None:
        # Fallback: if FreeCAD emitted gzip into .x3d, always convert to plain XML bytes.
        if was_gzip and not target_gzip:
            _force_gzip_to_plain(file_path)
        return

    doctype_line = _extract_doctype(xml_text)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        FreeCAD.Console.PrintWarning(LOG_PREFIX + f"decorate_x3d parse failed: {exc}\n")
        if was_gzip and not target_gzip:
            _write_x3d_text(file_path, xml_text, False)
            FreeCAD.Console.PrintWarning(
                LOG_PREFIX + "Wrote plain .x3d after parse warning to avoid invalid-character load errors.\n"
            )
        return

    namespace = _detect_namespace(root.tag)

    def q(tag: str) -> str:
        return f"{{{namespace}}}{tag}" if namespace else tag

    scene = root.find(q("Scene"))
    if scene is None:
        # Fallback in case of unusual root nesting.
        for node in root.iter():
            if _local_name(node.tag) == "Scene":
                scene = node
                break
    if scene is None:
        FreeCAD.Console.PrintWarning(LOG_PREFIX + "decorate_x3d skipped: Scene node not found\n")
        if was_gzip and not target_gzip:
            _write_x3d_text(file_path, xml_text, False)
            FreeCAD.Console.PrintWarning(
                LOG_PREFIX + "Wrote plain .x3d (no Scene found) to avoid invalid-character load errors.\n"
            )
        return

    _ensure_unique_def_names(scene)
    _remove_gameexport_light_nodes(scene)
    _remove_walk_ground_collision(scene, q)
    navigation_cfg = _normalize_navigation_cfg(lighting_cfg)
    _apply_environment_background(scene, q, file_path, environment_cfg)
    _ensure_navigation(scene, q, navigation_cfg)
    _apply_mm_to_m_axis_transform(scene, q)
    _ensure_walk_ground_collision(scene, q, navigation_cfg)
    _insert_viewpoint(scene, q, gamestart_meta, navigation_cfg)
    light_count = _insert_lights(scene, q, lighting_cfg)
    emitter_material_count = _apply_light_source_emissive_materials(scene, q, material_cfg)
    object_material_count = _apply_object_material_assignments(scene, q, file_path, material_cfg)
    ground_texture_count = _apply_ground_texture(scene, q, file_path, ground_texture_cfg)

    if gamestart_meta or lighting_cfg:
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Decoration note: GameStart/lights metadata received; axis conversion applied."
            + f" Lights inserted: {light_count}\n"
        )
    if emitter_material_count > 0:
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Applied emissive source materials to light geometry: "
            + str(emitter_material_count)
            + " Material nodes\n"
        )
    if object_material_count > 0:
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Applied object material/texture effects: "
            + str(object_material_count)
            + " Shape nodes\n"
        )
    if ground_texture_count > 0:
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Applied legacy ground texture to exported object: "
            + str(ground_texture_count)
            + " Shape nodes\n"
        )

    instance_count = _apply_geometry_export_mode(
        scene,
        q,
        geometry_export_cfg,
    )
    if instance_count > 0:
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Optimized repeated X3D geometry with DEF/USE: "
            + str(instance_count)
            + " repeated nodes replaced\n"
        )

    xml_out = _serialize_xml(root, doctype_line)
    mode = _material_lighting_mode_from_cfg(material_cfg)
    if light_count > 0 and mode == "None":
        FreeCAD.Console.PrintWarning(
            "[GAMEEXPORT][WARN] X3D lights were inserted but interior material profile is disabled. "
            "Enable Materiales X3D / X3D Materials with Soft, Architectural, or Bright if lighting is not visible.\n"
        )
    if mode != "None":
        xml_out, material_count = apply_x3d_material_lighting_profile(xml_out, mode)
        if material_count == 0:
            FreeCAD.Console.PrintWarning(
                "[GAMEEXPORT][WARN] No X3D Material nodes found for interior lighting profile.\n"
            )
        else:
            FreeCAD.Console.PrintMessage(
                LOG_PREFIX
                + f"Applied X3D material lighting profile: {mode} ({material_count} Material nodes)\n"
            )

    if was_gzip and not target_gzip:
        FreeCAD.Console.PrintWarning(
            LOG_PREFIX + "Input payload is gzip but extension is .x3d; writing plain XML to keep parser compatibility.\n"
        )
    elif (not was_gzip) and target_gzip:
        FreeCAD.Console.PrintMessage(LOG_PREFIX + "Target extension .x3dz detected; writing gzip payload.\n")

    _write_x3d_text(file_path, xml_out, target_gzip)
    FreeCAD.Console.PrintMessage(LOG_PREFIX + "Applied axis fix (mm->m + -90X) successfully\n")


def _apply_mm_to_m_axis_transform(scene, q) -> None:
    """Wrap scene geometry into a canonical transform for engine coordinates."""
    preserved = {q("Background"), q("NavigationInfo"), q("Viewpoint")}

    transform = None
    for child in list(scene):
        if child.tag == q("Transform") and child.attrib.get("DEF") == TRANSFORM_DEF:
            transform = child
            break

    if transform is None:
        transform = ET.Element(q("Transform"))
    else:
        scene.remove(transform)

    transform.attrib["DEF"] = TRANSFORM_DEF
    transform.attrib["scale"] = SCALE_VECTOR
    transform.attrib["rotation"] = ROTATION_VECTOR

    for existing in list(transform):
        transform.remove(existing)

    geometry_children = []
    for child in list(scene):
        if child.tag in preserved:
            continue
        scene.remove(child)
        geometry_children.append(child)

    for child in geometry_children:
        transform.append(child)

    # Place transform after preserved config nodes.
    scene.append(transform)


def _normalize_navigation_cfg(lighting_cfg: Optional[Dict[str, object]]) -> Dict[str, object]:
    nav = {}
    if isinstance(lighting_cfg, dict):
        candidate = lighting_cfg.get("navigation")
        if isinstance(candidate, dict):
            nav = candidate
    speed = float(nav.get("speed", DEFAULT_NAV_SPEED))
    eye_height_mm = float(nav.get("eye_height_mm", DEFAULT_EYE_HEIGHT_MM))
    step_height_mm = float(nav.get("step_height_mm", DEFAULT_STEP_HEIGHT_MM))
    ground_elevation_mm = float(
        nav.get("ground_elevation_mm", DEFAULT_GROUND_ELEVATION_MM)
    )
    ground_margin_mm = float(nav.get("ground_margin_mm", DEFAULT_GROUND_MARGIN_MM))
    ground_thickness_mm = float(
        nav.get("ground_thickness_mm", DEFAULT_GROUND_THICKNESS_MM)
    )
    speed = max(0.1, min(10000.0, speed))
    eye_height_mm = max(100.0, min(5000.0, eye_height_mm))
    step_height_mm = max(0.0, min(2000.0, step_height_mm))
    ground_elevation_mm = max(-1000000.0, min(1000000.0, ground_elevation_mm))
    ground_margin_mm = max(0.0, min(100000.0, ground_margin_mm))
    ground_thickness_mm = max(1.0, min(10000.0, ground_thickness_mm))
    return {
        "speed": speed,
        "eye_height_mm": eye_height_mm,
        "step_height_mm": step_height_mm,
        "walk_only": bool(nav.get("walk_only", True)),
        "ground_collision": bool(nav.get("ground_collision", True)),
        "ground_elevation_mm": ground_elevation_mm,
        "ground_margin_mm": ground_margin_mm,
        "ground_thickness_mm": ground_thickness_mm,
    }


def _remove_walk_ground_collision(scene, q) -> None:
    """Remove an earlier generated ground proxy before redecorating the file."""
    for child in list(scene):
        if child.tag == q("Collision") and child.attrib.get("DEF") == GROUND_COLLISION_DEF:
            scene.remove(child)


def _ensure_walk_ground_collision(scene, q, nav_cfg: Dict[str, object]) -> None:
    """Add an invisible flat proxy so WALK terrain-following has a reliable floor.

    FreeCAD exports millimetres with Z-up.  The main scene transform maps this
    to metres with Y-up, so the proxy is emitted directly in final X3D metres.
    It complements the detailed slab and wall collision mesh without being
    rendered.
    """
    _remove_walk_ground_collision(scene, q)
    if not bool(nav_cfg.get("ground_collision", True)):
        return

    transform = None
    for child in list(scene):
        if child.tag == q("Transform") and child.attrib.get("DEF") == TRANSFORM_DEF:
            transform = child
            break
    if transform is None:
        return

    bounds = _freecad_xy_bounds_from_coordinates(transform, q)
    if bounds is None:
        return
    min_x, max_x, min_y, max_y = bounds

    margin_mm = float(nav_cfg.get("ground_margin_mm", DEFAULT_GROUND_MARGIN_MM))
    elevation_mm = float(
        nav_cfg.get("ground_elevation_mm", DEFAULT_GROUND_ELEVATION_MM)
    )
    thickness_mm = float(
        nav_cfg.get("ground_thickness_mm", DEFAULT_GROUND_THICKNESS_MM)
    )
    size_x_m = max(0.001, (max_x - min_x + 2.0 * margin_mm) * 0.001)
    size_z_m = max(0.001, (max_y - min_y + 2.0 * margin_mm) * 0.001)
    thickness_m = max(0.001, thickness_mm * 0.001)
    center_x_m = (min_x + max_x) * 0.0005
    center_z_m = -(min_y + max_y) * 0.0005
    center_y_m = elevation_mm * 0.001 - thickness_m * 0.5

    collision = ET.Element(
        q("Collision"), {"DEF": GROUND_COLLISION_DEF, "enabled": "true"}
    )
    proxy = ET.SubElement(
        collision,
        q("Transform"),
        {
            "containerField": "proxy",
            "translation": _format_vec((center_x_m, center_y_m, center_z_m)),
        },
    )
    shape = ET.SubElement(proxy, q("Shape"))
    ET.SubElement(
        shape,
        q("Box"),
        {"size": _format_vec((size_x_m, thickness_m, size_z_m))},
    )

    geometry_index = len(scene)
    for index, child in enumerate(scene):
        if child is transform:
            geometry_index = index
            break
    scene.insert(geometry_index, collision)


def _freecad_xy_bounds_from_coordinates(node, q) -> Optional[Tuple[float, float, float, float]]:
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    found = False
    for coordinate in node.iter(q("Coordinate")):
        point_text = coordinate.attrib.get("point", "")
        if not point_text:
            continue
        try:
            values = [float(value) for value in point_text.replace(",", " ").split()]
        except ValueError:
            continue
        for index in range(0, len(values) - 2, 3):
            x_value = values[index]
            y_value = values[index + 1]
            min_x = min(min_x, x_value)
            max_x = max(max_x, x_value)
            min_y = min(min_y, y_value)
            max_y = max(max_y, y_value)
            found = True
    if not found:
        return None
    return min_x, max_x, min_y, max_y


def _ensure_background(scene, q) -> None:
    if any(child.tag == q("Background") for child in list(scene)):
        return
    scene.insert(0, ET.Element(q("Background"), {"skyColor": "0.05 0.08 0.15"}))


def _apply_environment_background(
    scene, q, file_path: Path, environment_cfg: Optional[Dict[str, object]]
) -> None:
    """Apply optional X3D-only environment background settings."""
    FreeCAD = __import__("FreeCAD")

    if not isinstance(environment_cfg, dict) or not bool(environment_cfg.get("use_skybox", False)):
        _ensure_background(scene, q)
        return

    skybox_dir = str(environment_cfg.get("skybox_dir", "") or "").strip()
    faces = detect_skybox_faces(skybox_dir)
    if not faces:
        FreeCAD.Console.PrintWarning(
            "[GAMEEXPORT][WARN] Skybox enabled but no complete cubemap was found: "
            + skybox_dir
            + "\n"
        )
        _ensure_background(scene, q)
        return

    urls = _copy_skybox_assets(faces, file_path)
    if not urls:
        FreeCAD.Console.PrintWarning(
            "[GAMEEXPORT][WARN] Skybox assets could not be prepared for export.\n"
        )
        _ensure_background(scene, q)
        return

    background = _get_or_create_background(scene, q)
    background.attrib["DEF"] = "GameExport_Skybox"
    background.attrib.pop("skyColor", None)
    background.attrib.pop("groundColor", None)
    for attr in sorted(SKYBOX_FACE_SUFFIXES):
        background.attrib[attr] = _x3d_mfstring_url(urls[attr])

    FreeCAD.Console.PrintMessage(
        LOG_PREFIX + "Applied X3D skybox background from " + skybox_dir + "\n"
    )


def _get_or_create_background(scene, q):
    for child in list(scene):
        if child.tag == q("Background"):
            return child
    background = ET.Element(q("Background"))
    scene.insert(0, background)
    return background


def detect_skybox_faces(skybox_dir: str) -> Dict[str, Path]:
    """Return a complete set of cubemap face files found in skybox_dir."""
    folder_text = str(skybox_dir or "").strip()
    if not folder_text:
        return {}
    folder = Path(folder_text).expanduser()
    if not folder.is_dir():
        return {}

    candidates: Dict[str, Dict[str, Path]] = {}
    try:
        files = [
            item
            for item in folder.iterdir()
            if item.is_file() and item.suffix.lower() in SKYBOX_IMAGE_EXTENSIONS
        ]
    except Exception:
        return {}

    for path in files:
        stem = path.stem.lower()
        for attr, face in SKYBOX_FACE_SUFFIXES.items():
            suffix = "_" + face
            if stem == face:
                prefix = ""
            elif stem.endswith(suffix):
                prefix = stem[: -len(suffix)]
            else:
                continue
            candidates.setdefault(prefix, {})[attr] = path

    for prefix in sorted(candidates):
        face_map = candidates[prefix]
        if all(attr in face_map for attr in SKYBOX_FACE_SUFFIXES):
            return {attr: face_map[attr] for attr in SKYBOX_FACE_SUFFIXES}
    return {}


def _copy_skybox_assets(faces: Dict[str, Path], file_path: Path) -> Dict[str, str]:
    FreeCAD = __import__("FreeCAD")
    asset_root = file_path.with_name(file_path.stem + "_assets")
    sky_dir = asset_root / "skies"
    urls: Dict[str, str] = {}
    try:
        sky_dir.mkdir(parents=True, exist_ok=True)
        for attr, source in faces.items():
            dest = sky_dir / source.name
            try:
                same_file = source.resolve() == dest.resolve()
            except Exception:
                same_file = False
            if not same_file:
                shutil.copy2(str(source), str(dest))
            urls[attr] = asset_root.name.replace("\\", "/") + "/skies/" + dest.name
    except Exception as exc:
        FreeCAD.Console.PrintWarning(
            "[GAMEEXPORT][WARN] Failed to copy skybox assets: " + str(exc) + "\n"
        )
        return {}
    return urls


def _x3d_mfstring_url(url: str) -> str:
    clean = str(url or "").replace("\\", "/").replace('"', "%22")
    return '"' + clean + '"'


def _ensure_navigation(scene, q, nav_cfg: Dict[str, object]) -> None:
    eye_height_m = float(nav_cfg["eye_height_mm"]) * 0.001
    step_height_m = float(nav_cfg["step_height_mm"]) * 0.001
    camera_fill_enabled = bool(nav_cfg.get("camera_fill_enabled", False))
    attrs = {
        "DEF": "GameExport_Navigation",
        "avatarSize": f"0.25 {eye_height_m:.3f} {step_height_m:.3f}",
        "speed": f"{float(nav_cfg['speed']):.3f}",
        "headlight": "true" if camera_fill_enabled else "false",
        "type": '"WALK"' if bool(nav_cfg.get("walk_only", True)) else '"WALK" "ANY"',
    }

    existing = None
    for child in list(scene):
        if child.tag == q("NavigationInfo"):
            existing = child
            break
    if existing is None:
        insert_index = 1 if len(scene) > 0 and scene[0].tag == q("Background") else 0
        existing = ET.Element(q("NavigationInfo"), attrs)
        scene.insert(insert_index, existing)
    else:
        existing.attrib.update(attrs)

    # Castle supports a custom light attached to the camera through the
    # NavigationInfo.headlightNode extension.  A single low-intensity
    # directional fill brightens visible architectural surfaces without
    # recreating dozens of omnidirectional PointLight contributions.
    for child in list(existing):
        if (
            child.attrib.get("containerField") == "headlightNode"
            or child.attrib.get("DEF") == "GameExport_CameraFill"
        ):
            existing.remove(child)
    if camera_fill_enabled:
        fill_intensity = _clamp(
            _float_config_value(nav_cfg, "camera_fill_intensity", 0.45), 0.0, 1.5
        )
        fill_ambient = _clamp(
            _float_config_value(nav_cfg, "camera_fill_ambient_intensity", 0.25),
            0.0,
            1.0,
        )
        ET.SubElement(
            existing,
            q("DirectionalLight"),
            {
                "DEF": "GameExport_CameraFill",
                "containerField": "headlightNode",
                "on": "true",
                "global": "true",
                "direction": "0 0 -1",
                "color": "1 0.98 0.92",
                "intensity": _format_float(fill_intensity),
                "ambientIntensity": _format_float(fill_ambient),
            },
        )


def _insert_viewpoint(scene, q, meta: Optional[Dict[str, object]], nav_cfg: Dict[str, object]) -> None:
    FreeCAD = __import__("FreeCAD")

    eye_height_mm = float(nav_cfg.get("eye_height_mm", DEFAULT_EYE_HEIGHT_MM))
    position_mm = (0.0, -6000.0, 0.0)
    orientation = (0.0, 1.0, 0.0, 0.0)
    yaw_pitch_roll_deg = (0.0, 0.0, 0.0)
    use_yaw_pitch_roll = True
    description = "GameStart"
    fov_rad = math.radians(60.0)

    if isinstance(meta, dict):
        if isinstance(meta.get("position_mm"), (list, tuple)) and len(meta.get("position_mm")) == 3:
            p = meta["position_mm"]
            position_mm = (float(p[0]), float(p[1]), float(p[2]))
        if isinstance(meta.get("orientation"), (list, tuple)) and len(meta.get("orientation")) == 4:
            o = meta["orientation"]
            orientation = (float(o[0]), float(o[1]), float(o[2]), float(o[3]))
        ypr_keys = ("yaw_deg", "pitch_deg", "roll_deg")
        if all(key in meta for key in ypr_keys):
            yaw_pitch_roll_deg = tuple(float(meta[key]) for key in ypr_keys)
        else:
            use_yaw_pitch_roll = False
        description = str(meta.get("description", description))
        fov_rad = float(meta.get("fov_rad", fov_rad))
        if "height_offset_mm" in meta:
            try:
                eye_height_mm = float(meta["height_offset_mm"])
            except Exception:
                pass

    pos_vec = FreeCAD.Vector(position_mm[0], position_mm[1], position_mm[2] + eye_height_mm)
    transform_rot = FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90.0)
    pos_rot = transform_rot.multVec(pos_vec)
    position_m = (pos_rot.x * 0.001, pos_rot.y * 0.001, pos_rot.z * 0.001)

    if use_yaw_pitch_roll:
        yaw_deg, pitch_deg, roll_deg = yaw_pitch_roll_deg
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "[DEBUG] GameStart FreeCAD orientation: "
            + f"Yaw={yaw_deg:.6f} deg, Pitch={pitch_deg:.6f} deg, Roll={roll_deg:.6f} deg\n"
        )
        final_axis_angle = _convert_gamestart_orientation_to_x3d(
            orientation,
            yaw_pitch_roll_deg,
        )
    else:
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "[DEBUG] GameStart FreeCAD Yaw/Pitch/Roll unavailable; "
            + "using legacy Placement orientation\n"
        )
        final_axis_angle = _convert_gamestart_orientation_to_x3d(orientation, None)
    axis_x, axis_y, axis_z, final_angle_rad = final_axis_angle
    FreeCAD.Console.PrintMessage(
        LOG_PREFIX
        + "[DEBUG] GameStart X3D Viewpoint axis-angle: "
        + f"{axis_x:.6f} {axis_y:.6f} {axis_z:.6f} {final_angle_rad:.6f}\n"
    )

    attrs = {
        "DEF": "GameExport_Viewpoint",
        "description": description,
        "position": f"{position_m[0]:.6f} {position_m[1]:.6f} {position_m[2]:.6f}",
        "orientation": f"{axis_x:.6f} {axis_y:.6f} {axis_z:.6f} {final_angle_rad:.6f}",
        "fieldOfView": f"{fov_rad:.6f}",
        "jump": "true",
    }

    for child in list(scene):
        if child.tag == q("Viewpoint") and child.attrib.get("DEF") == "GameExport_Viewpoint":
            scene.remove(child)

    insert_index = 0
    for idx, child in enumerate(scene):
        if child.tag in {q("Background"), q("NavigationInfo")}:
            insert_index = idx + 1
    scene.insert(insert_index, ET.Element(q("Viewpoint"), attrs))


def _convert_gamestart_orientation_to_x3d(
    placement_orientation: Tuple[float, float, float, float],
    yaw_pitch_roll_deg: Optional[Tuple[float, float, float]],
) -> Tuple[float, float, float, float]:
    """Convert a relative FreeCAD camera rotation into the X3D camera basis."""
    if yaw_pitch_roll_deg is None:
        source_rotation = _quaternion_from_axis_angle(
            placement_orientation[:3],
            float(placement_orientation[3]),
        )
    else:
        yaw_deg, pitch_deg, roll_deg = yaw_pitch_roll_deg
        yaw_rotation = _quaternion_from_axis_angle((0.0, 0.0, 1.0), math.radians(yaw_deg))
        pitch_rotation = _quaternion_from_axis_angle((1.0, 0.0, 0.0), math.radians(pitch_deg))
        roll_rotation = _quaternion_from_axis_angle((0.0, 1.0, 0.0), math.radians(roll_deg))
        source_rotation = _quaternion_multiply(
            _quaternion_multiply(yaw_rotation, pitch_rotation),
            roll_rotation,
        )

    # Geometry changes from FreeCAD Z-up to X3D Y-up through -90 degrees X.
    # Camera rotations are relative, so change basis by T * R * inverse(T).
    basis_rotation = _quaternion_from_axis_angle((1.0, 0.0, 0.0), -math.pi / 2.0)
    converted = _quaternion_multiply(
        _quaternion_multiply(basis_rotation, source_rotation),
        _quaternion_conjugate(basis_rotation),
    )
    return _quaternion_to_axis_angle(converted)


def _quaternion_from_axis_angle(axis, angle_rad: float) -> Tuple[float, float, float, float]:
    x, y, z = (float(axis[0]), float(axis[1]), float(axis[2]))
    length = math.sqrt((x * x) + (y * y) + (z * z))
    if length <= 1e-12 or abs(angle_rad) <= 1e-12:
        return (1.0, 0.0, 0.0, 0.0)
    half_angle = float(angle_rad) * 0.5
    scale = math.sin(half_angle) / length
    return (math.cos(half_angle), x * scale, y * scale, z * scale)


def _quaternion_multiply(left, right) -> Tuple[float, float, float, float]:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return (
        (lw * rw) - (lx * rx) - (ly * ry) - (lz * rz),
        (lw * rx) + (lx * rw) + (ly * rz) - (lz * ry),
        (lw * ry) - (lx * rz) + (ly * rw) + (lz * rx),
        (lw * rz) + (lx * ry) - (ly * rx) + (lz * rw),
    )


def _quaternion_conjugate(value) -> Tuple[float, float, float, float]:
    return (value[0], -value[1], -value[2], -value[3])


def _quaternion_to_axis_angle(value) -> Tuple[float, float, float, float]:
    length = math.sqrt(sum(float(component) ** 2 for component in value))
    if length <= 1e-12:
        return (0.0, 0.0, 1.0, 0.0)
    w, x, y, z = (float(component) / length for component in value)
    if w < 0.0:
        w, x, y, z = -w, -x, -y, -z
    w = max(-1.0, min(1.0, w))
    angle_rad = 2.0 * math.acos(w)
    axis_length = math.sqrt((x * x) + (y * y) + (z * z))
    if axis_length <= 1e-12 or abs(angle_rad) <= 1e-12:
        return (0.0, 0.0, 1.0, 0.0)
    return (x / axis_length, y / axis_length, z / axis_length, angle_rad)


def _material_cfg_with_light_source_indices(
    material_cfg: Optional[Dict[str, object]], exportable_objects: Iterable[object]
) -> Optional[Dict[str, object]]:
    if not isinstance(material_cfg, dict):
        return material_cfg
    objects = list(exportable_objects)
    names = {str(name) for name in material_cfg.get("light_source_names", []) if str(name)}
    if not names:
        return material_cfg

    cfg = dict(material_cfg)
    cfg["exportable_count"] = len(objects)
    indices = []
    matched = set()
    for index, obj in enumerate(objects):
        obj_name = str(getattr(obj, "Name", "") or "")
        obj_label = str(getattr(obj, "Label", "") or "")
        if obj_name in names or obj_label in names:
            indices.append(index)
            matched.add(obj_name)
            matched.add(obj_label)
    cfg["light_source_indices"] = indices

    try:
        FreeCAD = __import__("FreeCAD")
        missing = sorted(name for name in names if name not in matched)
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Light source material mapping: "
            + str(len(indices))
            + " export objects matched\n"
        )
        if missing:
            FreeCAD.Console.PrintWarning(
                LOG_PREFIX
                + "[WARN] Light source objects not found in export geometry: "
                + ", ".join(missing[:12])
                + ("\n" if len(missing) <= 12 else "...\n")
            )
    except Exception:
        pass
    return cfg



def _material_cfg_with_object_assignments(
    material_cfg: Optional[Dict[str, object]], exportable_objects: Iterable[object]
) -> Dict[str, object]:
    """Attach persisted object assignments to material config by export index."""
    cfg = dict(material_cfg or {})
    persisted = material_assignments.collect_assignments(exportable_objects, enabled_only=True)
    explicit = cfg.get("object_assignments", [])
    merged = []
    seen = set()
    for item in list(explicit or []) + persisted:
        if not isinstance(item, dict):
            continue
        normalized = material_assignments.normalize_assignment(item)
        try:
            object_index = int(item.get("object_index", -1))
        except Exception:
            object_index = -1
        object_name = str(item.get("object_name", "") or "")
        key = (object_index, object_name)
        if key in seen:
            continue
        seen.add(key)
        normalized.update(
            {
                "object_index": object_index,
                "object_name": object_name,
                "object_label": str(item.get("object_label", "") or ""),
                "native_material_name": str(item.get("native_material_name", "") or ""),
            }
        )
        merged.append(normalized)
    cfg["object_assignments"] = merged
    cfg["object_count"] = len(list(exportable_objects or []))
    return cfg


def _ground_texture_cfg_with_object_indices(
    ground_texture_cfg: Optional[Dict[str, object]], exportable_objects: Iterable[object]
) -> Optional[Dict[str, object]]:
    if not isinstance(ground_texture_cfg, dict):
        return ground_texture_cfg
    if not bool(ground_texture_cfg.get("enabled", False)):
        return ground_texture_cfg

    objects = list(exportable_objects)
    names = {
        str(ground_texture_cfg.get("object_name", "") or "").strip(),
        str(ground_texture_cfg.get("object_label", "") or "").strip(),
    }
    names = {name for name in names if name}
    if not names:
        return ground_texture_cfg

    cfg = dict(ground_texture_cfg)
    cfg["exportable_count"] = len(objects)
    indices = []
    matched = set()
    for index, obj in enumerate(objects):
        obj_name = str(getattr(obj, "Name", "") or "")
        obj_label = str(getattr(obj, "Label", "") or "")
        aliases = _object_name_aliases(obj)
        if names.intersection(aliases):
            indices.append(index)
            matched.update(aliases)
    if not indices:
        indices = _guess_ground_texture_indices(objects)
    cfg["object_indices"] = indices

    try:
        FreeCAD = __import__("FreeCAD")
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX + "Ground texture object mapping: " + str(len(indices)) + " export objects matched\n"
        )
        if not names.intersection(matched):
            FreeCAD.Console.PrintWarning(
                LOG_PREFIX
                + "[WARN] Ground texture object not found in export geometry: "
                + ", ".join(sorted(names))
                + "\n"
            )
            if indices:
                FreeCAD.Console.PrintWarning(
                    LOG_PREFIX + "[WARN] Using inferred ground texture target: " + _object_display_name(objects[indices[0]]) + "\n"
                )
    except Exception:
        pass
    return cfg


def _object_name_aliases(obj: object) -> set:
    aliases = set()
    for attr in ("Name", "Label"):
        value = str(getattr(obj, attr, "") or "").strip()
        if value:
            aliases.add(value)
    linked = getattr(obj, "LinkedObject", None)
    if linked is not None and linked is not obj:
        for attr in ("Name", "Label"):
            value = str(getattr(linked, attr, "") or "").strip()
            if value:
                aliases.add(value)
    return aliases


def _object_display_name(obj: object) -> str:
    label = str(getattr(obj, "Label", "") or "").strip()
    name = str(getattr(obj, "Name", "") or "").strip()
    if label and name and label != name:
        return label + " (" + name + ")"
    return label or name or "Unknown"


def _guess_ground_texture_indices(objects: List[object]) -> List[int]:
    scored = []
    for index, obj in enumerate(objects):
        score = _ground_texture_candidate_score(obj)
        if score > 0:
            scored.append((score, index))
    if not scored:
        return []
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [scored[0][1]]


def _ground_texture_candidate_score(obj: object) -> int:
    text = " ".join(_object_name_aliases(obj)).lower()
    score = 0
    for keyword, value in GROUND_TEXTURE_FALLBACK_KEYWORDS:
        if keyword in text:
            score = max(score, value)
    return score


def _apply_light_source_emissive_materials(scene, q, material_cfg: Optional[Dict[str, object]]) -> int:
    if not isinstance(material_cfg, dict):
        return 0
    indices = []
    for value in material_cfg.get("light_source_indices", []) or []:
        try:
            index = int(value)
        except Exception:
            continue
        if index >= 0 and index not in indices:
            indices.append(index)
    if not indices:
        return 0

    transform = _find_freecad_transform(scene, q)
    if transform is None:
        return 0
    expected_count = _expected_object_count(material_cfg, max(indices) + 1)
    container = _find_object_group_container(transform, max(indices), expected_count)
    if container is None:
        return 0

    children = list(container)
    count = 0
    for index in indices:
        if index >= len(children):
            try:
                FreeCAD = __import__("FreeCAD")
                FreeCAD.Console.PrintWarning(
                    LOG_PREFIX
                    + "[WARN] Light source material index outside X3D object group: "
                    + str(index)
                    + " / "
                    + str(len(children))
                    + "\n"
                )
            except Exception:
                pass
            continue
        count += _mark_materials_emissive(children[index], index)
    return count



def _apply_object_material_assignments(
    scene, q, file_path: Path, material_cfg: Optional[Dict[str, object]]
) -> int:
    if not isinstance(material_cfg, dict):
        return 0
    assignments = [item for item in list(material_cfg.get("object_assignments", []) or []) if isinstance(item, dict)]
    if not assignments:
        return 0
    indices = []
    for item in assignments:
        try:
            index = int(item.get("object_index", -1))
        except Exception:
            continue
        if index >= 0:
            indices.append(index)
    if not indices:
        return 0
    transform = _find_freecad_transform(scene, q)
    if transform is None:
        return 0
    expected_count = _expected_object_count(material_cfg, max(indices) + 1)
    container = _find_object_group_container(transform, max(indices), expected_count)
    if container is None:
        return 0
    children = list(container)
    applied = 0
    for assignment in assignments:
        cfg = material_assignments.normalize_assignment(assignment)
        if not bool(cfg.get("enabled", False)):
            continue
        try:
            index = int(assignment.get("object_index", -1))
        except Exception:
            index = -1
        if index < 0 or index >= len(children):
            _console_warning(
                "Object material index outside X3D object group: "
                + str(index)
                + " / "
                + str(len(children))
            )
            continue
        mode = str(cfg.get("mode", material_assignments.MODE_TEXTURE))
        if mode == material_assignments.MODE_MIRROR:
            applied += _apply_mirror_to_shapes(children[index], q, int(cfg.get("mirror_size", 512)))
            continue
        texture_path_text = material_assignments.resolve_texture_path(cfg)
        texture_url = ""
        if texture_path_text:
            texture_path = Path(texture_path_text).expanduser()
            if texture_path.is_file():
                texture_url = _copy_texture_asset(texture_path, file_path)
            else:
                _console_warning("Object texture file not found: " + str(texture_path))
        if texture_url:
            applied += _apply_object_texture_to_shapes(
                children[index],
                q,
                texture_url,
                str(cfg.get("projection", material_assignments.PROJECTION_AUTO)),
                float(cfg.get("tile_u_mm", 1000.0)),
                float(cfg.get("tile_v_mm", 1000.0)),
                polished=(mode == material_assignments.MODE_POLISHED),
                reflectivity=float(cfg.get("reflectivity", 0.35)),
            )
        elif mode == material_assignments.MODE_POLISHED:
            applied += _apply_polished_material_to_shapes(
                children[index], q, float(cfg.get("reflectivity", 0.35))
            )
    return applied


def _console_warning(message: str) -> None:
    try:
        FreeCAD = __import__("FreeCAD")
        FreeCAD.Console.PrintWarning(LOG_PREFIX + "[WARN] " + str(message) + "\n")
    except Exception:
        pass


def _apply_object_texture_to_shapes(
    node,
    q,
    texture_url: str,
    projection: str,
    tile_u_mm: float,
    tile_v_mm: float,
    polished: bool = False,
    reflectivity: float = 0.35,
) -> int:
    coord_defs = _collect_coordinate_defs(node)
    count = 0
    for shape in node.iter():
        if _local_name(shape.tag) != "Shape" or not _shape_has_textured_surface(shape):
            continue
        appearance = _ensure_shape_appearance(shape, q)
        _ensure_object_material(appearance, q, count, polished=polished, reflectivity=reflectivity)
        _replace_child_by_local_name(
            appearance,
            "ImageTexture",
            ET.Element(
                q("ImageTexture"),
                {"url": _x3d_mfstring_url(texture_url), "repeatS": "true", "repeatT": "true"},
            ),
        )
        for local_name in ("RenderedTexture", "GeneratedCubeMapTexture", "MultiTexture"):
            _remove_children_by_local_name(appearance, local_name)
        _generate_physical_planar_uv_for_shape(
            shape,
            q,
            projection,
            tile_u_mm,
            tile_v_mm,
            coord_defs,
        )
        _remove_children_by_local_name(appearance, "TextureTransform")
        count += 1
    return count


def _apply_polished_material_to_shapes(node, q, reflectivity: float) -> int:
    count = 0
    for shape in node.iter():
        if _local_name(shape.tag) != "Shape" or not _shape_has_textured_surface(shape):
            continue
        appearance = _ensure_shape_appearance(shape, q)
        _ensure_object_material(appearance, q, count, polished=True, reflectivity=reflectivity)
        count += 1
    return count


def _apply_mirror_to_shapes(node, q, mirror_size: int) -> int:
    size = int(max(64, min(4096, int(mirror_size or 512))))
    count = 0
    for shape in node.iter():
        if _local_name(shape.tag) != "Shape" or not _shape_has_textured_surface(shape):
            continue
        appearance = _ensure_shape_appearance(shape, q)
        _ensure_object_material(appearance, q, count, polished=True, reflectivity=1.0)
        for local_name in ("ImageTexture", "MultiTexture", "GeneratedCubeMapTexture", "RenderedTexture", "TextureTransform"):
            _remove_children_by_local_name(appearance, local_name)
        rendered = ET.Element(
            q("RenderedTexture"),
            {
                "dimensions": f"{size} {size} 3",
                "repeatS": "false",
                "repeatT": "false",
                "update": "ALWAYS",
            },
        )
        rendered.append(ET.Element(q("ViewpointMirror"), {"containerField": "viewpoint"}))
        appearance.append(rendered)
        for geometry in list(shape):
            if _local_name(geometry.tag) not in {
                "ElevationGrid",
                "Extrusion",
                "IndexedFaceSet",
                "IndexedTriangleSet",
                "TriangleSet",
                "TriangleStripSet",
            }:
                continue
            _remove_children_by_local_name(geometry, "TextureCoordinate")
            _remove_children_by_local_name(geometry, "TextureCoordinateGenerator")
            geometry.attrib.pop("texCoordIndex", None)
            geometry.append(ET.Element(q("TextureCoordinateGenerator"), {"mode": "MIRROR-PLANE"}))
        count += 1
    return count


def _remove_children_by_local_name(parent, local_name: str) -> None:
    for child in list(parent):
        if _local_name(child.tag) == local_name:
            parent.remove(child)


def _ensure_object_material(
    appearance,
    q,
    material_index: int,
    polished: bool = False,
    reflectivity: float = 0.35,
) -> None:
    material = None
    for child in list(appearance):
        if _local_name(child.tag) == "Material":
            material = child
            break
    if material is None:
        material = ET.Element(q("Material"))
        appearance.insert(0, material)
    material.attrib.pop("USE", None)
    # Keep each material local to its Shape. Avoid introducing duplicate DEF names
    # when a selected FreeCAD object expands into multiple X3D Shape nodes.
    material.attrib.pop("DEF", None)
    if "diffuseColor" not in material.attrib:
        material.attrib["diffuseColor"] = "0.8 0.8 0.8"
    if polished:
        level = max(0.0, min(1.0, float(reflectivity)))
        spec = 0.25 + 0.75 * level
        material.attrib["specularColor"] = f"{_format_float(spec)} {_format_float(spec)} {_format_float(spec)}"
        material.attrib["shininess"] = _format_float(0.35 + 0.65 * level)
        material.attrib["ambientIntensity"] = _format_float(0.15 + 0.15 * (1.0 - level))


def _generate_physical_planar_uv_for_shape(
    shape,
    q,
    projection: str,
    tile_u_mm: float,
    tile_v_mm: float,
    coord_defs: Optional[Dict[str, str]] = None,
) -> bool:
    projection = material_assignments.normalize_projection(projection)
    tile_u = max(float(tile_u_mm or 1000.0), 1.0)
    tile_v = max(float(tile_v_mm or 1000.0), 1.0)
    changed = False
    for geometry in list(shape):
        if _local_name(geometry.tag) != "IndexedFaceSet":
            continue
        coord = None
        for child in list(geometry):
            if _local_name(child.tag) == "Coordinate":
                coord = child
                break
        if coord is None:
            continue
        point_text = coord.attrib.get("point", "")
        if not point_text:
            coord_use = str(coord.attrib.get("USE", "") or "").strip()
            point_text = (coord_defs or {}).get(coord_use, "")
        points = _parse_vec3_points(point_text)
        if not points:
            continue
        axes = _projection_axes(points, projection)
        u_values = [point[axes[0]] for point in points]
        v_values = [point[axes[1]] for point in points]
        min_u = min(u_values)
        min_v = min(v_values)
        uv_values = []
        for point in points:
            uv_values.append((point[axes[0]] - min_u) / tile_u)
            uv_values.append((point[axes[1]] - min_v) / tile_v)
        _remove_children_by_local_name(geometry, "TextureCoordinate")
        _remove_children_by_local_name(geometry, "TextureCoordinateGenerator")
        geometry.attrib.pop("texCoordIndex", None)
        geometry.append(ET.Element(q("TextureCoordinate"), {"point": _format_float_list(uv_values)}))
        changed = True
    return changed


def _projection_axes(points: List[Tuple[float, float, float]], projection: str) -> Tuple[int, int]:
    if projection == material_assignments.PROJECTION_XY:
        return (0, 1)
    if projection == material_assignments.PROJECTION_XZ:
        return (0, 2)
    if projection == material_assignments.PROJECTION_YZ:
        return (1, 2)
    spans = []
    for axis in range(3):
        values = [point[axis] for point in points]
        spans.append(max(values) - min(values))
    candidates = [((0, 1), spans[0] * spans[1]), ((0, 2), spans[0] * spans[2]), ((1, 2), spans[1] * spans[2])]
    return max(candidates, key=lambda item: item[1])[0]


def _apply_ground_texture(scene, q, file_path: Path, ground_texture_cfg: Optional[Dict[str, object]]) -> int:
    if not isinstance(ground_texture_cfg, dict) or not bool(ground_texture_cfg.get("enabled", False)):
        return 0

    texture_path = Path(str(ground_texture_cfg.get("texture_path", "") or "")).expanduser()
    if not texture_path.is_file():
        try:
            FreeCAD = __import__("FreeCAD")
            FreeCAD.Console.PrintWarning(
                "[GAMEEXPORT][WARN] Ground texture file not found: " + texture_path.name + "\n"
            )
        except Exception:
            pass
        return 0

    indices = []
    for value in ground_texture_cfg.get("object_indices", []) or []:
        try:
            index = int(value)
        except Exception:
            continue
        if index >= 0 and index not in indices:
            indices.append(index)
    if not indices:
        return 0

    transform = _find_freecad_transform(scene, q)
    if transform is None:
        return 0
    expected_count = _expected_object_count(ground_texture_cfg, max(indices) + 1)
    container = _find_object_group_container(transform, max(indices), expected_count)
    if container is None:
        return 0

    texture_url = _copy_texture_asset(texture_path, file_path)
    if not texture_url:
        return 0

    repeat_s = _safe_float(ground_texture_cfg.get("repeat_s", 20.0), 20.0, 0.01, 1000.0)
    repeat_t = _safe_float(ground_texture_cfg.get("repeat_t", 20.0), 20.0, 0.01, 1000.0)
    generate_uv = bool(ground_texture_cfg.get("generate_planar_uv", True))

    children = list(container)
    count = 0
    for index in indices:
        if index >= len(children):
            try:
                FreeCAD = __import__("FreeCAD")
                FreeCAD.Console.PrintWarning(
                    LOG_PREFIX
                    + "[WARN] Ground texture index outside X3D object group: "
                    + str(index)
                    + " / "
                    + str(len(children))
                    + "\n"
                )
            except Exception:
                pass
            continue
        count += _apply_texture_to_shapes(children[index], q, texture_url, repeat_s, repeat_t, generate_uv)
    return count


def _copy_texture_asset(texture_path: Path, file_path: Path) -> str:
    FreeCAD = __import__("FreeCAD")
    asset_root = file_path.with_name(file_path.stem + "_assets")
    texture_dir = asset_root / "textures"
    try:
        texture_dir.mkdir(parents=True, exist_ok=True)
        dest = texture_dir / texture_path.name
        try:
            same_file = texture_path.resolve() == dest.resolve()
        except Exception:
            same_file = False
        if not same_file:
            shutil.copy2(str(texture_path), str(dest))
        return asset_root.name.replace("\\", "/") + "/textures/" + dest.name
    except Exception as exc:
        FreeCAD.Console.PrintWarning("[GAMEEXPORT][WARN] Failed to copy ground texture: " + str(exc) + "\n")
        return ""


def _apply_texture_to_shapes(node, q, texture_url: str, repeat_s: float, repeat_t: float, generate_uv: bool) -> int:
    coord_defs = _collect_coordinate_defs(node)
    count = 0
    for shape in node.iter():
        if _local_name(shape.tag) != "Shape":
            continue
        if not _shape_has_textured_surface(shape):
            continue
        appearance = _ensure_shape_appearance(shape, q)
        _ensure_textured_material(appearance, q, count)
        _replace_child_by_local_name(
            appearance,
            "ImageTexture",
            ET.Element(q("ImageTexture"), {"url": _x3d_mfstring_url(texture_url), "repeatS": "true", "repeatT": "true"}),
        )
        if generate_uv:
            _generate_planar_uv_for_shape(shape, q, 1.0, 1.0, coord_defs)
        _ensure_texture_transform(appearance, q, repeat_s, repeat_t)
        count += 1
    return count


def _collect_coordinate_defs(node) -> Dict[str, str]:
    coord_defs: Dict[str, str] = {}
    for child in node.iter():
        if _local_name(child.tag) != "Coordinate":
            continue
        coord_def = str(child.attrib.get("DEF", "") or "").strip()
        points = str(child.attrib.get("point", "") or "").strip()
        if coord_def and points:
            coord_defs[coord_def] = points
    return coord_defs


def _shape_has_textured_surface(shape) -> bool:
    surface_nodes = {
        "ElevationGrid",
        "Extrusion",
        "IndexedFaceSet",
        "IndexedTriangleSet",
        "TriangleSet",
        "TriangleStripSet",
    }
    for child in list(shape):
        if _local_name(child.tag) in surface_nodes:
            return True
    return False


def _ensure_shape_appearance(shape, q):
    for child in list(shape):
        if _local_name(child.tag) == "Appearance":
            child.attrib.pop("USE", None)
            return child
    appearance = ET.Element(q("Appearance"))
    shape.insert(0, appearance)
    return appearance


def _ensure_textured_material(appearance, q, material_index: int) -> None:
    material = None
    for child in list(appearance):
        if _local_name(child.tag) == "Material":
            material = child
            break
    if material is None:
        material = ET.Element(q("Material"))
        appearance.insert(0, material)
    material.attrib.pop("USE", None)
    material.attrib["DEF"] = GROUND_TEXTURE_MATERIAL_DEF_PREFIX + str(material_index)
    material.attrib["diffuseColor"] = "1 1 1"
    material.attrib["ambientIntensity"] = "0.45"
    material.attrib["shininess"] = "0.02"


def _replace_child_by_local_name(parent, local_name: str, replacement) -> None:
    for child in list(parent):
        if _local_name(child.tag) == local_name:
            parent.remove(child)
    parent.append(replacement)


def _ensure_texture_transform(appearance, q, scale_s: float, scale_t: float) -> None:
    _replace_child_by_local_name(
        appearance,
        "TextureTransform",
        ET.Element(
            q("TextureTransform"),
            {"scale": _format_float(scale_s) + " " + _format_float(scale_t)},
        ),
    )


def _generate_planar_uv_for_shape(
    shape, q, repeat_s: float, repeat_t: float, coord_defs: Optional[Dict[str, str]] = None
) -> bool:
    for geometry in list(shape):
        if _local_name(geometry.tag) != "IndexedFaceSet":
            continue
        coord = None
        for child in list(geometry):
            if _local_name(child.tag) == "Coordinate":
                coord = child
                break
        if coord is None:
            continue
        point_text = coord.attrib.get("point", "")
        if not point_text:
            coord_use = str(coord.attrib.get("USE", "") or "").strip()
            point_text = (coord_defs or {}).get(coord_use, "")
        points = _parse_vec3_points(point_text)
        if not points:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1e-9)
        span_y = max(max_y - min_y, 1e-9)
        uv_values = []
        for x, y, _z in points:
            uv_values.append(((x - min_x) / span_x) * repeat_s)
            uv_values.append(((y - min_y) / span_y) * repeat_t)
        for child in list(geometry):
            if _local_name(child.tag) == "TextureCoordinate":
                geometry.remove(child)
        geometry.attrib.pop("texCoordIndex", None)
        geometry.append(ET.Element(q("TextureCoordinate"), {"point": _format_float_list(uv_values)}))
        return True
    return False


def _parse_vec3_points(text: str) -> List[Tuple[float, float, float]]:
    parts = str(text or "").replace(",", " ").split()
    values = []
    for part in parts:
        try:
            values.append(float(part))
        except Exception:
            pass
    points = []
    for index in range(0, len(values) - 2, 3):
        points.append((values[index], values[index + 1], values[index + 2]))
    return points


def _format_float_list(values: Iterable[float]) -> str:
    return " ".join(_format_float(value) for value in values)


def _safe_float(value, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except Exception:
        number = float(default)
    return max(float(minimum), min(float(maximum), number))


def _expected_object_count(cfg: Dict[str, object], minimum: int) -> int:
    try:
        count = int(cfg.get("exportable_count", minimum))
    except Exception:
        count = minimum
    return max(int(minimum), count)


def _find_freecad_transform(scene, q):
    for node in scene.iter():
        if node.tag == q("Transform") and node.attrib.get("DEF") == TRANSFORM_DEF:
            return node
    return None


def _find_object_group_container(transform, max_index: int, expected_count: Optional[int] = None):
    minimum_required = max_index + 1
    preferred_required = max(minimum_required, int(expected_count or minimum_required))
    queue = [transform]
    fallback = None
    fallback_size = -1
    while queue:
        node = queue.pop(0)
        children = list(node)
        if _local_name(node.tag) in {"Transform", "Group"} and len(children) >= preferred_required:
            return node
        if _local_name(node.tag) in {"Transform", "Group"} and len(children) >= minimum_required:
            if len(children) > fallback_size:
                fallback = node
                fallback_size = len(children)
        for child in children:
            if _local_name(child.tag) in {"Transform", "Group"}:
                queue.append(child)
    return fallback


def _mark_materials_emissive(node, source_index: int) -> int:
    count = 0
    material_index = 0
    for child in node.iter():
        if _local_name(child.tag) != "Material":
            continue
        original_def = str(child.attrib.get("DEF", "Material"))
        child.attrib["DEF"] = (
            EMITTER_MATERIAL_DEF_PREFIX
            + str(source_index)
            + "_"
            + str(material_index)
            + "_"
            + _safe_x3d_def(original_def)
        )
        child.attrib["diffuseColor"] = "1 0.96 0.78"
        child.attrib["emissiveColor"] = "1 0.92 0.55"
        child.attrib["ambientIntensity"] = "1"
        child.attrib["shininess"] = "0.02"
        count += 1
        material_index += 1
    return count


def apply_x3d_material_lighting_profile(x3d_content: str, mode: str) -> Tuple[str, int]:
    """Apply color-aware interior compensation to ordinary X3D materials.

    ``emissiveColor`` is derived from each material's own ``diffuseColor``.
    This preserves FreeCAD hues instead of replacing every surface with the
    same neutral gray. Material USE nodes and light/ground helper materials
    remain untouched.
    """
    profile = MATERIAL_LIGHTING_PROFILES.get(str(mode))
    if not profile:
        return x3d_content, 0

    count = 0

    def _replace(match: re.Match) -> str:
        nonlocal count
        tag = match.group(0)
        if re.search(r"\bDEF\s*=\s*['\"]" + re.escape(EMITTER_MATERIAL_DEF_PREFIX), tag):
            return tag
        if re.search(r"\bDEF\s*=\s*['\"]" + re.escape(GROUND_TEXTURE_MATERIAL_DEF_PREFIX), tag):
            return tag
        if MATERIAL_USE_RE.search(tag):
            return tag
        diffuse_color = _material_diffuse_color_from_tag(tag)
        tag = MATERIAL_PROFILE_ATTR_RE.sub("", tag)
        self_closing = tag.rstrip().endswith("/>")
        if self_closing:
            base = tag.rstrip()[:-2].rstrip()
            end = " />"
        else:
            base = tag.rstrip()[:-1].rstrip()
            end = ">"

        count += 1
        emissive_color = _scaled_material_color(
            diffuse_color,
            float(profile.get("emissiveFactor", 0.0)),
        )
        attrs = (
            f" ambientIntensity=\"{profile['ambientIntensity']}\""
            f" emissiveColor=\"{emissive_color}\""
            f" shininess=\"{profile['shininess']}\""
        )
        return base + attrs + end

    return MATERIAL_TAG_RE.sub(_replace, x3d_content), count


def _material_diffuse_color_from_tag(tag: str) -> Tuple[float, float, float]:
    """Read diffuseColor from one Material tag, using the X3D default."""
    match = MATERIAL_DIFFUSE_COLOR_RE.search(str(tag or ""))
    if match is None:
        return (0.8, 0.8, 0.8)
    try:
        values = [float(value) for value in re.split(r"[\s,]+", match.group(2).strip())]
    except (TypeError, ValueError):
        return (0.8, 0.8, 0.8)
    if len(values) < 3:
        return (0.8, 0.8, 0.8)
    return tuple(max(0.0, min(1.0, value)) for value in values[:3])


def _scaled_material_color(
    diffuse_color: Tuple[float, float, float], factor: float
) -> str:
    clean_factor = max(0.0, min(1.0, float(factor)))
    return " ".join(
        _format_float(max(0.0, min(1.0, component * clean_factor)))
        for component in diffuse_color
    )


def _material_lighting_mode_from_cfg(material_cfg: Optional[Dict[str, object]]) -> str:
    if not isinstance(material_cfg, dict):
        return "None"
    if not bool(material_cfg.get("improve_interior_lighting", False)):
        return "None"
    mode = str(material_cfg.get("interior_lighting_mode", "None") or "None")
    if mode not in MATERIAL_LIGHTING_PROFILES:
        return "None"
    return mode


def _insert_lights(scene, q, lighting_cfg: Optional[Dict[str, object]]) -> int:
    """Insert global and local lights using already-converted X3D coordinates."""
    if not isinstance(lighting_cfg, dict):
        return 0

    count = 0
    global_cfg = lighting_cfg.get("global")
    if isinstance(global_cfg, dict) and bool(global_cfg.get("enabled", False)):
        light = _make_directional_light(q, global_cfg)
        _insert_scene_light(scene, q, light)
        count += 1

    point_entries = lighting_cfg.get("point_lights")
    point_shadow_count = 0
    point_shadow_requested = 0
    spot_shadow_count = 0
    spot_shadow_requested = 0
    if isinstance(point_entries, (list, tuple)):
        for index, entry in enumerate(point_entries):
            if not isinstance(entry, dict):
                continue
            safe_entry = dict(entry)
            light_mode = _light_export_mode(safe_entry)
            if light_mode == LIGHT_MODE_POINT_CLASSIC and bool(safe_entry.get("shadows", False)):
                point_shadow_requested += 1
                if point_shadow_count >= MAX_POINT_LIGHT_SHADOWS:
                    safe_entry["shadows"] = False
                else:
                    point_shadow_count += 1
            elif light_mode != LIGHT_MODE_POINT_CLASSIC and bool(safe_entry.get("shadows", False)):
                spot_shadow_requested += 1
                if spot_shadow_count >= MAX_SPOT_LIGHT_SHADOWS:
                    safe_entry["shadows"] = False
                else:
                    spot_shadow_count += 1
            if light_mode == LIGHT_MODE_POINT_CLASSIC:
                light = _make_point_light(q, safe_entry, index)
            else:
                light = _make_spot_light(q, safe_entry, index)
            _insert_scene_light(scene, q, light)
            count += 1
        if point_shadow_count > 0:
            try:
                FreeCAD = __import__("FreeCAD")
                FreeCAD.Console.PrintMessage(
                    LOG_PREFIX + "PointLight shadows written: " + str(point_shadow_count) + "\n"
                )
                if point_shadow_requested > point_shadow_count:
                    FreeCAD.Console.PrintWarning(
                        "[GAMEEXPORT][WARN] PointLight shadows capped by exporter: requested="
                        + str(point_shadow_requested)
                        + ", written="
                        + str(point_shadow_count)
                        + "\n"
                    )
            except Exception:
                pass
        if spot_shadow_requested > 0:
            try:
                FreeCAD = __import__("FreeCAD")
                FreeCAD.Console.PrintMessage(
                    LOG_PREFIX + "SpotLight shadow maps written: " + str(spot_shadow_count) + "\n"
                )
                if spot_shadow_requested > spot_shadow_count:
                    FreeCAD.Console.PrintWarning(
                        "[GAMEEXPORT][WARN] SpotLight shadow maps capped to prevent Castle shader overflow: requested="
                        + str(spot_shadow_requested)
                        + ", written="
                        + str(spot_shadow_count)
                        + "\n"
                    )
            except Exception:
                pass

    return count


def _insert_scene_light(scene, q, light_node) -> None:
    """Place light after navigation/viewpoint nodes and before geometry."""
    insert_index = 0
    config_tags = {q("Background"), q("NavigationInfo"), q("Viewpoint")}
    for idx, child in enumerate(scene):
        if child.tag in config_tags:
            insert_index = idx + 1
    scene.insert(insert_index, light_node)


def _make_directional_light(q, cfg: Dict[str, object]):
    direction = _direction_from_yaw_pitch(
        _float_config_value(cfg, "yaw", 0.0),
        _float_config_value(cfg, "pitch", -45.0),
    )
    color = _normalize_color(cfg.get("color", (1.0, 0.95, 0.85)))
    intensity = max(0.0, _float_config_value(cfg, "intensity", 1.0))
    ambient = _clamp(_float_config_value(cfg, "ambient_intensity", 0.18), 0.0, 1.0)
    attrs = {
        "DEF": LIGHT_DEF_PREFIX + "SunLight",
        "on": "true",
        "global": "true",
        "direction": _format_vec(direction),
        "color": _format_vec(color),
        "intensity": _format_float(intensity),
        "ambientIntensity": _format_float(ambient),
    }
    if bool(cfg.get("shadows", False)):
        attrs["shadows"] = "true"
    return ET.Element(q("DirectionalLight"), attrs)


def _make_point_light(q, entry: Dict[str, object], index: int):
    position = entry.get("position_mm", (0.0, 0.0, 0.0))
    if not isinstance(position, (list, tuple)) or len(position) != 3:
        position = (0.0, 0.0, 0.0)
    location = _transform_point_mm_to_x3d_m(
        (float(position[0]), float(position[1]), float(position[2]))
    )
    color = _normalize_color(entry.get("color", (1.0, 1.0, 1.0)))
    intensity = max(0.0, _float_config_value(entry, "intensity", 1.0))
    ambient = _clamp(
        _float_config_value(entry, "ambient_intensity", DEFAULT_POINT_LIGHT_AMBIENT_INTENSITY), 0.0, 1.0
    )
    radius = max(0.1, _float_config_value(entry, "radius", 12.0))
    attenuation = _normalize_attenuation(entry.get("attenuation", "1 0 0"))
    shadows = bool(entry.get("shadows", False))
    name = str(entry.get("name", "") or f"PointLight_{index + 1}")
    attrs = {
        "DEF": LIGHT_DEF_PREFIX + _safe_x3d_def(name),
        "on": "true",
        "global": "true",
        "location": _format_vec(location),
        "radius": _format_float(radius),
        "color": _format_vec(color),
        "intensity": _format_float(intensity),
        "ambientIntensity": _format_float(ambient),
        "attenuation": attenuation,
    }
    if shadows:
        attrs["shadows"] = "true"
        attrs["projectionNear"] = "0.050000"
        attrs["projectionFar"] = _format_float(radius)
    try:
        FreeCAD = __import__("FreeCAD")
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "[DEBUG] X3D PointLight written: name="
            + name
            + ", world_mm="
            + _format_vec((float(position[0]), float(position[1]), float(position[2])))
            + ", x3d_m="
            + _format_vec(location)
            + ", shadows="
            + str(shadows)
            + ", attenuation="
            + attenuation
            + "\n"
        )
    except Exception:
        pass
    return ET.Element(q("PointLight"), attrs)


def _make_spot_light(q, entry: Dict[str, object], index: int):
    """Create a downward ceiling SpotLight, optionally with a static shadow map."""
    position = entry.get("position_mm", (0.0, 0.0, 0.0))
    if not isinstance(position, (list, tuple)) or len(position) != 3:
        position = (0.0, 0.0, 0.0)
    location = _transform_point_mm_to_x3d_m(
        (float(position[0]), float(position[1]), float(position[2]))
    )
    photometric = _light_export_mode(entry) == LIGHT_MODE_PHOTOMETRIC
    color = (
        cct_to_rgb(_float_config_value(entry, "cct_kelvin", DEFAULT_PHOTOMETRIC_CCT_K))
        if photometric
        else _normalize_color(entry.get("color", (1.0, 1.0, 1.0)))
    )
    if photometric:
        intensity = photometric_candela(
            _float_config_value(entry, "lumens", DEFAULT_PHOTOMETRIC_LUMENS),
            _float_config_value(
                entry, "beam_angle_deg", DEFAULT_PHOTOMETRIC_BEAM_ANGLE_DEG
            ),
        )
        ambient = 0.0
    else:
        intensity = max(0.0, _float_config_value(entry, "intensity", 1.0))
        ambient = _clamp(
            _float_config_value(entry, "ambient_intensity", 0.02), 0.0, 1.0
        )
    radius = max(0.1, _float_config_value(entry, "radius", 4.0))
    attenuation = _normalize_attenuation(
        "0 0 1" if photometric else entry.get("attenuation", "1 0.30 0.06")
    )
    if photometric:
        full_beam_deg = _clamp(
            _float_config_value(
                entry, "beam_angle_deg", DEFAULT_PHOTOMETRIC_BEAM_ANGLE_DEG
            ),
            1.0,
            179.0,
        )
        cutoff = math.radians(full_beam_deg * 0.5)
        beam = cutoff * 0.85
    else:
        cutoff = _clamp(
            _float_config_value(entry, "cut_off_angle", DEFAULT_SPOT_CUTOFF_ANGLE),
            0.01,
            math.pi / 2.0,
        )
        beam = _clamp(
            _float_config_value(entry, "beam_width", DEFAULT_SPOT_BEAM_WIDTH),
            0.0,
            cutoff,
        )
    shadows = bool(entry.get("shadows", False))
    name = str(entry.get("name", "") or f"SpotLight_{index + 1}")
    attrs = {
        "DEF": LIGHT_DEF_PREFIX + _safe_x3d_def(name),
        "on": "true",
        "global": "true",
        "location": _format_vec(location),
        # FreeCAD is Z-up. A ceiling luminaire points along -Z, which becomes
        # -Y after the exporter's fixed -90 degree X-axis conversion.
        "direction": "0 -1 0",
        "radius": _format_float(radius),
        "beamWidth": _format_float(beam),
        "cutOffAngle": _format_float(cutoff),
        "color": _format_vec(color),
        "intensity": _format_float(intensity),
        "ambientIntensity": _format_float(ambient),
        "attenuation": attenuation,
    }
    if shadows:
        attrs["shadows"] = "true"
        attrs["projectionNear"] = _format_float(
            max(0.05, min(radius * 0.25, _float_config_value(entry, "projection_near", 0.10)))
        )
        attrs["projectionFar"] = _format_float(radius)
    light = ET.Element(q("SpotLight"), attrs)
    if shadows:
        shadow_size = int(
            _clamp(
                _float_config_value(entry, "shadow_map_size", DEFAULT_SPOT_SHADOW_MAP_SIZE),
                64,
                2048,
            )
        )
        ET.SubElement(
            light,
            q("GeneratedShadowMap"),
            {
                "containerField": "defaultShadowMap",
                "update": "NEXT_FRAME_ONLY",
                "size": str(shadow_size),
            },
        )
    try:
        FreeCAD = __import__("FreeCAD")
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "[DEBUG] X3D SpotLight written: name="
            + name
            + ", x3d_m="
            + _format_vec(location)
            + ", radius="
            + _format_float(radius)
            + ", shadows="
            + str(shadows)
            + ", photometric="
            + str(photometric)
            + ", intensity_cd="
            + _format_float(intensity)
            + "\n"
        )
    except Exception:
        pass
    return light


def _light_export_mode(entry: Dict[str, object]) -> str:
    """Normalize the local-light algorithm while preserving legacy input."""
    mode = str(entry.get("light_mode", LIGHT_MODE_POINT_CLASSIC) or LIGHT_MODE_POINT_CLASSIC)
    if mode not in {
        LIGHT_MODE_SPOT_SHADOW_MAP,
        LIGHT_MODE_SPOT_NO_SHADOWS,
        LIGHT_MODE_POINT_CLASSIC,
        LIGHT_MODE_PHOTOMETRIC,
    }:
        return LIGHT_MODE_POINT_CLASSIC
    return mode


def photometric_candela(lumens: float, beam_angle_deg: float) -> float:
    """Convert luminous flux to center candela for a uniform conical beam.

    ``beam_angle_deg`` is the complete beam angle. The relation is
    I = Phi / Omega with Omega = 2*pi*(1-cos(angle/2)). This is an
    intentionally explicit approximation for the experimental mode; an IES
    distribution can replace it later without changing the legacy modes.
    """
    flux = max(0.0, float(lumens))
    full_angle = _clamp(float(beam_angle_deg), 1.0, 179.0)
    half_angle = math.radians(full_angle * 0.5)
    solid_angle = 2.0 * math.pi * (1.0 - math.cos(half_angle))
    if solid_angle <= 1e-12:
        return 0.0
    return flux / solid_angle


def cct_to_rgb(cct_kelvin: float) -> Tuple[float, float, float]:
    """Return a display RGB approximation for a correlated color temperature."""
    temperature = _clamp(float(cct_kelvin), 1000.0, 40000.0) / 100.0
    if temperature <= 66.0:
        red = 255.0
        green = 99.4708025861 * math.log(temperature) - 161.1195681661
        blue = 0.0 if temperature <= 19.0 else 138.5177312231 * math.log(temperature - 10.0) - 305.0447927307
    else:
        red = 329.698727446 * ((temperature - 60.0) ** -0.1332047592)
        green = 288.1221695283 * ((temperature - 60.0) ** -0.0755148492)
        blue = 255.0
    return tuple(_clamp(component, 0.0, 255.0) / 255.0 for component in (red, green, blue))


def _direction_from_yaw_pitch(yaw_deg: float, pitch_deg: float) -> Tuple[float, float, float]:
    """Convert panel yaw/pitch in FreeCAD Z-up coordinates to X3D Y-up direction."""
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    horizontal = math.cos(pitch)
    freecad_direction = (
        horizontal * math.sin(yaw),
        -horizontal * math.cos(yaw),
        math.sin(pitch),
    )
    return _rotate_freecad_vector_to_x3d(freecad_direction)


def _transform_point_mm_to_x3d_m(position_mm: Tuple[float, float, float]) -> Tuple[float, float, float]:
    rotated = _rotate_freecad_vector_to_x3d(position_mm)
    return (rotated[0] * 0.001, rotated[1] * 0.001, rotated[2] * 0.001)


def _rotate_freecad_vector_to_x3d(vector: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Apply the same -90 degree X rotation used by the scene transform."""
    x, y, z = vector
    return (x, z, -y)


def _remove_gameexport_light_nodes(node) -> None:
    """Remove previous GameExport light nodes recursively before reinserting them."""
    for child in list(node):
        if _is_gameexport_light_node(child):
            node.remove(child)
            continue
        _remove_gameexport_light_nodes(child)


def _is_gameexport_light_node(node) -> bool:
    tag = _local_name(getattr(node, "tag", ""))
    if tag not in {"DirectionalLight", "PointLight", "SpotLight"}:
        return False
    return str(getattr(node, "attrib", {}).get("DEF", "")).startswith(LIGHT_DEF_PREFIX)


def _normalize_color(value) -> Tuple[float, float, float]:
    if isinstance(value, str):
        try:
            parts = [float(part.strip()) for part in value.split(",")]
            value = parts
        except Exception:
            value = (1.0, 1.0, 1.0)
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        value = (1.0, 1.0, 1.0)
    numbers = [float(value[0]), float(value[1]), float(value[2])]
    if any(component > 1.0 for component in numbers):
        numbers = [component / 255.0 for component in numbers]
    return tuple(_clamp(component, 0.0, 1.0) for component in numbers)


def _normalize_attenuation(value) -> str:
    if isinstance(value, str):
        parts = value.replace(",", " ").split()
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        parts = []
    numbers = []
    for part in parts[:3]:
        try:
            numbers.append(max(0.0, float(part)))
        except Exception:
            numbers.append(0.0)
    while len(numbers) < 3:
        numbers.append(0.0)
    if numbers == [0.0, 0.0, 0.0]:
        numbers = [1.0, 0.25, 0.04]
    return " ".join(_format_float(number) for number in numbers)


def _float_config_value(data: Dict[str, object], key: str, default: float) -> float:
    try:
        value = data.get(key, default)
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_x3d_def(text: str) -> str:
    safe = []
    for char in text:
        safe.append(char if (char.isascii() and (char.isalnum() or char == "_")) else "_")
    result = "".join(safe).strip("_") or "Light"
    if result[0].isdigit():
        result = "Light_" + result
    return result


def _format_vec(vector: Tuple[float, float, float]) -> str:
    return " ".join(_format_float(component) for component in vector)


def _format_float(value: float) -> str:
    return f"{float(value):.6f}"


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _read_x3d_text(path: Path) -> tuple[Optional[str], bool]:
    FreeCAD = __import__("FreeCAD")
    try:
        raw = path.read_bytes()
    except Exception as exc:  # pragma: no cover - IO guard
        FreeCAD.Console.PrintWarning(LOG_PREFIX + f"read failed: {exc}\n")
        return None, False

    is_gzip = len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B
    payload = raw
    if is_gzip:
        try:
            payload = gzip.decompress(raw)
            FreeCAD.Console.PrintMessage(LOG_PREFIX + "Compressed X3D detected; applying fix\n")
        except Exception as exc:
            FreeCAD.Console.PrintWarning(LOG_PREFIX + f"gzip decompress failed: {exc}\n")
            return None, True

    try:
        return payload.decode("utf-8"), is_gzip
    except UnicodeDecodeError as exc:
        FreeCAD.Console.PrintWarning(LOG_PREFIX + f"UTF-8 decode failed: {exc}\n")
        return None, is_gzip


def _write_x3d_text(path: Path, text: str, as_gzip: bool) -> None:
    payload = text.encode("utf-8")
    if as_gzip:
        payload = gzip.compress(payload)
    path.write_bytes(payload)


def _force_gzip_to_plain(path: Path) -> None:
    FreeCAD = __import__("FreeCAD")
    try:
        raw = path.read_bytes()
        if len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B:
            decompressed = gzip.decompress(raw)
            path.write_bytes(decompressed)
            FreeCAD.Console.PrintWarning(
                LOG_PREFIX + "Forced gzip->plain conversion for .x3d to avoid invalid-character load errors.\n"
            )
    except Exception as exc:
        FreeCAD.Console.PrintWarning(LOG_PREFIX + f"force gzip->plain failed: {exc}\n")


def _geometry_export_mode(cfg: Optional[Dict[str, object]]) -> str:
    if not isinstance(cfg, dict):
        return DEFAULT_GEOMETRY_EXPORT_MODE
    requested = str(cfg.get("mode", DEFAULT_GEOMETRY_EXPORT_MODE) or "").strip()
    if requested.lower() == "classic":
        return "Classic"
    return "Optimized"


def _apply_geometry_export_mode(
    scene: ET.Element,
    q,
    cfg: Optional[Dict[str, object]],
) -> int:
    """Reuse identical rendered subtrees while preserving all placements."""
    FreeCAD = __import__("FreeCAD")
    mode = _geometry_export_mode(cfg)
    FreeCAD.Console.PrintMessage(
        LOG_PREFIX + "X3D geometry export mode: " + mode + "\n"
    )
    if mode == "Classic":
        return 0

    transform = _find_freecad_transform(scene, q)
    if transform is None:
        FreeCAD.Console.PrintWarning(
            LOG_PREFIX + "Geometry instancing skipped: FreeCAD transform not found\n"
        )
        return 0

    try:
        minimum_payload = int(
            (cfg or {}).get("minimum_payload_chars", MIN_INSTANCE_PAYLOAD_CHARS)
        )
    except (TypeError, ValueError):
        minimum_payload = MIN_INSTANCE_PAYLOAD_CHARS
    return _instance_repeated_x3d_subtrees(
        transform,
        minimum_payload_chars=max(0, minimum_payload),
    )


def _instance_repeated_x3d_subtrees(
    root: ET.Element,
    minimum_payload_chars: int = MIN_INSTANCE_PAYLOAD_CHARS,
) -> int:
    """Replace later identical Group/Switch/Shape nodes with type-safe USE.

    DEF names are ignored during comparison. Existing USE nodes are resolved
    to their previously defined content, so only complete visual matches are
    reused. Transform nodes are never replaced, preserving every placement.
    """
    def_nodes = {}
    reserved_defs = set()
    for node in _iter_def_scope_nodes(root):
        node_def = str(node.attrib.get("DEF", "") or "").strip()
        if not node_def:
            continue
        reserved_defs.add(node_def)
        def_nodes.setdefault(node_def, node)

    digest_cache = {}

    def digest_node(node, resolving=None):
        cache_key = id(node)
        cached = digest_cache.get(cache_key)
        if cached is not None:
            return cached

        resolving = set(resolving or ())
        if cache_key in resolving:
            marker = ("cycle:" + str(node.attrib.get("DEF", ""))).encode("utf-8")
            result = (hashlib.sha256(marker).hexdigest(), len(marker))
            digest_cache[cache_key] = result
            return result
        resolving.add(cache_key)

        digest = hashlib.sha256()
        local_tag = _local_name(node.tag)
        digest.update(local_tag.encode("utf-8", errors="replace"))
        payload_chars = len(local_tag)

        node_use = str(node.attrib.get("USE", "") or "").strip()
        if node_use:
            target = def_nodes.get(node_use)
            if target is not None:
                target_digest, target_size = digest_node(target, resolving)
                digest.update(b"\x00RESOLVED_USE\x00")
                digest.update(target_digest.encode("ascii"))
                payload_chars += target_size
            else:
                digest.update(b"\x00UNRESOLVED_USE\x00")
                digest.update(node_use.encode("utf-8", errors="replace"))
                payload_chars += len(node_use)
            container_field = str(node.attrib.get("containerField", "") or "")
            if container_field:
                digest.update(b"\x00containerField\x00")
                digest.update(container_field.encode("utf-8", errors="replace"))
                payload_chars += len(container_field)
        else:
            for key, value in sorted(node.attrib.items()):
                if key in {"DEF", "USE"}:
                    continue
                text = str(value)
                digest.update(b"\x00ATTR\x00")
                digest.update(str(key).encode("utf-8", errors="replace"))
                digest.update(b"\x00")
                digest.update(text.encode("utf-8", errors="replace"))
                payload_chars += len(str(key)) + len(text)
            for child in list(node):
                child_digest, child_size = digest_node(child, resolving)
                digest.update(b"\x00CHILD\x00")
                digest.update(child_digest.encode("ascii"))
                payload_chars += child_size

        result = (digest.hexdigest(), payload_chars)
        digest_cache[cache_key] = result
        return result

    eligible_tags = {"Group", "Switch", "Shape"}
    seen = {}
    generated_index = 1
    replacement_count = 0

    def next_instance_def() -> str:
        nonlocal generated_index
        while True:
            candidate = INSTANCE_DEF_PREFIX + f"{generated_index:05d}"
            generated_index += 1
            if candidate not in reserved_defs:
                reserved_defs.add(candidate)
                return candidate

    def visit(parent) -> None:
        nonlocal replacement_count
        for child in list(parent):
            local_tag = _local_name(child.tag)
            if local_tag not in eligible_tags or child.attrib.get("USE"):
                visit(child)
                continue

            digest_value, payload_chars = digest_node(child)
            key = (local_tag, digest_value)
            previous = seen.get(key)
            if previous is not None and payload_chars >= minimum_payload_chars:
                _source_node, source_def = previous
                replacement = ET.Element(child.tag, {"USE": source_def})
                container_field = child.attrib.get("containerField")
                if container_field:
                    replacement.attrib["containerField"] = container_field
                child_index = list(parent).index(child)
                parent.remove(child)
                parent.insert(child_index, replacement)
                replacement_count += 1
                continue

            source_def = str(child.attrib.get("DEF", "") or "").strip()
            if not source_def:
                source_def = next_instance_def()
                child.attrib["DEF"] = source_def
                def_nodes[source_def] = child
            seen[key] = (child, source_def)
            visit(child)

    visit(root)
    return replacement_count


def _serialize_xml(root: ET.Element, doctype_line: str) -> str:
    buf = BytesIO()
    ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
    text = buf.getvalue().decode("utf-8")

    if doctype_line and doctype_line not in text:
        lines = text.splitlines()
        if lines and lines[0].startswith("<?xml"):
            lines.insert(1, doctype_line)
        else:
            lines.insert(0, doctype_line)
        text = "\n".join(lines) + "\n"
    return text


def _iter_def_scope_nodes(root: ET.Element):
    """Yield nodes in one X3D DEF scope without entering ProtoDeclare bodies."""
    yield root
    for child in list(root):
        if _local_name(child.tag) == "ProtoDeclare":
            continue
        yield from _iter_def_scope_nodes(child)


def _ensure_unique_def_names(scene: ET.Element) -> int:
    """Rename duplicate X3D DEF values while preserving the first definition.

    FreeCADGui.export may emit the same internal Coin name for multiple linked
    Mesh instances, for example SoFCIndexedFaceSet. X3D requires every DEF in
    a scene name scope to be unique. Keeping the first DEF also keeps existing
    USE references deterministic; later full node definitions only receive a
    numeric suffix and their geometry, placement and appearance stay intact.
    """
    nodes = list(_iter_def_scope_nodes(scene))
    reserved = {
        str(node.attrib.get("DEF", "") or "")
        for node in nodes
        if str(node.attrib.get("DEF", "") or "")
    }
    seen = set()
    next_suffix = {}
    renamed = 0

    for node in nodes:
        original = str(node.attrib.get("DEF", "") or "")
        if not original:
            continue
        if original not in seen:
            seen.add(original)
            continue

        suffix = int(next_suffix.get(original, 2))
        candidate = f"{original}_{suffix}"
        while candidate in reserved or candidate in seen:
            suffix += 1
            candidate = f"{original}_{suffix}"
        next_suffix[original] = suffix + 1
        node.set("DEF", candidate)
        reserved.add(candidate)
        seen.add(candidate)
        renamed += 1

    if renamed:
        FreeCAD = __import__("FreeCAD")
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Normalized duplicate X3D DEF names: "
            + str(renamed)
            + " renamed\n"
        )
    return renamed


def _extract_doctype(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("<!DOCTYPE"):
            # FreeCAD sometimes emits XHTML doctype; normalize to X3D for compatibility.
            return X3D_DOCTYPE
    return X3D_DOCTYPE


def _detect_namespace(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[0][1:]
    return ""


def _local_name(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _split_exportables(objects: Iterable[object]) -> Tuple[List[object], List[Tuple[str, str, str]]]:
    exportable: List[object] = []
    skipped: List[Tuple[str, str, str]] = []
    for obj in objects:
        ok, reason = _is_exportable_object(obj)
        if ok:
            exportable.append(obj)
            continue
        label = getattr(obj, "Label", "") or getattr(obj, "Name", "Unknown")
        type_id = getattr(obj, "TypeId", "UnknownType")
        skipped.append((label, type_id, reason))
    return exportable, skipped


def _linked_master_ids(objects: Iterable[object]) -> set:
    result = set()
    for obj in objects:
        if str(getattr(obj, "TypeId", "") or "") != "App::Link":
            continue
        target = obj
        seen = set()
        while str(getattr(target, "TypeId", "") or "") == "App::Link":
            marker = id(target)
            if marker in seen:
                target = None
                break
            seen.add(marker)
            target = getattr(target, "LinkedObject", None)
            if target is None:
                break
        if target is not None:
            result.add(id(target))
    return result


def _normalized_object_text(obj) -> str:
    try:
        linked = getattr(obj, "LinkedObject", None) if obj is not None else None
    except Exception:
        linked = None
    text = " ".join(
        (
            str(getattr(obj, "Name", "") or ""),
            str(getattr(obj, "Label", "") or ""),
            str(getattr(linked, "Name", "") or ""),
            str(getattr(linked, "Label", "") or ""),
        )
    )
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()


def _object_export_override(obj) -> Optional[bool]:
    """Return an explicit export choice from object or linked master metadata."""
    try:
        linked = getattr(obj, "LinkedObject", None)
    except Exception:
        linked = None
    for candidate in (obj, linked):
        if candidate is None:
            continue
        try:
            if hasattr(candidate, "GameExportExclude") and bool(candidate.GameExportExclude):
                return False
        except Exception:
            pass
    for candidate in (obj, linked):
        if candidate is None:
            continue
        try:
            if hasattr(candidate, "GameExportInclude") and bool(candidate.GameExportInclude):
                return True
        except Exception:
            pass
    return None


def _has_solid_or_mesh_geometry(obj) -> bool:
    """Return True for an object or linked target with solid or mesh geometry."""
    candidate = obj
    seen = set()
    while candidate is not None and id(candidate) not in seen:
        seen.add(id(candidate))
        shape = getattr(candidate, "Shape", None)
        if shape is not None:
            try:
                solids = list(getattr(shape, "Solids", []) or [])
                if any(
                    float(getattr(solid, "Volume", 0.0) or 0.0) > 1e-6
                    for solid in solids
                ):
                    return True
            except Exception:
                pass
        mesh = getattr(candidate, "Mesh", None)
        if mesh is not None:
            try:
                if int(getattr(mesh, "CountFacets", 0) or 0) > 0:
                    return True
            except Exception:
                pass
        try:
            candidate = getattr(candidate, "LinkedObject", None)
        except Exception:
            candidate = None
    return False


def _is_object_visible(obj, _visited=None) -> bool:
    if obj is None:
        return True
    if _visited is None:
        _visited = set()
    marker = id(obj)
    if marker in _visited:
        return True
    _visited.add(marker)

    view = getattr(obj, "ViewObject", None)
    if view is not None:
        try:
            if not bool(getattr(view, "Visibility", True)):
                return False
        except Exception:
            pass

    # Only inspect actual group membership. InList may also contain dependency
    # owners whose visibility must not affect the exported object.
    for parent in list(getattr(obj, "InList", []) or []):
        members = getattr(parent, "Group", None)
        if members is None:
            continue
        try:
            is_member = any(member is obj for member in list(members or []))
        except Exception:
            continue
        if is_member and not _is_object_visible(parent, _visited):
            return False
    return True


def _is_planar_helper_object(obj) -> bool:
    text = _normalized_object_text(obj)
    return any(keyword in text for keyword in PLANAR_HELPER_KEYWORDS)


def _is_internal_container_member(obj) -> bool:
    """Detect geometry stored in library, master or reference containers."""
    for parent in list(getattr(obj, "InList", []) or []):
        members = getattr(parent, "Group", None)
        if members is None:
            continue
        try:
            is_member = any(member is obj for member in list(members or []))
        except Exception:
            continue
        if not is_member:
            continue
        text = " " + _normalized_object_text(parent)
        if any(keyword in text for keyword in INTERNAL_CONTAINER_KEYWORDS):
            return True
    return False


def _log_skipped_objects(skipped: List[Tuple[str, str, str]], max_rows: int = 25) -> None:
    FreeCAD = __import__("FreeCAD")
    FreeCAD.Console.PrintWarning(
        LOG_PREFIX + f"Skipping {len(skipped)} non-exportable objects (showing up to {max_rows})\n"
    )
    for label, type_id, reason in skipped[:max_rows]:
        FreeCAD.Console.PrintWarning(LOG_PREFIX + f"SKIP: {label} [{type_id}] -> {reason}\n")
    if len(skipped) > max_rows:
        FreeCAD.Console.PrintWarning(LOG_PREFIX + f"... and {len(skipped) - max_rows} more skipped\n")


def _is_exportable_object(obj: object) -> Tuple[bool, str]:
    if _is_auxiliary_export_object(obj):
        return False, "GameEngineExport helper object"

    type_id = str(getattr(obj, "TypeId", "") or "")

    if "Part2DObject" in type_id:
        return False, "2D drafting/symbol geometry"
    if _is_planar_helper_object(obj):
        return False, "named 2D helper geometry"

    non_geo_prefixes = (
        "App::DocumentObjectGroup",
        "App::Origin",
        "App::GeoFeatureGroupExtension",
        "Spreadsheet::",
        "TechDraw::",
        "Drawing::",
        "Path::",
        "Sketcher::SketchObject",
    )
    if any(type_id.startswith(prefix) for prefix in non_geo_prefixes):
        return False, "non-geometry helper/container"

    if hasattr(obj, "Shape"):
        try:
            shape = getattr(obj, "Shape")
            if shape is not None and hasattr(shape, "isNull") and not shape.isNull():
                solids = list(getattr(shape, "Solids", []) or [])
                if any(float(getattr(solid, "Volume", 0.0) or 0.0) > 1e-6 for solid in solids):
                    return True, ""
                faces = list(getattr(shape, "Faces", []) or [])
                if faces:
                    return True, ""
                edges = list(getattr(shape, "Edges", []) or [])
                if edges:
                    return False, "wire-only 2D geometry"
        except Exception:
            pass

    if hasattr(obj, "Mesh"):
        try:
            mesh = getattr(obj, "Mesh")
            facets = int(getattr(mesh, "CountFacets", 0))
            if facets > 0:
                return True, ""
        except Exception:
            pass

    if hasattr(obj, "Points"):
        try:
            pts = getattr(obj, "Points")
            count = int(getattr(pts, "CountPoints", 0))
            if count > 0:
                return True, ""
        except Exception:
            pass

    if hasattr(obj, "Group") and not (hasattr(obj, "Shape") or hasattr(obj, "Mesh")):
        return False, "group/container without exportable geometry"

    if type_id:
        return False, "unsupported or empty geometry for X3D export"
    return False, "unknown object type"


def _is_auxiliary_export_object(obj: object) -> bool:
    name = str(getattr(obj, "Name", "") or "")
    label = str(getattr(obj, "Label", "") or "")
    prefixes = ("CGE_TempLightPreview", "CGE_LightOrigin_")
    return any(name.startswith(prefix) or label.startswith(prefix) for prefix in prefixes)


__all__: List[str] = [
    "collect_default_scene_objects",
    "export_to_x3d",
    "decorate_x3d",
    "diagnose_export_candidates",
    "apply_x3d_material_lighting_profile",
    "detect_skybox_faces",
    "photometric_candela",
    "cct_to_rgb",
]
