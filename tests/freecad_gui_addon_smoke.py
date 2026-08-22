"""Automated FreeCAD GUI smoke test for a clean GameEngineExportWB install.

Run this file with the FreeCAD GUI executable, not with ordinary Python.
Results are written below FreeCAD's isolated user directory or to the path in
``GEE_SMOKE_RESULT``. The test never modifies a user's project document.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import time
import traceback

import FreeCAD
import FreeCADGui
import Part

try:
    from PySide import QtCore, QtGui
except ImportError:
    from PySide6 import QtCore, QtGui, QtWidgets

    for name in (
        "QApplication",
        "QDialog",
        "QTabWidget",
        "QToolBar",
        "QTranslator",
    ):
        if not hasattr(QtGui, name) and hasattr(QtWidgets, name):
            setattr(QtGui, name, getattr(QtWidgets, name))


RESULT_PATH = Path(
    os.environ.get("GEE_SMOKE_RESULT", "")
    or (Path(FreeCAD.getUserAppDataDir()) / "gameengineexportwb-gui-smoke.json")
)
ARTIFACTS = RESULT_PATH.parent / "gameengineexportwb-smoke-artifacts"
CASTLE_PATH = Path(os.environ.get("GEE_CASTLE_PATH", "")).expanduser()


class SmokeFailure(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise SmokeFailure(str(message))


def process_events():
    app = QtGui.QApplication.instance()
    if app is not None:
        app.processEvents()


def reject_visible_dialogs():
    app = QtGui.QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        if isinstance(widget, QtGui.QDialog) and widget.isVisible():
            widget.reject()


def close_document(doc):
    if doc is not None:
        name = str(getattr(doc, "Name", "") or "")
        if name:
            FreeCAD.closeDocument(name)
            process_events()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def find_object_by_role(doc, role):
    """Find generated geometry by stable semantic role, not Arch's internal name."""
    expected = str(role or "")
    for obj in getattr(doc, "Objects", []) or []:
        if str(getattr(obj, "GEE_Role", "") or "") == expected:
            return obj
        if str(getattr(obj, "Role", "") or "") == expected:
            return obj
    return None


def close_freecad():
    """Close test documents and the isolated GUI without save prompts."""
    for name in list((FreeCAD.listDocuments() or {}).keys()):
        try:
            FreeCAD.closeDocument(name)
        except Exception:
            pass
    main_window = FreeCADGui.getMainWindow()
    if main_window is not None:
        main_window.close()
    app = QtGui.QApplication.instance()
    if app is not None:
        app.quit()


