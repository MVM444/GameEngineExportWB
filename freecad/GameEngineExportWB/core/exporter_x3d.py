"""X3D exporter helpers for Game Engine Export WB.

Descripcion rapida: exporta via FreeCADGui, filtra la escena y aplica conversion fija de ejes.
Version interna: 2026.09.01-game-export-exclude-hard-v1.
Fecha y hora: 2026-09-01 12:20 America/Costa_Rica.
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
from . import solar as solar_core


LOG_PREFIX = "[GAMEEXPORT] "
DEBUG_VERSION = "2026-09-01-game-export-exclude-hard-v1"
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
SOLAR_CONTROL_DEF_PREFIX = "GameExport_Solar"
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
    skipped_forced = 0
    for obj in list(selected_objects or []):
        if obj is None or id(obj) in excluded_ids or id(obj) in seen_ids:
            continue
        if _object_export_override(obj) is False:
            skipped_forced += 1
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
        + ", forced_excluded="
        + str(skipped_forced)
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
        if _object_export_override(obj) is False:
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
    _remove_interactive_solar_nodes(scene)
    _remove_gameexport_light_nodes(scene)
    _remove_walk_ground_collision(scene, q)
    navigation_cfg = _normalize_navigation_cfg(lighting_cfg)
    _apply_environment_background(scene, q, file_path, environment_cfg)
    _ensure_navigation(scene, q, navigation_cfg)
    _apply_mm_to_m_axis_transform(scene, q)
    _ensure_walk_ground_collision(scene, q, navigation_cfg)
    _insert_viewpoint(scene, q, gamestart_meta, navigation_cfg)
    light_count = _insert_lights(scene, q, lighting_cfg)
    solar_control_inserted = _insert_interactive_solar_controller(
        scene,
        q,
        lighting_cfg,
    )
    if solar_control_inserted:
        root.attrib["profile"] = "Immersive"
        root.attrib["version"] = "4.0"
        FreeCAD.Console.PrintMessage(
            LOG_PREFIX
            + "Inserted interactive solar controls: J/L hour, N/M day, U/O week, C diagram, R reset\n"
        )
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
    bounds = _freecad_xyz_bounds_from_coordinates(node, q)
    if bounds is None:
        return None
    min_x, max_x, min_y, max_y, _min_z, _max_z = bounds
    return min_x, max_x, min_y, max_y


def _freecad_xyz_bounds_from_coordinates(
    node,
    q,
) -> Optional[Tuple[float, float, float, float, float, float]]:
    """Return raw FreeCAD-coordinate bounds from exported Coordinate nodes.

    FreeCAD's X3D exporter bakes object placements into these coordinates. The
    enclosing ``FreeCAD_mm_to_m`` transform then performs the shared mm-to-m
    scale and Z-up to Y-up rotation, so these bounds are a stable source for a
    renderer-neutral solar shadow volume.
    """
    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")
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
            z_value = values[index + 2]
            min_x = min(min_x, x_value)
            max_x = max(max_x, x_value)
            min_y = min(min_y, y_value)
            max_y = max(max_y, y_value)
            min_z = min(min_z, z_value)
            max_z = max(max_z, z_value)
            found = True
    if not found:
        return None
    return min_x, max_x, min_y, max_y, min_z, max_z


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


def _solar_shadow_projection_config(
    scene,
    q,
    visualization: Dict[str, object],
) -> Dict[str, object]:
    """Build a direction-independent orthographic volume around scene geometry.

    Castle can auto-fit this volume, but that fit is performed from the light
    direction present while the scene loads. Interactive Solar changes the
    direction afterwards. A bounding sphere gives us a stable rectangle and
    depth interval; only the light-camera location and up vector must then move
    with the sun.
    """
    transform = next(
        (
            child
            for child in list(scene)
            if child.tag == q("Transform")
            and child.attrib.get("DEF") == TRANSFORM_DEF
        ),
        None,
    )
    bounds = (
        _freecad_xyz_bounds_from_coordinates(transform, q)
        if transform is not None
        else None
    )
    if bounds is not None:
        min_x, max_x, min_y, max_y, min_z, max_z = bounds
        center = (
            (min_x + max_x) * 0.0005,
            (min_z + max_z) * 0.0005,
            -(min_y + max_y) * 0.0005,
        )
        half_extents = (
            (max_x - min_x) * 0.0005,
            (max_z - min_z) * 0.0005,
            (max_y - min_y) * 0.0005,
        )
        radius = math.sqrt(sum(component * component for component in half_extents))
    else:
        center = tuple(visualization.get("center_x3d_m", (0.0, 0.0, 0.0)))
        radius = float(visualization.get("radius_m", 30.0))

    # A modest margin includes tessellation and thin primitives not represented
    # by Coordinate nodes, without sacrificing shadow-map precision.
    radius = max(1.0, radius * 1.15 + 0.25)
    distance = radius * 2.0
    return {
        "center": center,
        "radius": radius,
        "distance": distance,
        "rectangle": (-radius, -radius, radius, radius),
        "near": max(0.05, distance - radius),
        "far": distance + radius,
    }


def _solar_shadow_projection_location(
    center: Tuple[float, float, float],
    direction: Tuple[float, float, float],
    distance: float,
) -> Tuple[float, float, float]:
    """Place the directional-light camera upstream of the scene center."""
    return tuple(
        float(center[index]) - float(direction[index]) * float(distance)
        for index in range(3)
    )  # type: ignore[return-value]


def _solar_shadow_up_vector(
    direction: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    """Return a stable light-camera up vector orthogonal to its direction."""
    direction_y = float(direction[1])
    if abs(direction_y) > 0.9999:
        return (0.0, 0.0, 1.0)
    # Project world-up onto the plane normal to the light direction. Castle
    # accepts a non-normalized value and orthogonalizes it internally.
    return (
        -direction_y * float(direction[0]),
        1.0 - direction_y * direction_y,
        -direction_y * float(direction[2]),
    )


def _insert_interactive_solar_controller(
    scene,
    q,
    lighting_cfg: Optional[Dict[str, object]],
) -> bool:
    """Insert CastleScript controls that vary the exported sun at runtime."""
    if not isinstance(lighting_cfg, dict):
        return False
    global_cfg = lighting_cfg.get("global")
    if not isinstance(global_cfg, dict):
        return False
    control = global_cfg.get("interactive_solar")
    if not isinstance(control, dict) or not bool(control.get("enabled", False)):
        return False

    light_def = LIGHT_DEF_PREFIX + "SunLight"
    light = next(
        (
            node
            for node in scene.iter()
            if _local_name(getattr(node, "tag", "")) == "DirectionalLight"
            and node.attrib.get("DEF") == light_def
        ),
        None,
    )
    if light is None:
        return False

    try:
        year = int(control.get("year"))
        days_in_year = max(365, min(366, int(control.get("days_in_year", 365))))
        initial_day = max(
            1,
            min(days_in_year, int(control.get("initial_day_of_year", 1))),
        )
        initial_hour = max(0, min(23, int(control.get("initial_hour", 12))))
        latitude_deg = float(control.get("latitude_deg"))
        longitude_deg = float(control.get("longitude_deg"))
        timezone_hours = float(control.get("timezone_hours"))
        north_deg = float(control.get("north_deg", 0.0))
        day_step = max(1, min(31, int(control.get("day_step", 1))))
        week_step = max(1, min(31, int(control.get("week_step_days", 7))))
    except (TypeError, ValueError):
        return False

    visualization = _solar_visualization_config(control)
    initial_sun = solar_core.approximate_sun_position(
        initial_day,
        initial_hour,
        latitude_deg,
        longitude_deg,
        timezone_hours,
        north_deg,
    )
    initial_direction = (
        -initial_sun[0],
        -initial_sun[2],
        initial_sun[1],
    )
    base_intensity = max(0.0, _float_config_value(global_cfg, "intensity", 1.0))
    base_ambient = _clamp(
        _float_config_value(global_cfg, "ambient_intensity", 0.18),
        0.0,
        1.0,
    )
    night_ambient = 0.02
    initial_daylight = max(0.0, min(1.0, initial_sun[2] * 2.0))
    light.set("direction", _format_vec(initial_direction))
    light.set("intensity", _format_float(base_intensity * initial_daylight))
    light.set(
        "ambientIntensity",
        _format_float(
            night_ambient + (base_ambient - night_ambient) * initial_daylight
        ),
    )

    shadow_projection = _solar_shadow_projection_config(scene, q, visualization)
    shadow_projection_enabled = light.attrib.get("shadows") == "true"
    if shadow_projection_enabled:
        light.set(
            "projectionLocation",
            _format_vec(
                _solar_shadow_projection_location(
                    shadow_projection["center"],
                    initial_direction,
                    float(shadow_projection["distance"]),
                )
            ),
        )
        light.set(
            "projectionRectangle",
            _format_float_list(shadow_projection["rectangle"]),
        )
        light.set("projectionNear", _format_float(shadow_projection["near"]))
        light.set("projectionFar", _format_float(shadow_projection["far"]))
        light.set("up", _format_vec(_solar_shadow_up_vector(initial_direction)))

    key_sensor_def = SOLAR_CONTROL_DEF_PREFIX + "KeySensor"
    controller_def = SOLAR_CONTROL_DEF_PREFIX + "Controller"
    calculator_def = SOLAR_CONTROL_DEF_PREFIX + "Calculator"
    hud_sensor_def = SOLAR_CONTROL_DEF_PREFIX + "HUDSensor"
    hud_def = SOLAR_CONTROL_DEF_PREFIX + "HUD"
    hud_text_def = SOLAR_CONTROL_DEF_PREFIX + "HUDText"
    hud_compass_script_def = SOLAR_CONTROL_DEF_PREFIX + "HUDCompassScript"
    hud_compass_dial_def = SOLAR_CONTROL_DEF_PREFIX + "HUDCompassDial"
    visualization_switch_def = SOLAR_CONTROL_DEF_PREFIX + "VisualizationSwitch"
    sun_transform_def = SOLAR_CONTROL_DEF_PREFIX + "SunTransform"
    sun_material_def = SOLAR_CONTROL_DEF_PREFIX + "SunMaterial"
    ray_transform_def = SOLAR_CONTROL_DEF_PREFIX + "RayTransform"
    ray_material_def = SOLAR_CONTROL_DEF_PREFIX + "RayMaterial"

    scene.append(
        ET.Element(
            q("KeySensor"),
            {
                "DEF": key_sensor_def,
                "description": "GameEngineExport interactive solar controls",
                "enabled": "true",
            },
        )
    )

    controller = ET.Element(
        q("Script"),
        {
            "DEF": controller_def,
            "url": _x3d_mfstring(_solar_controller_castlescript()),
        },
    )
    _append_script_field(controller, q, "key_press", "SFString", "inputOnly")
    _append_script_field(
        controller,
        q,
        "year",
        "SFInt32",
        "initializeOnly",
        str(year),
    )
    _append_script_field(
        controller,
        q,
        "days_in_year",
        "SFInt32",
        "initializeOnly",
        str(days_in_year),
    )
    _append_script_field(
        controller,
        q,
        "day",
        "SFInt32",
        "initializeOnly",
        str(initial_day),
    )
    _append_script_field(
        controller,
        q,
        "hour",
        "SFInt32",
        "initializeOnly",
        str(initial_hour),
    )
    _append_script_field(
        controller,
        q,
        "initial_day",
        "SFInt32",
        "initializeOnly",
        str(initial_day),
    )
    _append_script_field(
        controller,
        q,
        "initial_hour",
        "SFInt32",
        "initializeOnly",
        str(initial_hour),
    )
    _append_script_field(
        controller,
        q,
        "day_step",
        "SFInt32",
        "initializeOnly",
        str(day_step),
    )
    _append_script_field(
        controller,
        q,
        "week_step",
        "SFInt32",
        "initializeOnly",
        str(week_step),
    )
    _append_script_field(
        controller,
        q,
        "handled",
        "SFBool",
        "initializeOnly",
        "false",
    )
    _append_script_field(controller, q, "state_changed", "SFVec2f", "outputOnly")
    _append_script_field(controller, q, "label_changed", "MFString", "outputOnly")
    _append_script_field(
        controller,
        q,
        "diagram_choice",
        "SFInt32",
        "initializeOnly",
        "0",
    )
    _append_script_field(controller, q, "diagram_changed", "SFInt32", "outputOnly")
    scene.append(controller)

    calculator = ET.Element(
        q("Script"),
        {
            "DEF": calculator_def,
            "url": _x3d_mfstring(_solar_calculator_castlescript()),
        },
    )
    _append_script_field(calculator, q, "state", "SFVec2f", "inputOnly")
    for name, value in (
        ("latitude_rad", math.radians(latitude_deg)),
        ("longitude_deg", longitude_deg),
        ("timezone_hours", timezone_hours),
        ("north_rad", math.radians(north_deg)),
        ("base_intensity", base_intensity),
        ("base_ambient", base_ambient),
        ("night_ambient", night_ambient),
        ("diagram_radius", visualization["radius_m"]),
        ("shadow_center_x", shadow_projection["center"][0]),
        ("shadow_center_y", shadow_projection["center"][1]),
        ("shadow_center_z", shadow_projection["center"][2]),
        ("shadow_distance", shadow_projection["distance"]),
        ("shadow_near", shadow_projection["near"]),
        ("shadow_far", shadow_projection["far"]),
    ):
        _append_script_field(
            calculator,
            q,
            name,
            "SFFloat",
            "initializeOnly",
            _format_float(value),
        )
    for name in (
        "day",
        "hour",
        "b_angle",
        "declination",
        "equation_time",
        "solar_minutes",
        "hour_angle",
        "sun_east",
        "sun_north",
        "sun_up",
        "model_east",
        "model_north",
        "daylight",
    ):
        _append_script_field(
            calculator,
            q,
            name,
            "SFFloat",
            "initializeOnly",
            "0",
        )
    _append_script_field(calculator, q, "direction_changed", "SFVec3f", "outputOnly")
    _append_script_field(calculator, q, "intensity_changed", "SFFloat", "outputOnly")
    _append_script_field(calculator, q, "ambient_changed", "SFFloat", "outputOnly")
    _append_script_field(
        calculator,
        q,
        "shadow_projection_location_changed",
        "SFVec3f",
        "outputOnly",
    )
    _append_script_field(
        calculator,
        q,
        "shadow_up_changed",
        "SFVec3f",
        "outputOnly",
    )
    _append_script_field(
        calculator,
        q,
        "shadow_near_changed",
        "SFFloat",
        "outputOnly",
    )
    _append_script_field(
        calculator,
        q,
        "shadow_far_changed",
        "SFFloat",
        "outputOnly",
    )
    _append_script_field(calculator, q, "sun_position_changed", "SFVec3f", "outputOnly")
    _append_script_field(calculator, q, "ray_translation_changed", "SFVec3f", "outputOnly")
    _append_script_field(calculator, q, "ray_rotation_changed", "SFRotation", "outputOnly")
    _append_script_field(calculator, q, "sun_transparency_changed", "SFFloat", "outputOnly")
    scene.append(calculator)

    compass_script = ET.Element(
        q("Script"),
        {
            "DEF": hud_compass_script_def,
            "url": _x3d_mfstring(_solar_compass_castlescript()),
        },
    )
    _append_script_field(
        compass_script,
        q,
        "camera_orientation",
        "SFRotation",
        "inputOnly",
    )
    _append_script_field(
        compass_script,
        q,
        "north_rad",
        "SFFloat",
        "initializeOnly",
        _format_float(math.radians(north_deg)),
    )
    for name in (
        "forward_east",
        "forward_north",
        "true_east",
        "true_north",
        "heading",
    ):
        _append_script_field(compass_script, q, name, "SFFloat", "initializeOnly", "0")
    _append_script_field(
        compass_script,
        q,
        "camera_direction",
        "SFVec3f",
        "initializeOnly",
        "0 0 -1",
    )
    _append_script_field(
        compass_script,
        q,
        "rotation_changed",
        "SFRotation",
        "outputOnly",
    )
    scene.append(compass_script)

    scene.append(
        ET.Element(
            q("ProximitySensor"),
            {
                "DEF": hud_sensor_def,
                "center": "0 0 0",
                "size": "1000000 1000000 1000000",
                "enabled": "true",
            },
        )
    )
    scene.append(
        _make_solar_hud(
            q,
            hud_def,
            hud_text_def,
            hud_compass_dial_def,
            year,
            initial_day,
            initial_hour,
        )
    )
    scene.append(
        _make_solar_visualization(
            q,
            visualization_switch_def,
            sun_transform_def,
            sun_material_def,
            ray_transform_def,
            ray_material_def,
            visualization,
            days_in_year=days_in_year,
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            timezone_hours=timezone_hours,
            north_deg=north_deg,
        )
    )

    routes = [
        (key_sensor_def, "keyPress", controller_def, "key_press"),
        (controller_def, "state_changed", calculator_def, "state"),
        (calculator_def, "direction_changed", light_def, "direction"),
        (calculator_def, "intensity_changed", light_def, "intensity"),
        (calculator_def, "ambient_changed", light_def, "ambientIntensity"),
        (calculator_def, "sun_position_changed", sun_transform_def, "translation"),
        (calculator_def, "ray_translation_changed", ray_transform_def, "translation"),
        (calculator_def, "ray_rotation_changed", ray_transform_def, "rotation"),
        (calculator_def, "sun_transparency_changed", sun_material_def, "transparency"),
        (calculator_def, "sun_transparency_changed", ray_material_def, "transparency"),
        (controller_def, "label_changed", hud_text_def, "string"),
        (controller_def, "diagram_changed", visualization_switch_def, "whichChoice"),
        (hud_sensor_def, "position_changed", hud_def, "translation"),
        (hud_sensor_def, "orientation_changed", hud_def, "rotation"),
        (
            hud_sensor_def,
            "orientation_changed",
            hud_compass_script_def,
            "camera_orientation",
        ),
        (
            hud_compass_script_def,
            "rotation_changed",
            hud_compass_dial_def,
            "rotation",
        ),
    ]
    if shadow_projection_enabled:
        routes[3:3] = [
            (
                calculator_def,
                "shadow_projection_location_changed",
                light_def,
                "projectionLocation",
            ),
            (
                calculator_def,
                "shadow_up_changed",
                light_def,
                "up",
            ),
            (
                calculator_def,
                "shadow_near_changed",
                light_def,
                "projectionNear",
            ),
            (
                calculator_def,
                "shadow_far_changed",
                light_def,
                "projectionFar",
            ),
        ]
    for from_node, from_field, to_node, to_field in routes:
        scene.append(
            ET.Element(
                q("ROUTE"),
                {
                    "fromNode": from_node,
                    "fromField": from_field,
                    "toNode": to_node,
                    "toField": to_field,
                },
            )
        )
    return True


def _append_script_field(node, q, name: str, field_type: str, access_type: str, value=None):
    attrs = {
        "name": name,
        "type": field_type,
        "accessType": access_type,
    }
    if value is not None:
        attrs["value"] = str(value)
    ET.SubElement(node, q("field"), attrs)


def _x3d_mfstring(value: str) -> str:
    """Encode one X3D MFString item for an XML attribute."""
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _solar_controller_castlescript() -> str:
    return """castlescript:
