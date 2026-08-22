"""Castle Model Viewer diagnostics reusable from FreeCAD, CLI or MCP.

The module deliberately has no FreeCAD or Qt imports.  User interfaces are
adapters around :func:`run_diagnostic`, which always treats the source X3D as
read-only and writes results under a separate ``_castle_debug`` directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence


SCHEMA_VERSION = "1.0"
DIAGNOSTIC_VERSION = "2026-08-21-castle-diagnostics-v5-bounded-paths"
VALID_MODES = {"analyze", "interactive", "capture"}
MAX_DIAGNOSTIC_PATH_CHARS = 240
_DIAGNOSTIC_SUFFIXES = (
    ".diagnostic.json",
    ".summary.md",
    ".validation.txt",
    ".castle_stdout.log",
    ".castle_native.log",
    ".gee.analysis.json",
    ".gee.analysis.md",
    ".png",
)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _checked_file(path, label: str) -> Path:
    value = Path(str(path or "")).expanduser()
    if not value.is_file():
        raise FileNotFoundError(label + " not found: " + (value.name or "<empty>"))
    return value.resolve()


def _portable_path(path, root: Path) -> str:
    """Return a shareable relative path, falling back to the file name."""
    value = Path(path)
    try:
        return value.resolve().relative_to(Path(root).resolve()).as_posix()
    except (OSError, ValueError):
        return value.name


def _portable_command(command: Sequence[str], root: Path) -> list:
    """Remove machine-specific directories from a command saved in reports."""
    result = []
    for index, value in enumerate(command):
        text = str(value)
        if index == 0 or Path(text).is_absolute() or "/" in text or "\\" in text:
            result.append(_portable_path(text, root))
        else:
            result.append(text)
    return result


def _redact_private_text(text: str, paths: Sequence[object] = ()) -> str:
    """Redact known local roots from Castle/converter logs before sharing."""
    result = str(text or "")
    replacements = []
    for value in paths:
        candidate = str(value or "").strip()
        if candidate and (
            Path(candidate).is_absolute() or "/" in candidate or "\\" in candidate
        ):
            replacements.extend((candidate, candidate.replace("\\", "/")))
    for value in [
        os.environ.get("USERPROFILE", ""),
        os.environ.get("LOCALAPPDATA", ""),
        str(Path.home()),
    ]:
        candidate = str(value or "").strip()
        if candidate:
            replacements.extend((candidate, candidate.replace("\\", "/")))
    for candidate in sorted(set(replacements), key=len, reverse=True):
        result = result.replace(candidate, "<private-path>")
    # Cover ordinary Windows user paths that were not part of the command.
    result = re.sub(
        r"(?i)[A-Z]:[\\/]Users[\\/][^\\/\r\n]+",
        "<private-user>",
        result,
    )
    return result


def _redact_log_file(path: Path, private_paths: Sequence[object] = ()) -> None:
    value = Path(path)
    if not value.is_file():
        return
    try:
        original = value.read_text(encoding="utf-8", errors="replace")
        redacted = _redact_private_text(original, private_paths)
        if redacted != original:
            value.write_text(redacted, encoding="utf-8")
    except OSError:
        return


def _source_fingerprint(path: Path) -> Dict[str, int]:
    stat_result = path.stat()
    return {
        "size_bytes": int(stat_result.st_size),
        "mtime_ns": int(stat_result.st_mtime_ns),
    }


def _emit(log_callback, level: str, message: str) -> None:
    if log_callback is not None:
        log_callback(str(level), str(message))


def find_castle_converter(viewer_path) -> Optional[Path]:
    """Find ``castle-model-converter`` beside the configured viewer."""
    if not viewer_path:
        return None
    viewer = Path(str(viewer_path)).expanduser()
    suffix = viewer.suffix if viewer.suffix.lower() == ".exe" else ""
    names = ["castle-model-converter" + suffix, "castle-model-converter"]
    for name in names:
        candidate = viewer.parent / name
        if candidate.is_file():
            return candidate.resolve()
    return None


def _safe_filename_token(value: object, fallback: str) -> str:
    """Return a readable token that cannot create nested diagnostic paths."""
    token = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value or "")).strip("._-")
    return token or fallback


def _bounded_diagnostic_prefix(source: Path, stamp: str, folder: Path) -> str:
    """Keep every diagnostic output below a conservative Windows path limit."""
    stem = _safe_filename_token(source.stem, "scene")
    run_token = _safe_filename_token(stamp, "run")
    raw_prefix = stem + "_" + run_token
    folder_length = len(os.path.abspath(str(folder)))
    longest_suffix = max(len(suffix) for suffix in _DIAGNOSTIC_SUFFIXES)
    budget = MAX_DIAGNOSTIC_PATH_CHARS - folder_length - 1 - longest_suffix
    if budget <= 0:
        raise OSError(
            "Diagnostic output directory is too long for portable Windows paths: "
            + folder.name
        )
    if len(raw_prefix) <= budget:
        return raw_prefix

    digest = hashlib.sha256(raw_prefix.encode("utf-8")).hexdigest()[:12]
    if budget <= len(digest) + 1:
        return digest[:budget]
    readable_budget = budget - len(digest) - 1
    readable = raw_prefix[:readable_budget].rstrip("._-")
    if not readable:
        return digest[:budget]
    return readable + "_" + digest


def diagnostic_paths(x3d_path, run_id: Optional[str] = None) -> Dict[str, Path]:
    """Return deterministic output paths without creating or changing files."""
    source = Path(x3d_path)
    stamp = str(run_id or _timestamp())
    folder = source.parent / "_castle_debug"
    prefix = _bounded_diagnostic_prefix(source, stamp, folder)
    return {
        "folder": folder,
        "analysis_base": folder / (prefix + ".x3d"),
        "manifest": folder / (prefix + ".diagnostic.json"),
        "summary": folder / (prefix + ".summary.md"),
        "validation": folder / (prefix + ".validation.txt"),
        "castle_stdout_log": folder / (prefix + ".castle_stdout.log"),
        "castle_native_log": folder / (prefix + ".castle_native.log"),
        # Backward-compatible alias: castle_log now means captured stdout/stderr.
        "castle_log": folder / (prefix + ".castle_stdout.log"),
        "screenshot": folder / (prefix + ".png"),
    }


def build_viewer_command(
    viewer_path,
    x3d_path,
    mode: str = "interactive",
    viewpoint: str = "GameStart",
    width: int = 1600,
    height: int = 900,
    anti_alias: int = 4,
    shader_debug: bool = True,
    screenshot_path=None,
) -> list:
    """Build a Castle command using only documented command-line options."""
    if mode not in {"interactive", "capture"}:
        raise ValueError("Viewer mode must be interactive or capture")
    command = [str(viewer_path), str(x3d_path)]
    if shader_debug:
        command.append("--debug-log-shaders")
    if mode == "capture":
        if screenshot_path is None:
            raise ValueError("screenshot_path is required in capture mode")
        command.extend(
            [
                "--viewpoint",
                str(viewpoint or "GameStart"),
                "--geometry",
                str(max(320, int(width))) + "x" + str(max(240, int(height))),
                "--anti-alias",
                str(max(0, min(4, int(anti_alias)))),
                "--screenshot",
                "0",
                str(screenshot_path),
            ]
        )
    return command


def _run_validation(
    converter: Path,
    x3d: Path,
    output_path: Path,
    timeout: int,
    display_root: Optional[Path] = None,
) -> Dict[str, object]:
    command = [str(converter), str(x3d), "--validate"]
    root = Path(display_root or x3d.parent)
    public_command = _portable_command(command, root)
    public_log = _portable_path(output_path, root)
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=max(10, int(timeout)),
            check=False,
        )
        text = _redact_private_text(completed.stdout or "", command)
        output_path.write_text(text, encoding="utf-8", errors="replace")
        return {
            "status": "completed",
            "return_code": int(completed.returncode),
            "command": public_command,
            "log": public_log,
        }
    except subprocess.TimeoutExpired as exc:
        text = _redact_private_text(
            str(getattr(exc, "stdout", "") or "") + "\nValidation timed out.\n",
            command,
        )
        output_path.write_text(text, encoding="utf-8", errors="replace")
        return {"status": "timeout", "command": public_command, "log": public_log}
    except Exception as exc:
        public_error = _redact_private_text(str(exc), command)
        output_path.write_text(public_error + "\n", encoding="utf-8")
        return {
            "status": "failed",
            "error": public_error,
            "command": public_command,
            "log": public_log,
        }


def default_castle_log_path(viewer_path) -> Optional[Path]:
    """Return the standard Castle GUI log path when it is predictable."""
    app_name = Path(str(viewer_path)).stem
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data) / app_name / (app_name + ".log")
    home = Path.home()
    if home:
        return home / ".config" / app_name / (app_name + ".log")
    return None


def _copy_native_castle_log(source: Optional[Path], destination: Path, old_mtime_ns) -> str:
    """Copy Castle's native GUI log without overwriting captured stdout/stderr."""
    if source is None or not source.is_file():
        return "not_found"
    try:
        source_stat = source.stat()
        if old_mtime_ns is not None and source_stat.st_mtime_ns <= old_mtime_ns:
            return "unchanged"
        if source_stat.st_size <= 0:
            return "empty"
        shutil.copyfile(str(source), str(destination))
        return "copied"
    except Exception:
        return "copy_failed"