def help_and_language_checks(result):
    from GameEngineExportWB import i18n
    from GameEngineExportWB.commands import cmd_help, cmd_reload_workbench
    from GameEngineExportWB.ui import panel_info

    general = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General")
    original_language = general.GetString("Language", "")

    qm_path = Path(i18n.__file__).resolve().parent / "translations" / "GameEngineExportWB_es-ES.qm"
    translator = QtCore.QTranslator()
    require(qm_path.is_file(), "Compiled Spanish QM is missing")
    require(translator.load(str(qm_path)), "Compiled Spanish QM cannot be loaded by Qt")

    expected_titles = {
        "English": ["Getting Started", "Buttons", "AI / JSON", "Information"],
        "Spanish": ["Primeros pasos", "Botones", "IA / JSON", "Informacion"],
    }
    language_results = {}
    for language, expected in expected_titles.items():
        general.SetString("Language", language)
        dialog = panel_info.build_help_dialog()
        tabs = dialog.findChild(QtGui.QTabWidget)
        titles = [str(tabs.tabText(index)) for index in range(tabs.count())]
        require(titles == expected, f"Unexpected Help tabs for {language}: {titles}")
        require(not dialog.windowIcon().isNull(), "Help dialog icon is null")
        language_results[language] = titles
        dialog.reject()
        dialog.deleteLater()

    general.SetString("Language", "English")
    QtCore.QTimer.singleShot(50, reject_visible_dialogs)
    cmd_help.CommandClass().Activated()
    require(cmd_reload_workbench.reload_workbench_runtime(), "Hot restart returned false")
    live_help = importlib.import_module("GameEngineExportWB.commands.cmd_help")
    QtCore.QTimer.singleShot(50, reject_visible_dialogs)
    live_help.CommandClass().Activated()

    live_info = importlib.import_module("GameEngineExportWB.ui.panel_info")
    tip_params = FreeCAD.ParamGet(live_info.TIP_PARAM_GROUP)
    tip_params.SetBool("show_startup_tips", True)
    tip_dialog = live_info.build_startup_tips_dialog()
    require(
        "Do not show" in str(tip_dialog._gee_dont_show.text()),
        "Getting-started opt-out checkbox is missing",
    )
    tip_dialog._gee_dont_show.setChecked(True)
    original_builder = live_info.build_startup_tips_dialog
    live_info.build_startup_tips_dialog = lambda parent=None: tip_dialog
    QtCore.QTimer.singleShot(20, tip_dialog.reject)
    try:
        live_info.show_startup_tips(force=True)
    finally:
        live_info.build_startup_tips_dialog = original_builder
    require(
        not tip_params.GetBool("show_startup_tips", True),
        "Getting-started opt-out preference was not persisted",
    )
    require(
        live_info.show_startup_tips(force=False) is None,
        "Disabled getting-started tips were shown without force",
    )
    forced_dialog = live_info.build_startup_tips_dialog()
    live_info.build_startup_tips_dialog = lambda parent=None: forced_dialog
    QtCore.QTimer.singleShot(20, forced_dialog.reject)
    try:
        require(
            live_info.show_startup_tips(force=True) is forced_dialog,
            "Help could not show getting-started tips again",
        )
    finally:
        live_info.build_startup_tips_dialog = original_builder
    tip_params.SetBool("show_startup_tips", True)

    from GameEngineExportWB.core import json_ai

    workbench_context = live_info.build_workbench_ai_package()
    prompt_only = json_ai.get_prompt_template("en")
    prompt_json = json_ai.build_ai_prompt({"units": "mm", "rooms": []}, "en")
    for value, marker in (
        (workbench_context, "AI_CONTEXT.md"),
        (prompt_only, "SUGGESTED AI PROMPT"),
        (prompt_json, "CURRENT JSON:"),
    ):
        live_info._copy_to_clipboard(value)
        require(marker in QtGui.QApplication.clipboard().text(), f"Clipboard copy missing {marker}")

    if original_language:
        general.SetString("Language", original_language)
    else:
        general.SetString("Language", "English")
    result["help_languages"] = language_results
    result["help_hot_restart"] = True
    result["tips_persistence"] = True
    result["ai_clipboard_flows"] = 3
    result["qm_loaded"] = True