function initialize(timestamp)
  state_changed := vector(float(day), float(hour));
  diagram_changed := diagram_choice;
  label_changed := array('SOLAR ' + string(year) + '  |  DIA ' + string(day) + '  |  ' + string(hour) + ':00')
function key_press(value, timestamp)
  handled := false;
  when (or(value = 'l', value = 'L'), (hour := hour + 1; when(hour > 23, (hour := 0; day := day + 1)); handled := true));
  when (or(value = 'j', value = 'J'), (hour := hour - 1; when(hour < 0, (hour := 23; day := day - 1)); handled := true));
  when (or(value = 'm', value = 'M'), (day := day + day_step; handled := true));
  when (or(value = 'n', value = 'N'), (day := day - day_step; handled := true));
  when (or(value = 'o', value = 'O'), (day := day + week_step; handled := true));
  when (or(value = 'u', value = 'U'), (day := day - week_step; handled := true));
  when (or(value = 'c', value = 'C'), (diagram_choice := -1 - diagram_choice; diagram_changed := diagram_choice; handled := true));
  when (or(value = 'r', value = 'R'), (day := initial_day; hour := initial_hour; handled := true));
  when (day > days_in_year, day := day - days_in_year);
  when (day < 1, day := day + days_in_year);
  when (handled, (state_changed := vector(float(day), float(hour)); label_changed := array('SOLAR ' + string(year) + '  |  DIA ' + string(day) + '  |  ' + string(hour) + ':00'); writeln('Solar: dia ' + string(day) + ', hora ' + string(hour) + ':00')))