def _update_manifest_after_viewer_exit(
    process,
    source: Optional[Path],
    native_destination: Path,
    old_mtime_ns,
    manifest_path: Optional[Path],
    summary_path: Optional[Path],
    screenshot_path: Optional[Path],
    stdout_destination: Optional[Path] = None,
    redaction_paths: Sequence[object] = (),
) -> None:
    """Wait for Castle and persist final lifecycle/log/capture state."""
    return_code = process.wait()
    native_status = _copy_native_castle_log(source, native_destination, old_mtime_ns)
    if stdout_destination is not None:
        _redact_log_file(Path(stdout_destination), redaction_paths)
    if native_status == "copied":
        _redact_log_file(native_destination, redaction_paths)

    if manifest_path is None:
        return
    manifest_path = Path(manifest_path)
    # Castle may exit before run_diagnostic has written the initial manifest.
    for _ in range(50):
        if manifest_path.is_file():
            break
        time.sleep(0.1)
    if not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        castle = dict(manifest.get("castle", {}) or {})
        if int(castle.get("pid", -1) or -1) != int(process.pid):
            return
        castle["status"] = "completed" if int(return_code) == 0 else "failed"
        castle["return_code"] = int(return_code)
        castle["completed_utc"] = _utc_now()
        castle["native_log_status"] = native_status
        castle["log_status"] = "completed"
        if screenshot_path is not None:
            screenshot_path = Path(screenshot_path)
            castle["screenshot_exists"] = screenshot_path.is_file()
            if not screenshot_path.is_file():
                manifest.setdefault("warnings", []).append(
                    "Castle capture process completed but the requested screenshot was not found."
                )
        manifest["castle"] = castle
        outputs = manifest.setdefault("outputs", {})
        outputs["castle_stdout_log"] = str(castle.get("stdout_log", castle.get("log", "")))
        outputs["castle_log"] = outputs["castle_stdout_log"]
        if native_destination.is_file():
            outputs["castle_native_log"] = _portable_path(
                native_destination, manifest_path.parent.parent
            )
        if int(return_code) != 0:
            manifest.setdefault("warnings", []).append(
                "Castle Model Viewer exited with return code " + str(return_code) + "."
            )
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True),
            encoding="utf-8",
        )
        if summary_path is not None:
            _write_summary(manifest, Path(summary_path))
    except Exception:
        # Diagnostics must never interfere with Castle or the source X3D.
        return