def workbench_registration_checks(result):
    workbenches = dict(FreeCADGui.listWorkbenches() or {})
    require(
        "GameEngineExportWorkbench" in workbenches,
        "GameEngineExportWorkbench is not registered",
    )
    FreeCAD._GEE_TipsShownThisSession = True
    tip_params = FreeCAD.ParamGet("User parameter:Plugins/GameEngineExportWB/Help")
    tip_params.SetBool("show_startup_tips", False)
    FreeCADGui.activateWorkbench("GameEngineExportWorkbench")
    process_events()

    from GameEngineExportWB.commands import cmd_add_light_properties
    from GameEngineExportWB.commands import cmd_analyze_x3d
    from GameEngineExportWB.commands import cmd_bim_doors_windows
    from GameEngineExportWB.commands import cmd_castle_diagnostics
    from GameEngineExportWB.commands import cmd_export_and_launch
    from GameEngineExportWB.commands import cmd_help
    from GameEngineExportWB.commands import cmd_import_json_example
    from GameEngineExportWB.commands import cmd_open_panel
    from GameEngineExportWB.commands import cmd_quick_examples
    from GameEngineExportWB.commands import cmd_reload_workbench
    from GameEngineExportWB.commands import cmd_roof_quick_example
    from GameEngineExportWB.ui import workbench as workbench_module

    expected = {
        cmd_quick_examples.CommandClass.CommandName,
        cmd_export_and_launch.CommandClass.CommandName,
        cmd_open_panel.CommandClass.CommandName,
        cmd_help.CommandClass.CommandName,
        cmd_add_light_properties.CommandClass.CommandName,
        cmd_import_json_example.CommandClass.CommandName,
        cmd_bim_doors_windows.CommandClass.CommandName,
        cmd_roof_quick_example.CommandClass.CommandName,
        cmd_analyze_x3d.CommandClass.CommandName,
        cmd_castle_diagnostics.CommandClass.CommandName,
    }
    toolbar_items = str(FreeCADGui.activeWorkbench().getToolbarItems())
    for command_name in expected:
        require(command_name in toolbar_items, f"Toolbar command missing: {command_name}")
    require(
        cmd_reload_workbench.CommandClass.CommandName not in toolbar_items,
        "Reload Workbench unexpectedly appears in a normal toolbar",
    )
    toolbar_titles = {
        str(toolbar.windowTitle())
        for toolbar in FreeCADGui.getMainWindow().findChildren(QtGui.QToolBar)
    }
    expected_titles = {
        "Game Engine Export",
        "Game Engine Export - Scene / AI",
        "Game Engine Export - Diagnostics",
    }
    require(expected_titles.issubset(toolbar_titles), f"Toolbar titles missing: {toolbar_titles}")
    for command_name in expected | {cmd_reload_workbench.CommandClass.CommandName}:
        require(command_name in set(FreeCADGui.listCommands()), f"Command not registered: {command_name}")
    command_classes = (
        cmd_quick_examples.CommandClass,
        cmd_export_and_launch.CommandClass,
        cmd_open_panel.CommandClass,
        cmd_help.CommandClass,
        cmd_add_light_properties.CommandClass,
        cmd_import_json_example.CommandClass,
        cmd_bim_doors_windows.CommandClass,
        cmd_roof_quick_example.CommandClass,
        cmd_analyze_x3d.CommandClass,
        cmd_castle_diagnostics.CommandClass,
        cmd_reload_workbench.CommandClass,
    )
    icon_paths = []
    for command_class in command_classes:
        pixmap = Path(command_class().GetResources().get("Pixmap", ""))
        require(pixmap.is_file(), f"Command icon is missing: {command_class.CommandName}")
        require(not QtGui.QIcon(str(pixmap)).isNull(), f"Command icon is invalid: {pixmap.name}")
        icon_paths.append(pixmap.name)
    workbench_icon = Path(workbench_module.GameEngineExportWorkbench.Icon)
    require(workbench_icon.is_file(), "Workbench icon is missing")
    require(not QtGui.QIcon(str(workbench_icon)).isNull(), "Workbench icon is invalid")
    result["workbench_registered"] = True
    result["toolbar_count"] = 3
    result["toolbar_commands"] = len(expected)
    result["reload_menu_only"] = True
    result["icons_loaded"] = len(icon_paths) + 1


def generate_example(example_type, name, **overrides):
    from GameEngineExportWB.core import quick_examples

    doc = FreeCAD.newDocument(name)
    options = {
        "building_type": example_type,
        "seed": 424242,
        "clear_previous": True,
        "copy_context": False,
        "ai_prompt_language": "en",
    }
    options.update(overrides)
    root = quick_examples.generate_quick_example(options)
    doc.recompute()
    require(root is not None, f"{example_type} returned no root")
    require(doc.getObject("GameStart") is not None, f"{example_type} has no GameStart")
    context_text = str(getattr(root, "GEE_ContextJSON", "") or "")
    payload = json.loads(context_text)
    require(payload.get("units") == "mm", f"{example_type} context units changed")
    return doc, root, payload