""".strip()


def _solar_calculator_castlescript() -> str:
    return """castlescript:
function state(value, timestamp)
  day := vector_get(value, 0);
  hour := vector_get(value, 1);
  b_angle := (2 * pi / 365) * (day - 81);
  equation_time := 9.87 * sin(2 * b_angle) - 7.53 * cos(b_angle) - 1.5 * sin(b_angle);
  declination := (23.45 * pi / 180) * sin((2 * pi / 365) * (284 + day));
  solar_minutes := hour * 60 + equation_time + 4 * (longitude_deg - 15 * timezone_hours);
  hour_angle := (15 * pi / 180) * (solar_minutes / 60 - 12);
  sun_east := -cos(declination) * sin(hour_angle);
  sun_north := cos(latitude_rad) * sin(declination) - sin(latitude_rad) * cos(declination) * cos(hour_angle);
  sun_up := sin(latitude_rad) * sin(declination) + cos(latitude_rad) * cos(declination) * cos(hour_angle);
  model_east := sun_east * cos(north_rad) + sun_north * sin(north_rad);
  model_north := -sun_east * sin(north_rad) + sun_north * cos(north_rad);
  direction_changed := vector(-model_east, -sun_up, model_north);
  shadow_projection_location_changed := vector(shadow_center_x + model_east * shadow_distance, shadow_center_y + sun_up * shadow_distance, shadow_center_z - model_north * shadow_distance);
  shadow_up_changed := vector(-sun_up * model_east, 1 - sun_up * sun_up, sun_up * model_north);
  when (abs(sun_up) > 0.9999, shadow_up_changed := vector(0, 0, 1));
  shadow_near_changed := shadow_near;
  shadow_far_changed := shadow_far;
  sun_position_changed := vector(model_east * diagram_radius, sun_up * diagram_radius, -model_north * diagram_radius);
  ray_translation_changed := vector(model_east * diagram_radius * 0.5, sun_up * diagram_radius * 0.5, -model_north * diagram_radius * 0.5);
  ray_rotation_changed := orientation_from_direction_up(vector(-model_east, -sun_up, model_north), vector(0, 1, 0));
  sun_transparency_changed := 0;
  when (sun_up <= 0, sun_transparency_changed := 1);
  daylight := max(0, min(1, sun_up * 2));
  intensity_changed := base_intensity * daylight;
  ambient_changed := night_ambient + (base_ambient - night_ambient) * daylight
