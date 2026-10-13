"""Generate four reproducible Solar shadow validation scenes.

Run with FreeCADCmd, not regular Python.  The output folder receives one FCStd
and one X3D per preset plus ``solar_shadow_validation_report.json``.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import FreeCAD
import Part


try:
    DEV_REPO_PARENT = Path(__file__).resolve().parents[1]
except NameError:
    DEV_REPO_PARENT = Path.cwd()
if str(DEV_REPO_PARENT) in sys.path:
    sys.path.remove(str(DEV_REPO_PARENT))
sys.path.insert(0, str(DEV_REPO_PARENT))

from freecad.GameEngineExportWB.adapters import solar_adapter
from freecad.GameEngineExportWB.core import exporter_x3d
from freecad.GameEngineExportWB.core import solar_shadow_validation as reference


POLE_HEIGHT_MM = 3000.0
PLANE_SIZE_MM = 20000.0
SUN_VECTOR_DISTANCE_MM = 30000.0
TOLERANCE_MM = 1e-6


def _arguments() -> argparse.Namespace:
    default_name = "GameEngineExportWB_SolarShadowValidation_" + datetime.datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            os.environ.get(
                "GAMEEXPORT_SOLAR_SHADOW_OUTPUT",
                str(Path(tempfile.gettempdir()) / default_name),
            )
        ),
        help="Folder for generated FCStd, X3D and JSON files",
    )
    parser.add_argument(
        "--castle-converter",
        type=Path,
        default=(
            Path(os.environ["CASTLE_MODEL_CONVERTER"])
            if os.environ.get("CASTLE_MODEL_CONVERTER")
            else None
        ),
        help="Optional castle-model-converter executable used with --validate",
    )
    args, _unknown = parser.parse_known_args()
    return args


def _set_color(obj: object, color: tuple[float, float, float], transparency: int = 0) -> None:
    view = getattr(obj, "ViewObject", None)
    if view is None:
        return
    view.ShapeColor = color
    view.LineColor = color
    view.Transparency = transparency


def _add_shape(document: object, name: str, label: str, shape: object, color: tuple[float, float, float], transparency: int = 0) -> object:
    obj = document.addObject("Part::Feature", name)
    obj.Label = label
    obj.Shape = shape
    _set_color(obj, color, transparency)
    return obj


def _axis_shape(direction: FreeCAD.Vector, length: float = 3200.0) -> object:
    start = FreeCAD.Vector(0.0, 0.0, 12.0)
    shaft_length = length - 220.0
    shaft = Part.makeCylinder(22.0, shaft_length, start, direction)
    head_start = FreeCAD.Vector(
        start.x + direction.x * shaft_length,
        start.y + direction.y * shaft_length,
        start.z + direction.z * shaft_length,
    )
    head = Part.makeCone(90.0, 0.0, 220.0, head_start, direction)
    return Part.makeCompound([shaft, head])


def _create_sun_contract(document: object, preset: reference.ShadowPreset) -> object:
    toward_sun = reference.observer_to_sun_vector(
        preset.altitude_deg,
        preset.azimuth_deg,
        preset.north_deg,
    )
    sun = document.addObject("App::FeaturePython", "SunProperties")
    sun.Label = "Solar input - " + preset.label
    sun.addProperty("App::PropertyVector", "SunLightPosition", "Solar Validation")
    sun.addProperty("App::PropertyFloat", "Altitude", "Solar Validation")
    sun.addProperty("App::PropertyFloat", "Azimuth", "Solar Validation")
    sun.addProperty("App::PropertyAngle", "North", "Solar Validation")
    sun.addProperty("App::PropertyColor", "SunLightColor", "Solar Validation")
    sun.SunLightPosition = FreeCAD.Vector(
        toward_sun[0] * SUN_VECTOR_DISTANCE_MM,
        toward_sun[1] * SUN_VECTOR_DISTANCE_MM,
        toward_sun[2] * SUN_VECTOR_DISTANCE_MM,
    )
    sun.Altitude = preset.altitude_deg
    sun.Azimuth = preset.azimuth_deg
    sun.North = preset.north_deg
    sun.SunLightColor = (1.0, 0.86, 0.45)
    return sun


def _build_geometry(document: object, endpoint: tuple[float, float, float]) -> list[object]:
    objects = []
    half = PLANE_SIZE_MM * 0.5
    plane = Part.makeBox(
        PLANE_SIZE_MM,
        PLANE_SIZE_MM,
        80.0,
        FreeCAD.Vector(-half, -half, -80.0),
    )
    objects.append(
        _add_shape(document, "GroundPlane", "Plano horizontal Z=0", plane, (0.72, 0.72, 0.72))
    )

    axes = (
        ("AxisNorth", "Norte +Y", FreeCAD.Vector(0, 1, 0), (0.90, 0.12, 0.12)),
        ("AxisEast", "Este +X", FreeCAD.Vector(1, 0, 0), (0.12, 0.70, 0.18)),
        ("AxisSouth", "Sur -Y", FreeCAD.Vector(0, -1, 0), (0.15, 0.35, 0.95)),
        ("AxisWest", "Oeste -X", FreeCAD.Vector(-1, 0, 0), (0.94, 0.94, 0.94)),
    )
    for name, label, direction, color in axes:
        objects.append(_add_shape(document, name, label, _axis_shape(direction), color))

    pole = Part.makeCylinder(100.0, POLE_HEIGHT_MM, FreeCAD.Vector(0, 0, 0))
    objects.append(_add_shape(document, "VerticalPole", "Poste vertical 3000 mm", pole, (0.18, 0.18, 0.20)))

    shadow_vector = FreeCAD.Vector(endpoint[0], endpoint[1], 0.0)
    shadow_length = shadow_vector.Length
    shadow_direction = FreeCAD.Vector(
        shadow_vector.x / shadow_length,
        shadow_vector.y / shadow_length,
        0.0,
    )
    # Leave gaps so Castle's rendered shadow remains visible underneath the
    # independent reference instead of being completely covered by it.
    dash_count = 10
    dash_length = shadow_length / (dash_count * 2.0)
    shadow_parts = []
    for index in range(dash_count):
        offset = index * dash_length * 2.0
        dash_start = FreeCAD.Vector(
            shadow_direction.x * offset,
            shadow_direction.y * offset,
            28.0,
        )
        shadow_parts.append(
            Part.makeCylinder(28.0, dash_length, dash_start, shadow_direction)
        )
    marker = Part.makeSphere(75.0, FreeCAD.Vector(endpoint[0], endpoint[1], 28.0))
    shadow_parts.append(marker)
    objects.append(
        _add_shape(
            document,
            "TheoreticalShadow",
            "Linea teorica independiente de sombra",
            Part.makeCompound(shadow_parts),
            (0.05, 0.90, 0.95),
        )
    )
    return objects


def _add_validation_info(document: object, preset: reference.ShadowPreset, endpoint: tuple[float, float, float]) -> None:
    info = document.addObject("App::FeaturePython", "ValidationInfo")
    info.Label = "Resultado teorico - " + preset.key
    for name, value in (
        ("Preset", preset.key),
        ("ExpectedShadowAxis", preset.expected_shadow_axis),
        ("Convention", "FreeCAD: +X Este, +Y Norte, +Z arriba; azimut horario desde Norte configurado"),
    ):
        info.addProperty("App::PropertyString", name, "Solar Validation")
        setattr(info, name, value)
    for name, value in (
        ("AltitudeDeg", preset.altitude_deg),
        ("AzimuthDeg", preset.azimuth_deg),
        ("NorthDeg", preset.north_deg),
        ("PoleHeightMM", POLE_HEIGHT_MM),
        ("ExpectedShadowLengthMM", reference.horizontal_length(endpoint)),
    ):
        info.addProperty("App::PropertyFloat", name, "Solar Validation")
        setattr(info, name, value)
    info.addProperty("App::PropertyVector", "ExpectedShadowEndpoint", "Solar Validation")
    info.ExpectedShadowEndpoint = FreeCAD.Vector(*endpoint)


def _x3d_light_summary(path: Path) -> dict[str, object]:
    root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    node = next(
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "DirectionalLight"
        and element.attrib.get("DEF") == "GameExport_SunLight"
    )
    return {
        "direction": [float(value) for value in node.attrib["direction"].split()],
        "shadows": node.attrib.get("shadows") == "true",
        "shadow_volumes_present": (
            "shadowVolumes" in node.attrib or "shadowVolumesMain" in node.attrib
        ),
        "attributes": dict(node.attrib),
    }


def _castle_validate(converter: Path | None, x3d_path: Path) -> dict[str, object]:
    if converter is None:
        return {"status": "not_requested"}
    completed = subprocess.run(
        [str(converter), "--validate", str(x3d_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    return {
        "status": "pass" if completed.returncode == 0 else "fail",
        "return_code": completed.returncode,
        "output": output,
    }


def _add_obj_materials(obj_path: Path) -> None:
    """Assign stable diagnostic colors to FreeCAD Mesh.export OBJ groups."""
    materials = {
        "Plano horizontal Z=0": ("ground", (0.72, 0.72, 0.72)),
        "Norte +Y": ("north_red", (0.90, 0.12, 0.12)),
        "Este +X": ("east_green", (0.12, 0.70, 0.18)),
        "Sur -Y": ("south_blue", (0.15, 0.35, 0.95)),
        "Oeste -X": ("west_white", (0.94, 0.94, 0.94)),
        "Poste vertical 3000 mm": ("pole", (0.18, 0.18, 0.20)),
        "Linea teorica independiente de sombra": ("theoretical_cyan", (0.05, 0.90, 0.95)),
    }
    source_lines = obj_path.read_text(encoding="utf-8", errors="replace").splitlines()
    mtl_path = obj_path.with_suffix(".mtl")
    output_lines = ["mtllib " + mtl_path.name]
    used = set()
    for line in source_lines:
        output_lines.append(line)
        if not line.startswith("g "):
            continue
        group_name = line[2:].strip()
        material = materials.get(group_name)
        if material is None:
            continue
        output_lines.append("usemtl " + material[0])
        used.add(group_name)
    obj_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")

    mtl_lines = []
    for group_name, (material_name, color) in materials.items():
        if group_name not in used:
            continue
        mtl_lines.extend(
            [
                "newmtl " + material_name,
                "Ka 0.15 0.15 0.15",
                "Kd {:.6f} {:.6f} {:.6f}".format(*color),
                "Ks 0.08 0.08 0.08",
                "Ns 12.0",
                "d 1.0",
                "illum 2",
                "",
            ]
        )
    mtl_path.write_text("\n".join(mtl_lines), encoding="utf-8")


def _export_x3d(
    objects: list[object],
    x3d_path: Path,
    gamestart_meta: dict[str, object],
    lighting_cfg: dict[str, object],
    material_cfg: dict[str, object],
    converter: Path | None,
) -> str:
    """Use the normal exporter in GUI FreeCAD, with a headless test fallback.

    FreeCADCmd cannot load ImportGui in FreeCAD 1.1.3.  For repeatable CI-style
    execution it tessellates the same document to OBJ, lets Castle convert that
    geometry to X3D, and then runs the normal GameEngineExportWB decorator.  The
    fallback changes neither the Solar adapter nor the emitted light settings.
    """
    try:
        exporter_x3d.export_to_x3d(
            objects,
            x3d_path,
            gamestart_meta=gamestart_meta,
            lighting_cfg=lighting_cfg,
            material_cfg=material_cfg,
        )
        return "FreeCADGui.export"
    except ImportError as exc:
        if "Gui module" not in str(exc):
            raise
        if converter is None:
            raise RuntimeError(
                "FreeCADCmd needs --castle-converter (or CASTLE_MODEL_CONVERTER) "
                "for the headless OBJ-to-X3D fallback"
            ) from exc
        Mesh = __import__("Mesh")
        obj_path = x3d_path.with_suffix(".obj")
        Mesh.export(objects, str(obj_path))
        _add_obj_materials(obj_path)
        converted = subprocess.run(
            [str(converter), str(obj_path), str(x3d_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if converted.returncode != 0:
            details = "\n".join(
                part.strip()
                for part in (converted.stdout, converted.stderr)
                if part.strip()
            )
            raise RuntimeError("Castle OBJ-to-X3D conversion failed: " + details)
        exporter_x3d.decorate_x3d(
            x3d_path,
            gamestart_meta=gamestart_meta,
            lighting_cfg=lighting_cfg,
            material_cfg=material_cfg,
        )
        return "Mesh.export + castle-model-converter + decorate_x3d"


def _generate_case(output_dir: Path, preset: reference.ShadowPreset, converter: Path | None) -> dict[str, object]:
    endpoint = reference.theoretical_shadow_endpoint(
        POLE_HEIGHT_MM,
        preset.altitude_deg,
        preset.azimuth_deg,
        preset.north_deg,
    )
    document = FreeCAD.newDocument("SolarShadow_" + preset.key)
    try:
        _create_sun_contract(document, preset)
        objects = _build_geometry(document, endpoint)
        _add_validation_info(document, preset, endpoint)
        document.recompute()

        discovery = solar_adapter.discover_sun_environment(
            document,
            availability_probe=lambda: True,
        )
        if discovery.environment is None:
            raise RuntimeError("Solar adapter rejected preset: " + discovery.reason)
        ray_endpoint = reference.ray_shadow_endpoint(
            POLE_HEIGHT_MM,
            discovery.environment.direction_freecad,
        )
        error_mm = math.dist(endpoint, ray_endpoint)
        if error_mm > TOLERANCE_MM:
            raise AssertionError(
                f"Solar ray misses theoretical shadow by {error_mm:.9f} mm"
            )

        fcstd_path = output_dir / (preset.key + ".FCStd")
        x3d_path = output_dir / (preset.key + ".x3d")
        document.saveAs(str(fcstd_path))

        global_light = discovery.environment.to_directional_light_config(include_color=True)
        global_light.update(
            {
                "enabled": True,
                "intensity": 1.0,
                "ambient_intensity": 0.12,
                "shadows": True,
            }
        )
        lighting_cfg = {
            "global": global_light,
            "navigation": {
                "walk_only": False,
                "ground_collision": False,
                "speed": 2.0,
            },
        }
        material_cfg = {
            "improve_interior_lighting": True,
            "interior_lighting_mode": "Architectural",
        }
        gamestart_meta = {
            "position_mm": (0.0, -14000.0, 8000.0),
            "orientation": (0.0, 0.0, 1.0, 0.0),
            "yaw_deg": 0.0,
            "pitch_deg": -45.0,
            "roll_deg": 0.0,
            "height_offset_mm": 1600.0,
            "description": "Solar shadow validation overview",
            "fov_rad": math.radians(55.0),
        }
        export_backend = _export_x3d(
            objects,
            x3d_path,
            gamestart_meta,
            lighting_cfg,
            material_cfg,
            converter,
        )
        light = _x3d_light_summary(x3d_path)
        if not light["shadows"]:
            raise AssertionError("Exported DirectionalLight did not retain shadows=true")
        if light["shadow_volumes_present"]:
            raise AssertionError(
                "Baseline validation must not mix shadow-volume extensions with shadows=true"
            )
        castle = _castle_validate(converter, x3d_path)
        if castle["status"] == "fail":
            raise AssertionError("Castle validation failed: " + str(castle["output"]))

        return {
            "preset": preset.key,
            "label": preset.label,
            "inputs": {
                "altitude_deg": preset.altitude_deg,
                "azimuth_deg": preset.azimuth_deg,
                "north_deg": preset.north_deg,
                "pole_height_mm": POLE_HEIGHT_MM,
            },
            "expected_shadow_axis": preset.expected_shadow_axis,
            "theoretical_endpoint_mm": list(endpoint),
            "theoretical_length_mm": reference.horizontal_length(endpoint),
            "adapter_light_ray_freecad": list(discovery.environment.direction_freecad),
            "ray_intersection_endpoint_mm": list(ray_endpoint),
            "endpoint_error_mm": error_mm,
            "x3d_directional_light": light,
            "castle_validation": castle,
            "export_backend": export_backend,
            "files": {"fcstd": fcstd_path.name, "x3d": x3d_path.name},
            "status": "pass",
        }
    finally:
        FreeCAD.closeDocument(document.Name)


def main() -> int:
    args = _arguments()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.castle_converter is not None and not args.castle_converter.is_file():
        raise FileNotFoundError("Castle converter not found: " + str(args.castle_converter))

    report = {
        "purpose": "Independent Solar shadow sign, axis and length validation",
        "coordinate_convention": {
            "x": "East",
            "y": "North",
            "z": "Up",
            "azimuth": "Clockwise from configured North",
        },
        "freecad_version": ".".join(str(value) for value in FreeCAD.Version()[:3]),
        "shadow_map_quality_changed": False,
        "shadow_algorithm_scope": "baseline shadows=true only; no shadowVolumes/shadowVolumesMain",
        "cases": [],
    }
    for preset in reference.PRESETS:
        FreeCAD.Console.PrintMessage("[GAMEEXPORT] Generating " + preset.key + "\n")
        report["cases"].append(_generate_case(output_dir, preset, args.castle_converter))

    report["status"] = "pass"
    report_path = output_dir / "solar_shadow_validation_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    FreeCAD.Console.PrintMessage("[GAMEEXPORT] Solar shadow validation: PASS\n")
    FreeCAD.Console.PrintMessage("[GAMEEXPORT] Output: " + str(output_dir) + "\n")
    print("[GAMEEXPORT] Solar shadow validation: PASS")
    print("[GAMEEXPORT] Output: " + str(output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