def quick_example_and_json_checks(result):
    from GameEngineExportWB.core import json_ai, json_importer
    from GameEngineExportWB.ui import panel_export

    example_results = {}
    house_payload = None
    for example_type in ("Casa", "Oficina", "Fotometria", "Aleatorio"):
        doc, root, payload = generate_example(
            example_type,
            "GEE_Smoke_" + example_type,
            create_terrain=example_type in {"Casa", "Oficina"},
        )
        actual_type = str(getattr(root, "GEE_ExampleType", "") or "")
        if example_type == "Aleatorio":
            require(actual_type in {"Casa", "Oficina"}, "Random example chose an invalid type")
        else:
            require(actual_type == example_type, f"Unexpected generated type: {actual_type}")
        if example_type == "Casa":
            require(doc.getObject("GEE_Terrain_Irregular") is not None, "House terrain missing")
            require(
                find_object_by_role(doc, "building_floor") is not None,
                "House floor slab missing",
            )
            house_payload = payload
            stale_panel = panel_export.ExportTaskPanel()
            stale_panel.chk_ground_texture.setChecked(True)
            stale_panel.ground_object_line.setText("ObjectFromAnotherDocument")
            stale_panel.ground_texture_line.setText("X:/missing/old-texture.png")
            stale_cfg = stale_panel._ground_texture_config(log=True)
            require(not stale_cfg["enabled"], "Quick Example inherited a stale ground texture")
            require(not stale_cfg["texture_path"], "Stale Quick Example texture path was retained")
            stale_panel.widget.deleteLater()
        if example_type == "Fotometria":
            require(
                doc.getObject("GEE_PhotometricLuminaire_1") is not None,
                "Photometric luminaires missing",
            )
        example_results[example_type] = actual_type
        close_document(doc)

    doc, root, payload = generate_example(
        "Laberinto",
        "GEE_Smoke_Maze_Open",
        maze_rows=3,
        maze_cols=4,
        maze_cell_mm=1500,
        include_ceiling=False,
        create_terrain=False,
    )
    floor = doc.getObject("GEE_MazeFloor")
    ground = doc.getObject("GEE_MazeOuterGround")
    require(floor is not None and ground is not None, "Maze floor or outer ground missing")
    require(abs(float(floor.SidewalkWidth_mm) - 1000.0) < 1e-6, "Maze sidewalk is not 1000 mm")
    require(doc.getObject("GEE_MazeCeiling") is None, "Maze ceiling ignored disabled state")
    require(
        abs(float(floor.Shape.BoundBox.ZMax) - float(ground.Shape.BoundBox.ZMax)) > 1e-6,
        "Maze floor and outer ground are coplanar",
    )
    close_document(doc)

    doc, root, payload = generate_example(
        "Laberinto",
        "GEE_Smoke_Maze_Closed",
        maze_rows=3,
        maze_cols=4,
        maze_cell_mm=1500,
        include_ceiling=True,
        create_terrain=False,
    )
    require(doc.getObject("GEE_MazeCeiling") is not None, "Maze ceiling ignored enabled state")
    example_results["Laberinto"] = "ceiling_off_and_on"
    close_document(doc)

    require(house_payload is not None, "House payload was not retained for JSON test")
    prompt_package = json_ai.build_ai_prompt(house_payload, "en")
    require("CURRENT JSON:" in prompt_package, "Prompt + JSON package is incomplete")
    modified = dict(house_payload)
    modified["dimensions"] = dict(house_payload["dimensions"])
    modified["dimensions"]["width_mm"] = float(modified["dimensions"]["width_mm"]) + 500.0
    doc = FreeCAD.newDocument("GEE_Smoke_JSON_Import")
    imported_root, imported_payload, _context = json_importer.generate_quick_example_from_payload(
        modified,
        {"clear_previous": True, "copy_context": False, "ai_prompt_language": "en"},
    )
    require(imported_root is not None, "JSON import returned no root")
    require(
        float(imported_payload["dimensions"]["width_mm"])
        == float(modified["dimensions"]["width_mm"]),
        "JSON import did not apply the modified width",
    )
    close_document(doc)
    result["quick_examples"] = example_results
    result["json_round_trip"] = True
    result["stale_ground_texture_blocked"] = True