""".strip()


def _solar_compass_castlescript() -> str:
    return """castlescript:
function camera_orientation(value, timestamp)
  camera_direction := orientation_to_direction(value);
  forward_east := vector_get(camera_direction, 0);
  forward_north := -vector_get(camera_direction, 2);
  true_east := forward_east * cos(north_rad) - forward_north * sin(north_rad);
  true_north := forward_east * sin(north_rad) + forward_north * cos(north_rad);
  heading := 0;
  when (abs(true_north) > 0.0001, heading := arctan(true_east / true_north));
  when (true_north < 0, heading := heading + pi);
  when (and(abs(true_north) <= 0.0001, true_east >= 0), heading := pi / 2);
  when (and(abs(true_north) <= 0.0001, true_east < 0), heading := -pi / 2);
  when (heading > pi, heading := heading - 2 * pi);
  rotation_changed := vector(0, 0, 1, heading)
""".strip()


def _solar_visualization_config(control: Dict[str, object]) -> Dict[str, object]:
    raw = control.get("visualization")
    cfg = raw if isinstance(raw, dict) else {}
    center = cfg.get("center_freecad_mm", (0.0, 0.0, 0.0))
    try:
        if not isinstance(center, (list, tuple)) or len(center) != 3:
            raise ValueError
        center_values = tuple(float(value) for value in center)
        if not all(math.isfinite(value) for value in center_values):
            raise ValueError
    except (TypeError, ValueError):
        center_values = (0.0, 0.0, 0.0)

    radius_m = _clamp(_float_config_value(cfg, "radius_mm", 30000.0) * 0.001, 1.0, 1000.0)
    requested_sun_radius = _float_config_value(cfg, "sun_radius_mm", 700.0) * 0.001
    sun_radius_m = _clamp(requested_sun_radius, radius_m * 0.005, radius_m * 0.08)
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "center_x3d_m": (
            center_values[0] * 0.001,
            center_values[2] * 0.001,
            -center_values[1] * 0.001,
        ),
        "radius_m": radius_m,
        "sun_radius_m": sun_radius_m,
        "sun_color": _normalize_color(cfg.get("sun_color", (1.0, 0.82, 0.08))),
        "diagram_color": _normalize_color(cfg.get("diagram_color", (0.25, 0.45, 0.85))),
    }


def _make_solar_visualization(
    q,
    switch_def: str,
    sun_transform_def: str,
    sun_material_def: str,
    ray_transform_def: str,
    ray_material_def: str,
    visualization: Dict[str, object],
    *,
    days_in_year: int,
    latitude_deg: float,
    longitude_deg: float,
    timezone_hours: float,
    north_deg: float,
):
    """Build a Solar-like world compass, sun sphere and path diagram."""
    radius = float(visualization["radius_m"])
    switch = ET.Element(
        q("Switch"),
        {
            "DEF": switch_def,
            "whichChoice": "0" if bool(visualization.get("enabled", True)) else "-1",
        },
    )
    root = ET.SubElement(
        switch,
        q("Transform"),
        {
            "DEF": SOLAR_CONTROL_DEF_PREFIX + "VisualizationRoot",
            "translation": _format_vec(visualization["center_x3d_m"]),
        },
    )

    diagram_color = visualization["diagram_color"]
    compass_lines = _solar_compass_polylines(radius)
    _append_solar_line_shape(root, q, compass_lines, diagram_color, transparency=0.15)

    path_groups = _solar_path_polylines(
        radius,
        days_in_year=days_in_year,
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
        timezone_hours=timezone_hours,
        north_deg=north_deg,
    )
    _append_solar_line_shape(
        root,
        q,
        path_groups["morning"],
        (0.2, 0.8, 1.0),
        transparency=0.08,
    )
    _append_solar_line_shape(
        root,
        q,
        path_groups["midday"],
        (1.0, 0.75, 0.0),
        transparency=0.02,
    )
    _append_solar_line_shape(
        root,
        q,
        path_groups["afternoon"],
        (1.0, 0.35, 0.0),
        transparency=0.08,
    )
    _append_solar_line_shape(
        root,
        q,
        _solar_hour_polylines(
            radius,
            days_in_year=days_in_year,
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            timezone_hours=timezone_hours,
            north_deg=north_deg,
        ),
        diagram_color,
        transparency=0.48,
    )

    _append_solar_north_arrow(root, q, radius, north_deg)
    _append_solar_cardinal_labels(root, q, radius, north_deg)

    _append_solar_ray(
        root,
        q,
        ray_transform_def,
        ray_material_def,
        radius,
        float(visualization["sun_radius_m"]),
        visualization["sun_color"],
    )

    sun_transform = ET.SubElement(
        root,
        q("Transform"),
        {"DEF": sun_transform_def},
    )
    sun_shape = ET.SubElement(sun_transform, q("Shape"))
    sun_appearance = ET.SubElement(sun_shape, q("Appearance"))
    sun_color = visualization["sun_color"]
    ET.SubElement(
        sun_appearance,
        q("Material"),
        {
            "DEF": sun_material_def,
            "diffuseColor": _format_vec(sun_color),
            "emissiveColor": _format_vec(sun_color),
            "transparency": "0",
        },
    )
    ET.SubElement(
        sun_shape,
        q("Sphere"),
        {"radius": _format_float(float(visualization["sun_radius_m"]))},
    )
    return switch


def _append_solar_ray(
    parent,
    q,
    transform_def: str,
    material_def: str,
    radius: float,
    sun_radius: float,
    color: object,
) -> None:
    """Add Solar's sun-to-diagram ray with an arrow pointing to the center."""
    ray = ET.SubElement(parent, q("Transform"), {"DEF": transform_def})
    normalized_color = _normalize_color(color)

    shaft = ET.SubElement(
        ray,
        q("Transform"),
        {"rotation": "1 0 0 -1.570796327"},
    )
    shaft_shape = ET.SubElement(shaft, q("Shape"))
    shaft_appearance = ET.SubElement(shaft_shape, q("Appearance"))
    ET.SubElement(
        shaft_appearance,
        q("Material"),
        {
            "DEF": material_def,
            "diffuseColor": _format_vec(normalized_color),
            "emissiveColor": _format_vec(normalized_color),
            "transparency": "0",
        },
    )
    ET.SubElement(
        shaft_shape,
        q("Cylinder"),
        {
            "height": _format_float(radius),
            "radius": _format_float(max(radius * 0.0025, sun_radius * 0.06)),
        },
    )

    arrow_height = max(radius * 0.045, sun_radius * 1.4)
    arrow = ET.SubElement(
        ray,
        q("Transform"),
        {
            "translation": _format_vec(
                (0.0, 0.0, -radius * 0.5 + arrow_height * 0.5)
            ),
            "rotation": "1 0 0 -1.570796327",
        },
    )
    arrow_shape = ET.SubElement(arrow, q("Shape"))
    arrow_appearance = ET.SubElement(arrow_shape, q("Appearance"))
    ET.SubElement(arrow_appearance, q("Material"), {"USE": material_def})
    ET.SubElement(
        arrow_shape,
        q("Cone"),
        {
            "height": _format_float(arrow_height),
            "bottomRadius": _format_float(max(radius * 0.018, sun_radius * 0.35)),
        },
    )