def _start_viewer(
    command: Sequence[str],
    stdout_log_path: Path,
    native_log_path: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    summary_path: Optional[Path] = None,
    screenshot_path: Optional[Path] = None,
    display_root: Optional[Path] = None,
) -> Dict[str, object]:
    root = Path(display_root or Path(stdout_log_path).parent.parent)
    fallback_log = default_castle_log_path(command[0])
    fallback_mtime = None
    if fallback_log is not None and fallback_log.is_file():
        fallback_mtime = fallback_log.stat().st_mtime_ns
    native_destination = Path(native_log_path or (str(stdout_log_path) + ".native.log"))

    log_handle = Path(stdout_log_path).open("w", encoding="utf-8", errors="replace")
    try:
        process = subprocess.Popen(
            list(command),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
    finally:
        log_handle.close()

    monitor = threading.Thread(
        target=_update_manifest_after_viewer_exit,
        args=(
            process,
            fallback_log,
            native_destination,
            fallback_mtime,
            manifest_path,
            summary_path,
            screenshot_path,
            stdout_log_path,
            command,
        ),
        name="GameExportCastleMonitor-" + str(process.pid),
        daemon=True,
    )
    monitor.start()
    return {
        "status": "started",
        "pid": int(process.pid),
        "command": _portable_command(command, root),
        "log": _portable_path(stdout_log_path, root),
        "stdout_log": _portable_path(stdout_log_path, root),
        "native_log_source": fallback_log.name if fallback_log is not None else "",
        "native_log_copy": _portable_path(native_destination, root),
        "log_status": "running",
        "native_log_status": "pending_until_castle_exits",
        "started_utc": _utc_now(),
    }


def _recommendations(analysis: Dict[str, object]) -> list:
    lights = analysis.get("lights", {}) if isinstance(analysis, dict) else {}
    counts = lights.get("counts", {}) if isinstance(lights, dict) else {}
    total_local = int(counts.get("PointLight", 0) or 0) + int(counts.get("SpotLight", 0) or 0)
    recommendations = []
    if total_local > 16:
        recommendations.append(
            {
                "code": "many_local_lights",
                "message": "Many local lights may affect the same shape.",
                "castle_test": "View -> Max Lights Per Shape -> 8",
                "suggested_value": 8,
            }
        )
    summary = analysis.get("summary", {}) if isinstance(analysis, dict) else {}
    if int(summary.get("duplicate_def_names", 0) or 0):
        recommendations.append(
            {
                "code": "duplicate_def_names",
                "message": "Duplicate DEF names should be made unique before final delivery.",
            }
        )
    return recommendations


def _write_summary(manifest: Dict[str, object], path: Path) -> None:
    analysis = manifest.get("analysis", {}) or {}
    summary = analysis.get("summary", {}) if isinstance(analysis, dict) else {}
    counts = (analysis.get("lights", {}) or {}).get("counts", {}) if isinstance(analysis, dict) else {}
    lines = [
        "# Diagnostico Castle",
        "",
        "- Schema: " + str(manifest.get("schema_version", "")),
        "- Version: " + str(manifest.get("diagnostic_version", "")),
        "- X3D: `" + str(manifest.get("x3d", "")) + "`",
        "- Modo: " + str(manifest.get("mode", "")),
        "- Validacion: " + str((manifest.get("validation", {}) or {}).get("status", "disabled")),
        "- Castle: " + str((manifest.get("castle", {}) or {}).get("status", "not_started")),
        "- Shapes: " + str(summary.get("shapes", 0)),
        "- Triangulos aproximados: " + str(summary.get("triangles_approx", 0)),
        "- PointLight: " + str(counts.get("PointLight", 0)),
        "- SpotLight: " + str(counts.get("SpotLight", 0)),
        "- DirectionalLight: " + str(counts.get("DirectionalLight", 0)),
        "- DEF duplicados: " + str(summary.get("duplicate_def_names", 0)),
        "",
        "## Recomendaciones",
        "",
    ]
    recommendations = manifest.get("recommendations", []) or []
    if recommendations:
        for item in recommendations:
            lines.append("- " + str(item.get("message", "")))
            if item.get("castle_test"):
                lines.append("  - Prueba Castle: `" + str(item["castle_test"]) + "`")
    else:
        lines.append("- No se generaron recomendaciones automaticas.")
    lines.extend(["", "El diagnostico no modifica el FCStd ni el X3D original.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def run_diagnostic(
    x3d_path,
    viewer_path=None,
    mode: str = "interactive",
    validate: bool = True,
    shader_debug: bool = True,
    viewpoint: str = "GameStart",
    width: int = 1600,
    height: int = 900,
    anti_alias: int = 4,
    top_n: int = 20,
    progress_callback: Optional[Callable[[int, int], bool]] = None,
    analyzer_module=None,
    validation_timeout: int = 300,
    run_id: Optional[str] = None,
    document: Optional[str] = None,
    log_callback: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, object]:
    """Analyze an X3D and optionally validate or open it with Castle.

    This is the stable entry point intended for FreeCAD, tests and MCP.
    """
    if mode not in VALID_MODES:
        raise ValueError("Unsupported diagnostic mode: " + str(mode))
    x3d = _checked_file(x3d_path, "X3D")
    source_before = _source_fingerprint(x3d)
    warnings = []
    viewer = None
    if viewer_path:
        try:
            viewer = _checked_file(viewer_path, "Castle Model Viewer")
        except FileNotFoundError:
            if mode != "analyze":
                raise
            warnings.append("Configured Castle Model Viewer was not found; validation was skipped.")
    if mode != "analyze" and viewer is None:
        raise FileNotFoundError("Castle Model Viewer path is required")

    paths = diagnostic_paths(x3d, run_id=run_id)
    paths["folder"].mkdir(parents=True, exist_ok=True)
    _emit(log_callback, "INFO", "Castle diagnostics started: " + x3d.name)
    _emit(log_callback, "DEBUG", "Diagnostic mode: " + mode)
    _emit(log_callback, "DEBUG", "Diagnostic folder: " + paths["folder"].name)

    if analyzer_module is None:
        from . import x3d_analyzer as analyzer_module

    analysis = analyzer_module.analyze_x3d(
        x3d,
        top_n=max(1, int(top_n)),
        progress_callback=progress_callback,
    )
    analysis_json, analysis_markdown = analyzer_module.write_reports(
        analysis, paths["analysis_base"]
    )
    analysis_json = Path(analysis_json).resolve()
    analysis_markdown = Path(analysis_markdown).resolve()
    debug_folder = paths["folder"].resolve()
    if analysis_json.parent != debug_folder or analysis_markdown.parent != debug_folder:
        raise RuntimeError("X3D analyzer reports must be written inside _castle_debug")
    _emit(log_callback, "INFO", "X3D analysis completed")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "success": True,
        "operation": "castle_diagnostics",
        "generated_utc": _utc_now(),
        "document": str(document or ""),
        "mode": mode,
        "x3d": x3d.name,
        "source_unchanged": True,
        "source": source_before,
        "analysis": analysis,
        "recommendations": _recommendations(analysis),
        "warnings": warnings,
        "settings": {
            "validate": bool(validate),
            "shader_debug": bool(shader_debug),
            "viewpoint": str(viewpoint or "GameStart"),
            "width": int(width),
            "height": int(height),
            "anti_alias": int(anti_alias),
        },
        "outputs": {
            "folder": _portable_path(paths["folder"], x3d.parent),
            "analysis_json": _portable_path(analysis_json, x3d.parent),
            "analysis_markdown": _portable_path(analysis_markdown, x3d.parent),
            "manifest": _portable_path(paths["manifest"], x3d.parent),
            "summary": _portable_path(paths["summary"], x3d.parent),
        },
    }

    converter = find_castle_converter(viewer) if viewer else None
    if validate:
        if converter is None:
            reason = "castle-model-converter not found beside the viewer"
            paths["validation"].write_text(reason + "\n", encoding="utf-8")
            manifest["validation"] = {
                "status": "skipped",
                "reason": reason,
                "log": _portable_path(paths["validation"], x3d.parent),
            }
            manifest["warnings"].append(reason)
            _emit(log_callback, "WARN", reason)
        else:
            _emit(log_callback, "INFO", "Validating with: " + converter.name)
            manifest["validation"] = _run_validation(
                converter,
                x3d,
                paths["validation"],
                validation_timeout,
                display_root=x3d.parent,
            )
            _emit(
                log_callback,
                "INFO",
                "Castle validation status: " + str(manifest["validation"].get("status", "")),
            )
        manifest["outputs"]["validation"] = _portable_path(
            paths["validation"], x3d.parent
        )
    else:
        manifest["validation"] = {"status": "disabled"}

    if viewer is not None and mode != "analyze":
        command = build_viewer_command(
            viewer,
            x3d,
            mode=mode,
            viewpoint=viewpoint,
            width=width,
            height=height,
            anti_alias=anti_alias,
            shader_debug=shader_debug,
            screenshot_path=paths["screenshot"] if mode == "capture" else None,
        )
        _emit(
            log_callback,
            "INFO",
            "Launching Castle: " + " ".join(_portable_command(command, x3d.parent)),
        )
        manifest["castle"] = _start_viewer(
            command,
            paths["castle_stdout_log"],
            native_log_path=paths["castle_native_log"],
            manifest_path=paths["manifest"],
            summary_path=paths["summary"],
            screenshot_path=paths["screenshot"] if mode == "capture" else None,
            display_root=x3d.parent,
        )
        manifest["outputs"]["castle_stdout_log"] = _portable_path(
            paths["castle_stdout_log"], x3d.parent
        )
        # Compatibility key retained for consumers written against v2.
        manifest["outputs"]["castle_log"] = manifest["outputs"]["castle_stdout_log"]
        manifest["outputs"]["castle_native_log"] = _portable_path(
            paths["castle_native_log"], x3d.parent
        )
        if mode == "capture":
            manifest["outputs"]["screenshot"] = _portable_path(
                paths["screenshot"], x3d.parent
            )
            _emit(log_callback, "INFO", "Capture requested: " + paths["screenshot"].name)

    source_after = _source_fingerprint(x3d)
    manifest["source_unchanged"] = source_before == source_after
    if not manifest["source_unchanged"]:
        manifest["warnings"].append("The source X3D metadata changed during diagnostics.")
        _emit(log_callback, "WARN", "Source X3D metadata changed during diagnostics")

    _write_summary(manifest, paths["summary"])
    paths["manifest"].write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
    _emit(log_callback, "INFO", "Castle diagnostic manifest: " + paths["manifest"].name)
    return manifest


__all__ = [
    "DIAGNOSTIC_VERSION",
    "MAX_DIAGNOSTIC_PATH_CHARS",
    "SCHEMA_VERSION",
    "build_viewer_command",
    "diagnostic_paths",
    "find_castle_converter",
    "run_diagnostic",
]