def one_click_quick_example_checks(result):
    """Exercise Quick Example -> conditional export -> Castle launch control flow."""
    from GameEngineExportWB.commands import cmd_export_and_launch
    from GameEngineExportWB.ui import panel_export

    require(CASTLE_PATH.is_file(), "Castle path is unavailable for one-click flow")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    doc, _root, _payload = generate_example(
        "Casa",
        "GEE_Smoke_OneClick",
        create_terrain=True,
    )
    token = str(int(time.time() * 1000))
    base_name = "one-click-house-" + token
    fcstd = ARTIFACTS / (base_name + ".FCStd")
    x3d = ARTIFACTS / (base_name + ".x3d")
    doc.recompute()
    doc.saveAs(str(fcstd))

    setup_panel = panel_export.ExportTaskPanel()
    setup_panel.output_dir_line.setText(str(ARTIFACTS))
    setup_panel.base_name_line.setText(base_name)
    setup_panel.cge_path_line.setText(str(CASTLE_PATH))
    setup_panel.params.SetString("cge_path", str(CASTLE_PATH))
    setup_panel._update_export_names()
    setup_panel._save_sidecar(str(ARTIFACTS), base_name, "GameStart")
    setup_panel.widget.deleteLater()

    launches = []
    original_get_open_panel = cmd_export_and_launch._get_open_panel_module
    original_launch = panel_export.ExportTaskPanel._launch_castle_engine

    class _OpenPanelAdapter:
        @staticmethod
        def _reload_export_runtime():
            return panel_export

    def _capture_launch(_panel, file_path):
        launches.append([str(CASTLE_PATH), str(file_path)])

    cmd_export_and_launch._get_open_panel_module = lambda: _OpenPanelAdapter
    panel_export.ExportTaskPanel._launch_castle_engine = _capture_launch
    try:
        command = cmd_export_and_launch.CommandClass()
        command.Activated()
        require(x3d.is_file(), "One-click command did not create the X3D")
        require(len(launches) == 1, "One-click command did not request Castle launch")
        first_hash = sha256(x3d)
        first_mtime = x3d.stat().st_mtime_ns

        command.Activated()
        require(len(launches) == 2, "Unchanged one-click scene was not launched")
        require(sha256(x3d) == first_hash, "Unchanged one-click scene was re-exported")
        require(x3d.stat().st_mtime_ns == first_mtime, "Unchanged X3D timestamp changed")

        terrain = doc.getObject("GEE_Terrain_Irregular")
        require(terrain is not None, "One-click scene terrain is missing")
        terrain.Placement.Base.x += 25.0
        doc.recompute()
        command.Activated()
        require(len(launches) == 3, "Changed one-click scene was not launched")
        require(sha256(x3d) != first_hash, "Changed one-click scene was not re-exported")
    finally:
        panel_export.ExportTaskPanel._launch_castle_engine = original_launch
        cmd_export_and_launch._get_open_panel_module = original_get_open_panel

    for arguments in launches:
        require(Path(arguments[0]) == CASTLE_PATH, "One-click used the wrong Castle executable")
        require(Path(arguments[1]).name == x3d.name, "One-click launched the wrong X3D")
    result["one_click_quick_example"] = {
        "new_export": True,
        "reuse_unchanged": True,
        "reexport_changed": True,
        "castle_launch_requests": len(launches),
    }
    close_document(doc)
    return x3d