def _solar_compass_polylines(radius: float) -> List[List[Tuple[float, float, float]]]:
    lines: List[List[Tuple[float, float, float]]] = []
    elevation = radius * 0.002
    circle_segments = 72
    for ring in range(1, 9):
        ring_radius = radius * ring / 8.0
        lines.append(
            [
                (
                    math.cos(2.0 * math.pi * index / circle_segments) * ring_radius,
                    elevation,
                    math.sin(2.0 * math.pi * index / circle_segments) * ring_radius,
                )
                for index in range(circle_segments + 1)
            ]
        )
    for degrees in range(0, 360, 15):
        angle = math.radians(degrees)
        inner = 0.0 if degrees % 90 == 0 else radius * 0.88
        lines.append(
            [
                (math.cos(angle) * inner, elevation, math.sin(angle) * inner),
                (math.cos(angle) * radius, elevation, math.sin(angle) * radius),
            ]
        )
    return lines


def _solar_path_polylines(
    radius: float,
    *,
    days_in_year: int,
    latitude_deg: float,
    longitude_deg: float,
    timezone_hours: float,
    north_deg: float,
) -> Dict[str, List[List[Tuple[float, float, float]]]]:
    groups: Dict[str, List[List[Tuple[float, float, float]]]] = {
        "morning": [],
        "midday": [],
        "afternoon": [],
    }
    representative_days = [
        max(1, min(days_in_year, int(round((month - 0.32) * days_in_year / 12.0))))
        for month in range(1, 13)
    ]
    for day in representative_days:
        active_band = ""
        active_line: List[Tuple[float, float, float]] = []
        for half_hour in range(49):
            hour = half_hour * 0.5
            point = _solar_diagram_point(
                radius,
                day,
                hour,
                latitude_deg,
                longitude_deg,
                timezone_hours,
                north_deg,
            )
            band = "morning" if hour < 10.0 else "midday" if hour <= 14.0 else "afternoon"
            if point is None:
                if len(active_line) > 1 and active_band:
                    groups[active_band].append(active_line)
                active_band = ""
                active_line = []
                continue
            if band != active_band:
                previous = active_line[-1] if active_line else None
                if len(active_line) > 1 and active_band:
                    groups[active_band].append(active_line)
                active_line = [previous, point] if previous is not None else [point]
                active_band = band
            else:
                active_line.append(point)
        if len(active_line) > 1 and active_band:
            groups[active_band].append(active_line)
    return groups


def _solar_hour_polylines(
    radius: float,
    *,
    days_in_year: int,
    latitude_deg: float,
    longitude_deg: float,
    timezone_hours: float,
    north_deg: float,
) -> List[List[Tuple[float, float, float]]]:
    lines: List[List[Tuple[float, float, float]]] = []
    day_samples = list(range(1, days_in_year + 1, 15))
    if day_samples[-1] != days_in_year:
        day_samples.append(days_in_year)
    for hour in range(6, 19, 2):
        active: List[Tuple[float, float, float]] = []
        for day in day_samples:
            point = _solar_diagram_point(
                radius,
                day,
                float(hour),
                latitude_deg,
                longitude_deg,
                timezone_hours,
                north_deg,
            )
            if point is None:
                if len(active) > 1:
                    lines.append(active)
                active = []
            else:
                active.append(point)
        if len(active) > 1:
            lines.append(active)
    return lines


def _solar_diagram_point(
    radius: float,
    day: float,
    hour: float,
    latitude_deg: float,
    longitude_deg: float,
    timezone_hours: float,
    north_deg: float,
) -> Optional[Tuple[float, float, float]]:
    east, north, up = solar_core.approximate_sun_position(
        day,
        hour,
        latitude_deg,
        longitude_deg,
        timezone_hours,
        north_deg,
    )
    if up <= 0.0:
        return None
    return (east * radius, up * radius, -north * radius)


def _append_solar_line_shape(
    parent,
    q,
    polylines: List[List[Tuple[float, float, float]]],
    color: object,
    *,
    transparency: float,
) -> None:
    valid_lines = [line for line in polylines if len(line) > 1]
    if not valid_lines:
        return
    points: List[Tuple[float, float, float]] = []
    indices: List[str] = []
    for line in valid_lines:
        start = len(points)
        points.extend(line)
        indices.extend(str(start + offset) for offset in range(len(line)))
        indices.append("-1")
    shape = ET.SubElement(parent, q("Shape"))
    appearance = ET.SubElement(shape, q("Appearance"))
    normalized_color = _normalize_color(color)
    ET.SubElement(
        appearance,
        q("Material"),
        {
            "diffuseColor": _format_vec(normalized_color),
            "emissiveColor": _format_vec(normalized_color),
            "transparency": _format_float(_clamp(transparency, 0.0, 1.0)),
        },
    )
    geometry = ET.SubElement(
        shape,
        q("IndexedLineSet"),
        {"coordIndex": " ".join(indices)},
    )
    ET.SubElement(
        geometry,
        q("Coordinate"),
        {"point": ", ".join(_format_vec(point) for point in points)},
    )


def _append_solar_north_arrow(parent, q, radius: float, north_deg: float) -> None:
    angle = math.radians(north_deg)
    north = (math.sin(angle), -math.cos(angle))
    east = (math.cos(angle), math.sin(angle))
    tip = (north[0] * radius * 0.97, radius * 0.012, north[1] * radius * 0.97)
    base_center = (north[0] * radius * 0.73, radius * 0.012, north[1] * radius * 0.73)
    width = radius * 0.065
    left = (base_center[0] - east[0] * width, base_center[1], base_center[2] - east[1] * width)
    right = (base_center[0] + east[0] * width, base_center[1], base_center[2] + east[1] * width)
    shape = ET.SubElement(parent, q("Shape"))
    appearance = ET.SubElement(shape, q("Appearance"))
    ET.SubElement(
        appearance,
        q("Material"),
        {"diffuseColor": "0.9 0.08 0.04", "emissiveColor": "0.35 0.02 0.01"},
    )
    face = ET.SubElement(
        shape,
        q("IndexedFaceSet"),
        {"coordIndex": "0 1 2 -1", "solid": "false"},
    )
    ET.SubElement(
        face,
        q("Coordinate"),
        {"point": ", ".join(_format_vec(point) for point in (tip, left, right))},
    )


def _append_solar_cardinal_labels(parent, q, radius: float, north_deg: float) -> None:
    angle = math.radians(north_deg)
    north = (math.sin(angle), -math.cos(angle))
    east = (math.cos(angle), math.sin(angle))
    directions = (
        ("N", north, (1.0, 0.22, 0.12)),
        ("E", east, (0.85, 0.9, 1.0)),
        ("S", (-north[0], -north[1]), (0.85, 0.9, 1.0)),
        ("O/W", (-east[0], -east[1]), (0.85, 0.9, 1.0)),
    )
    for label, direction, color in directions:
        transform = ET.SubElement(
            parent,
            q("Transform"),
            {
                "translation": _format_vec(
                    (
                        direction[0] * radius * 1.10,
                        radius * 0.04,
                        direction[1] * radius * 1.10,
                    )
                )
            },
        )
        billboard = ET.SubElement(transform, q("Billboard"), {"axisOfRotation": "0 1 0"})
        shape = ET.SubElement(billboard, q("Shape"))
        appearance = ET.SubElement(shape, q("Appearance"))
        ET.SubElement(
            appearance,
            q("Material"),
            {"diffuseColor": _format_vec(color), "emissiveColor": _format_vec(color)},
        )
        text = ET.SubElement(shape, q("Text"), {"string": _x3d_mfstring(label)})
        ET.SubElement(
            text,
            q("FontStyle"),
            {
                "family": '"SANS"',
                "justify": '"MIDDLE" "MIDDLE"',
                "size": _format_float(radius * 0.045),
                "style": "BOLD",
            },
        )