def material_export_and_diagnostic_checks(result, castle_x3d=None):
    from GameEngineExportWB.commands import cmd_export_and_launch
    from GameEngineExportWB.core import castle_diagnostics
    from GameEngineExportWB.core import exporter_x3d
    from GameEngineExportWB.core import gamestart
    from GameEngineExportWB.core import material_assignments
    from GameEngineExportWB.core import x3d_analyzer
    from GameEngineExportWB.ui import panel_export

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    doc = FreeCAD.newDocument("GEE_Smoke_Materials")
    objects = []
    for index in range(3):
        obj = doc.addObject("Part::Feature", f"MaterialBox{index + 1}")
        obj.Label = f"Material Box {index + 1}"
        obj.Shape = Part.makeBox(1000, 1000, 1000, FreeCAD.Vector(index * 1500, 0, 0))
        objects.append(obj)
    gamestart_obj = gamestart.ensure_gamestart(doc, "GameStart")
    require(gamestart_obj is not None, "Material scene GameStart could not be created")
    gamestart_obj.Placement.Base = FreeCAD.Vector(1500.0, -2500.0, 1600.0)
    doc.recompute()

    panel = panel_export.ExportTaskPanel()
    FreeCADGui.Selection.clearSelection()
    for obj in objects:
        FreeCADGui.Selection.addSelection(obj)
    panel._use_selection_as_material_objects()
    require(len(panel.material_object_names) == 3, "Multiple material selection was not captured")
    panel._set_combo_data(panel.combo_material_mode, material_assignments.MODE_TEXTURE)
    panel._set_combo_data(panel.combo_material_texture, material_assignments.TEXTURE_WOOD)
    panel._set_combo_data(panel.combo_material_projection, material_assignments.PROJECTION_XY)
    panel.spin_material_tile_u.setValue(1200.0)
    panel.spin_material_tile_v.setValue(180.0)
    panel._apply_object_material_assignment()

    projection_results = []
    panel.material_object_names = [objects[0].Name]
    for projection in (
        material_assignments.PROJECTION_AUTO,
        material_assignments.PROJECTION_XY,
        material_assignments.PROJECTION_XZ,
        material_assignments.PROJECTION_YZ,
    ):
        panel._set_combo_data(panel.combo_material_projection, projection)
        panel._apply_object_material_assignment()
        projection_results.append(str(getattr(objects[0], material_assignments.PROP_PROJECTION)))
    require(
        projection_results
        == [
            material_assignments.PROJECTION_AUTO,
            material_assignments.PROJECTION_XY,
            material_assignments.PROJECTION_XZ,
            material_assignments.PROJECTION_YZ,
        ],
        f"Projection persistence failed: {projection_results}",
    )

    custom_texture = Path(material_assignments.builtin_texture_path(material_assignments.TEXTURE_CERAMIC))
    panel._set_combo_data(panel.combo_material_texture, material_assignments.TEXTURE_CUSTOM)
    panel.material_texture_line.setText(str(custom_texture))
    panel._apply_object_material_assignment()

    panel.material_object_names = [objects[1].Name]
    panel._set_combo_data(panel.combo_material_mode, material_assignments.MODE_POLISHED)
    panel._set_combo_data(panel.combo_material_texture, material_assignments.TEXTURE_WOOD)
    panel.spin_material_reflectivity.setValue(0.65)
    panel._apply_object_material_assignment()

    panel.material_object_names = [objects[2].Name]
    panel._set_combo_data(panel.combo_material_mode, material_assignments.MODE_MIRROR)
    panel._set_combo_data(panel.combo_mirror_size, 512)
    panel._apply_object_material_assignment()

    polished = material_assignments.read_object_assignment(objects[1])
    mirror = material_assignments.read_object_assignment(objects[2])
    require(polished["mode"] == material_assignments.MODE_POLISHED, "Polished mode was not stored")
    require(mirror["mode"] == material_assignments.MODE_MIRROR, "Mirror mode was not stored")
    require(polished["mode"] != mirror["mode"], "Polished was conflated with a true mirror")
    panel.material_object_names = [obj.Name for obj in objects]
    panel._refresh_object_material_status()
    material_status = panel.object_material_status_box.toPlainText().lower()
    require(
        "captured objects" in material_status or "objetos capturados" in material_status,
        "Material status panel is not visible",
    )

    fcstd = ARTIFACTS / "materials-persistence.FCStd"
    doc.recompute()
    doc.saveAs(str(fcstd))
    names = [obj.Name for obj in objects]
    close_document(doc)
    doc = FreeCAD.openDocument(str(fcstd))
    objects = [doc.getObject(name) for name in names]
    require(all(objects), "Saved material objects could not be reopened")
    require(
        material_assignments.read_object_assignment(objects[1])["mode"]
        == material_assignments.MODE_POLISHED,
        "Polished material did not persist in FCStd",
    )
    require(
        material_assignments.read_object_assignment(objects[2])["mode"]
        == material_assignments.MODE_MIRROR,
        "Mirror material did not persist in FCStd",
    )

    x3d = ARTIFACTS / "materials-persistence.x3d"
    exporter_x3d.export_to_x3d(
        objects,
        x3d,
        gamestart_meta=gamestart.get_metadata(doc.getObject("GameStart")),
        material_cfg={
            "object_assignments": material_assignments.collect_assignments(objects),
            "improve_interior_lighting": False,
            "interior_lighting_mode": "None",
        },
    )
    text = x3d.read_text(encoding="utf-8", errors="replace")
    require("RenderedTexture" in text and "ViewpointMirror" in text, "Castle mirror nodes missing")
    require("shininess" in text and "specularColor" in text, "Polished material decoration missing")
    require("ImageTexture" in text, "Object texture was not exported")

    before = sha256(x3d)
    manifest = castle_diagnostics.run_diagnostic(
        x3d,
        mode="analyze",
        validate=False,
        analyzer_module=x3d_analyzer,
        run_id="freecad-gui-smoke",
        document=doc.Name,
    )
    require(before == sha256(x3d), "Castle diagnostics modified the source X3D")
    manifest_path = x3d.parent / manifest["outputs"]["manifest"]
    manifest_text = manifest_path.read_text(encoding="utf-8")
    require(str(x3d.parent.resolve()) not in manifest_text, "Diagnostic manifest leaked an absolute path")

    cache_panel = panel_export.ExportTaskPanel()
    cache_panel.output_dir_line.setText(str(ARTIFACTS))
    cache_panel.base_name_line.setText(x3d.stem)
    first_fingerprint = cmd_export_and_launch._scene_fingerprint(cache_panel, panel_export)
    cmd_export_and_launch._save_export_cache(cache_panel, panel_export, x3d, first_fingerprint)
    matches, reason = cmd_export_and_launch._cache_matches(
        cache_panel, panel_export, x3d, first_fingerprint
    )
    require(matches, f"Unchanged X3D was not reusable: {reason}")
    objects[0].Placement.Base.x += 25.0
    doc.recompute()
    changed_fingerprint = cmd_export_and_launch._scene_fingerprint(cache_panel, panel_export)
    require(changed_fingerprint != first_fingerprint, "Model change did not invalidate export cache")

    castle_result = {"available": CASTLE_PATH.is_file()}
    if CASTLE_PATH.is_file():
        capture_x3d = Path(castle_x3d) if castle_x3d else x3d
        require(capture_x3d.is_file(), "Castle capture source X3D is missing")
        castle_manifest = castle_diagnostics.run_diagnostic(
            capture_x3d,
            viewer_path=CASTLE_PATH,
            mode="capture",
            validate=True,
            viewpoint="GameStart",
            width=800,
            height=600,
            anti_alias=2,
            analyzer_module=x3d_analyzer,
            run_id="freecad-castle-capture",
            document=doc.Name,
        )
        live_manifest = capture_x3d.parent / castle_manifest["outputs"]["manifest"]
        deadline = time.monotonic() + 90.0
        final_manifest = castle_manifest
        while time.monotonic() < deadline:
            process_events()
            if live_manifest.is_file():
                final_manifest = json.loads(live_manifest.read_text(encoding="utf-8"))
                status = str((final_manifest.get("castle") or {}).get("status", ""))
                if status in {"completed", "failed"}:
                    break
            time.sleep(0.2)
        castle_info = final_manifest.get("castle") or {}
        screenshot_value = str((final_manifest.get("outputs") or {}).get("screenshot", ""))
        screenshot_path = capture_x3d.parent / screenshot_value
        castle_result.update(
            {
                "status": castle_info.get("status"),
                "return_code": castle_info.get("return_code"),
                "screenshot": screenshot_path.is_file(),
                "validation": (final_manifest.get("validation") or {}).get("status"),
                "source": "one_click_quick_example_x3d",
            }
        )
        require(castle_info.get("status") == "completed", f"Castle capture failed: {castle_info}")
        require(screenshot_path.is_file(), "Castle did not create the requested screenshot")

    result["materials"] = {
        "single_and_multiple_selection": True,
        "custom_texture": True,
        "projections": projection_results,
        "physical_scale_mm": [1200.0, 180.0],
        "polished": True,
        "mirror": True,
        "fcstd_persistence": True,
        "x3d_reexport": True,
        "visible_status": True,
    }
    result["export_cache"] = {"reuse_unchanged": True, "invalidate_changed": True}
    result["diagnostic_read_only"] = True
    result["castle"] = castle_result
    panel.widget.deleteLater()
    cache_panel.widget.deleteLater()
    close_document(doc)


def run_smoke():
    result = {
        "status": "running",
        "freecad_version": FreeCAD.Version(),
        "gui_up": bool(FreeCAD.GuiUp),
    }
    try:
        require(FreeCAD.GuiUp, "FreeCAD GUI is not available")
        workbench_registration_checks(result)
        help_and_language_checks(result)
        quick_example_and_json_checks(result)
        one_click_x3d = one_click_quick_example_checks(result)
        material_export_and_diagnostic_checks(result, castle_x3d=one_click_x3d)
        result["status"] = "passed"
    except Exception as exc:
        result["status"] = "failed"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc()
    finally:
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True),
            encoding="utf-8",
        )
        FreeCAD.Console.PrintMessage(
            "[GAMEEXPORT][SMOKE] " + result["status"] + ": " + RESULT_PATH.name + "\n"
        )
        QtCore.QTimer.singleShot(100, close_freecad)


QtCore.QTimer.singleShot(0, run_smoke)