def _make_solar_hud(
    q,
    hud_def: str,
    text_def: str,
    compass_dial_def: str,
    year: int,
    day: int,
    hour: int,
):
    """Create a near-camera HUD that remains in front of walk-mode walls."""
    collision = ET.Element(
        q("Collision"),
        {"DEF": SOLAR_CONTROL_DEF_PREFIX + "HUDCollision", "enabled": "false"},
    )
    hud = ET.SubElement(collision, q("Transform"), {"DEF": hud_def})
    panel = ET.SubElement(
        hud,
        q("Transform"),
        {
            "DEF": SOLAR_CONTROL_DEF_PREFIX + "HUDPanel",
            "translation": "-0.138 0.086 -0.18",
            "scale": "0.04125 0.04125 0.04125",
        },
    )
    backdrop = ET.SubElement(panel, q("Transform"), {"translation": "1.025 -0.08 -0.03"})
    backdrop_shape = ET.SubElement(backdrop, q("Shape"))
    backdrop_appearance = ET.SubElement(backdrop_shape, q("Appearance"))
    _append_hud_unlit_material(
        backdrop_appearance,
        q,
        (0.012, 0.025, 0.055),
        transparency=0.06,
    )
    ET.SubElement(backdrop_shape, q("Box"), {"size": "2.05 0.62 0.025"})

    _append_hud_line_shape(
        panel,
        q,
        [
            [(0.0, 0.23, 0.01), (2.05, 0.23, 0.01), (2.05, -0.39, 0.01),
             (0.0, -0.39, 0.01), (0.0, 0.23, 0.01)],
            [(0.04, 0.015, 0.012), (2.01, 0.015, 0.012)],
        ],
        (0.08, 0.72, 1.0),
        line_width=2.0,
    )

    indicator = ET.SubElement(
        panel,
        q("Transform"),
        {"translation": "0.09 0.13 0.035"},
    )
    indicator_shape = ET.SubElement(indicator, q("Shape"))
    indicator_appearance = ET.SubElement(indicator_shape, q("Appearance"))
    _append_hud_unlit_material(indicator_appearance, q, (1.0, 0.68, 0.08))
    ET.SubElement(indicator_shape, q("Sphere"), {"radius": "0.042"})

    _append_hud_text(
        panel,
        q,
        f"SOLAR {year}  |  DIA {day}  |  {hour}:00",
        translation=(0.17, 0.13, 0.04),
        color=(1.0, 1.0, 1.0),
        size=0.115,
        def_name=text_def,
        style="BOLD",
    )
    _append_hud_text(
        panel,
        q,
        ("J/L  HORA     N/M  DIA     U/O  SEMANA", "C  DIAGRAMA        R  REINICIAR"),
        translation=(0.08, -0.17, 0.04),
        color=(0.58, 0.84, 1.0),
        size=0.082,
        def_name=SOLAR_CONTROL_DEF_PREFIX + "HUDHelp",
        spacing=1.35,
    )
    _append_hud_compass(hud, q, compass_dial_def)
    return collision


def _append_hud_unlit_material(
    appearance,
    q,
    color: object,
    *,
    transparency: float = 0.0,
    def_name: str = "",
    use_name: str = "",
):
    if use_name:
        return ET.SubElement(appearance, q("UnlitMaterial"), {"USE": use_name})
    attrs = {
        "emissiveColor": _format_vec(_normalize_color(color)),
        "transparency": _format_float(_clamp(transparency, 0.0, 1.0)),
    }
    if def_name:
        attrs["DEF"] = def_name
    return ET.SubElement(appearance, q("UnlitMaterial"), attrs)


def _append_hud_text(
    parent,
    q,
    strings,
    *,
    translation: Tuple[float, float, float],
    color: object,
    size: float,
    def_name: str = "",
    spacing: float = 1.0,
    style: str = "PLAIN",
    justify: str = "BEGIN",
) -> None:
    transform = ET.SubElement(
        parent,
        q("Transform"),
        {"translation": _format_vec(translation)},
    )
    shape = ET.SubElement(transform, q("Shape"))
    appearance = ET.SubElement(shape, q("Appearance"))
    _append_hud_unlit_material(appearance, q, color)
    values = (strings,) if isinstance(strings, str) else tuple(strings)
    attrs = {
        "string": " ".join(_x3d_mfstring(value) for value in values),
        "solid": "false",
    }
    if def_name:
        attrs["DEF"] = def_name
    text = ET.SubElement(shape, q("Text"), attrs)
    ET.SubElement(
        text,
        q("FontStyle"),
        {
            "family": '"SANS"',
            "justify": f'"{justify}" "MIDDLE"',
            "size": _format_float(size),
            "spacing": _format_float(spacing),
            "style": style,
        },
    )


def _append_hud_line_shape(
    parent,
    q,
    polylines: List[List[Tuple[float, float, float]]],
    color: object,
    *,
    line_width: float = 1.0,
) -> None:
    valid_lines = [line for line in polylines if len(line) > 1]
    if not valid_lines:
        return
    points: List[Tuple[float, float, float]] = []
    indices: List[str] = []
    for line in valid_lines:
        start = len(points)
        points.extend(line)
        indices.extend(str(start + offset) for offset in range(len(line)))
        indices.append("-1")
    shape = ET.SubElement(parent, q("Shape"))
    appearance = ET.SubElement(shape, q("Appearance"))
    _append_hud_unlit_material(appearance, q, color)
    ET.SubElement(
        appearance,
        q("LineProperties"),
        {
            "applied": "true",
            "linewidthScaleFactor": _format_float(line_width),
        },
    )
    geometry = ET.SubElement(
        shape,
        q("IndexedLineSet"),
        {"coordIndex": " ".join(indices)},
    )
    ET.SubElement(
        geometry,
        q("Coordinate"),
        {"point": ", ".join(_format_vec(point) for point in points)},
    )


def _append_hud_triangle(parent, q, points, color: object) -> None:
    shape = ET.SubElement(parent, q("Shape"))
    appearance = ET.SubElement(shape, q("Appearance"))
    _append_hud_unlit_material(appearance, q, color)
    face = ET.SubElement(
        shape,
        q("IndexedFaceSet"),
        {"coordIndex": "0 1 2 -1", "solid": "false"},
    )
    ET.SubElement(
        face,
        q("Coordinate"),
        {"point": ", ".join(_format_vec(point) for point in points)},
    )


def _append_hud_compass(parent, q, dial_def: str) -> None:
    anchor = ET.SubElement(
        parent,
        q("Transform"),
        {
            "DEF": SOLAR_CONTROL_DEF_PREFIX + "HUDCompass",
            "translation": "0.125 0.083 -0.178",
            "scale": "0.010875 0.010875 0.010875",
        },
    )
    backdrop = ET.SubElement(anchor, q("Transform"), {"translation": "0 0 -0.04"})
    backdrop_shape = ET.SubElement(backdrop, q("Shape"))
    backdrop_appearance = ET.SubElement(backdrop_shape, q("Appearance"))
    _append_hud_unlit_material(
        backdrop_appearance,
        q,
        (0.012, 0.025, 0.055),
        transparency=0.04,
    )
    ET.SubElement(backdrop_shape, q("Box"), {"size": "2.30 2.30 0.03"})

    outer_ring = [
        (
            math.cos(2.0 * math.pi * index / 64.0) * 1.02,
            math.sin(2.0 * math.pi * index / 64.0) * 1.02,
            0.01,
        )
        for index in range(65)
    ]
    _append_hud_line_shape(
        anchor,
        q,
        [outer_ring],
        (0.08, 0.72, 1.0),
        line_width=2.4,
    )

    dial = ET.SubElement(anchor, q("Transform"), {"DEF": dial_def})
    ring_points = [
        (
            math.cos(2.0 * math.pi * index / 48.0) * 0.86,
            math.sin(2.0 * math.pi * index / 48.0) * 0.86,
            0.015,
        )
        for index in range(49)
    ]
    compass_lines = [
        ring_points,
        [(-0.58, 0.0, 0.015), (0.58, 0.0, 0.015)],
        [(0.0, -0.58, 0.015), (0.0, 0.58, 0.015)],
    ]
    for index in range(24):
        angle = 2.0 * math.pi * index / 24.0
        inner = 0.70 if index % 6 == 0 else 0.78
        compass_lines.append(
            [
                (math.cos(angle) * inner, math.sin(angle) * inner, 0.015),
                (math.cos(angle) * 0.94, math.sin(angle) * 0.94, 0.015),
            ]
        )
    _append_hud_line_shape(
        dial,
        q,
        compass_lines,
        (0.58, 0.84, 1.0),
        line_width=1.8,
    )

    _append_hud_triangle(
        dial,
        q,
        ((0.0, 0.72, 0.04), (-0.115, -0.02, 0.04), (0.115, -0.02, 0.04)),
        (1.0, 0.12, 0.06),
    )
    _append_hud_triangle(
        dial,
        q,
        ((0.0, -0.62, 0.038), (-0.08, 0.02, 0.038), (0.08, 0.02, 0.038)),
        (0.78, 0.86, 0.94),
    )

    for label, x_value, y_value, color in (
        ("N", 0.0, 0.61, (1.0, 0.2, 0.08)),
        ("E", 0.61, 0.0, (1.0, 1.0, 1.0)),
        ("S", 0.0, -0.61, (1.0, 1.0, 1.0)),
        ("O", -0.61, 0.0, (1.0, 1.0, 1.0)),
    ):
        _append_hud_text(
            dial,
            q,
            label,
            translation=(x_value, y_value, 0.06),
            color=color,
            size=0.24,
            spacing=1.0,
            style="BOLD",
            justify="MIDDLE",
        )

    hub = ET.SubElement(
        dial,
        q("Transform"),
        {"translation": "0 0 0.07", "scale": "1 1 0.25"},
    )
    hub_shape = ET.SubElement(hub, q("Shape"))
    hub_appearance = ET.SubElement(hub_shape, q("Appearance"))
    _append_hud_unlit_material(hub_appearance, q, (1.0, 0.72, 0.08))
    ET.SubElement(hub_shape, q("Sphere"), {"radius": "0.09"})

    _append_hud_triangle(
        anchor,
        q,
        ((0.0, 1.13, 0.08), (-0.12, 0.96, 0.08), (0.12, 0.96, 0.08)),
        (1.0, 0.72, 0.08),
    )


def _make_directional_light(q, cfg: Dict[str, object]):
    direction = _direction_from_config(cfg)
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
        # Keep the validation baseline on the existing X3D/Castle shadow-map
        # path. Do not mix shadow-volume extensions into this geometry test.
        attrs["shadows"] = "true"
    return ET.Element(q("DirectionalLight"), attrs)


def _direction_from_config(cfg: Dict[str, object]) -> Tuple[float, float, float]:
    """Resolve a neutral FreeCAD direction, falling back to manual yaw/pitch."""
    direct = cfg.get("direction_freecad")
    if isinstance(direct, (list, tuple)) and len(direct) == 3:
        try:
            vector = tuple(float(component) for component in direct)
            length = math.sqrt(sum(component * component for component in vector))
            if length > 1e-9 and all(math.isfinite(component) for component in vector):
                normalized = tuple(component / length for component in vector)
                return _rotate_freecad_vector_to_x3d(normalized)
        except (TypeError, ValueError):
            pass
    return _direction_from_yaw_pitch(
        _float_config_value(cfg, "yaw", 0.0),
        _float_config_value(cfg, "pitch", -45.0),
    )


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


def _remove_interactive_solar_nodes(node) -> None:
    """Remove a previously generated controller and all of its ROUTEs."""
    for child in list(node):
        attrs = getattr(child, "attrib", {})
        def_name = str(attrs.get("DEF", "") or "")
        from_node = str(attrs.get("fromNode", "") or "")
        to_node = str(attrs.get("toNode", "") or "")
        if (
            def_name.startswith(SOLAR_CONTROL_DEF_PREFIX)
            or from_node.startswith(SOLAR_CONTROL_DEF_PREFIX)
            or to_node.startswith(SOLAR_CONTROL_DEF_PREFIX)
        ):
            node.remove(child)
            continue
        _remove_interactive_solar_nodes(child)


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
    """Apply the final exportability gate, including explicit exclusion metadata."""
    exportable: List[object] = []
    skipped: List[Tuple[str, str, str]] = []
    for obj in objects:
        label = getattr(obj, "Label", "") or getattr(obj, "Name", "Unknown")
        type_id = getattr(obj, "TypeId", "UnknownType")
        if _object_export_override(obj) is False:
            reason = "BIM Space (semantic exclusion)" if _is_bim_space(obj) else "GameExportExclude=True"
            skipped.append((label, type_id, reason))
            continue
        ok, reason = _is_exportable_object(obj)
        if ok:
            exportable.append(obj)
            continue
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


def _is_bim_space(obj) -> bool:
    """Return True when an object or linked target represents an IFC/BIM Space."""
    try:
        linked = getattr(obj, "LinkedObject", None)
    except Exception:
        linked = None
    for candidate in (obj, linked):
        if candidate is None:
            continue
        try:
            if str(getattr(candidate, "IfcType", "") or "").strip().lower() == "space":
                return True
        except Exception:
            pass
        try:
            proxy = getattr(candidate, "Proxy", None)
            if str(getattr(proxy, "Type", "") or "").strip().lower() == "space":
                return True
        except Exception:
            pass
        try:
            if str(getattr(candidate, "TypeId", "") or "").strip().lower() == "arch::space":
                return True
        except Exception:
            pass
    return False


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
    if _is_bim_space(obj):
        return False
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
