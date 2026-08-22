# AI_CONTEXT - GameEngineExportWB

**Purpose:** stable technical context for AI assistants that need to understand, diagnose, edit, or improve this Workbench.
**Target FreeCAD:** 1.1.3
**Version:** 2026-08-21-ai-context-v1
**Date and time:** 2026-08-21 08:24 -06:00

## 1. What this Workbench does

GameEngineExportWB prepares FreeCAD CAD/BIM scenes for interactive X3D visualization in Castle Model Viewer / Castle Game Engine. FreeCAD remains the model source of truth. The exported X3D is a visualization artifact, not a replacement for the FreeCAD document.

Primary flow:

`FreeCAD -> GameEngineExportWB -> X3D -> Castle Model Viewer`

The minimum learning flow is intentionally simple:

`Quick Example -> Run in Castle`

A new user should be able to understand the Workbench by trying those two commands first.

## 2. User-facing command groups

### Main toolbar

- Quick Example: creates a controlled architectural or navigation test scene.
- Run in Castle: exports only when required and opens/reuses the X3D in Castle.
- Export X3D / main panel: opens the complete export configuration panel.
- Help: opens Getting Started, Buttons, AI/JSON, and Information.

### Scene / AI toolbar

- Add Light Properties: prepares FreeCAD objects with GameEngineExport light metadata.
- Import JSON / AI: manual copy/paste bridge between an AI and a Quick Example scene.
- BIM Doors and Windows: adds BIM openings to the relevant example workflow.
- Add Roof: adds a simple roof to the Quick Example workflow.

### Diagnostics toolbar

- Analyze X3D: read-only structural analysis of an X3D file.
- Castle Diagnostics: deeper validation/log/capture workflow; source X3D must remain read-only.

Reload Workbench is a development command and is intentionally kept out of normal user toolbars.

## 3. Architecture to preserve

Preferred dependency direction:

`independent core -> FreeCAD adapter -> command/button -> small macro when needed -> future MCP`

Rules:

- Keep non-trivial core logic independent of FreeCADGui and Qt whenever practical.
- Prefer JSON-compatible input/output data for reusable functions.
- Keep UI and FreeCAD transaction code near adapters/commands, not in reusable algorithms.
- Diagnose before modifying. Read-only diagnostics are the default.
- Use dry_run and FreeCAD transactions when a change can affect documents.
- Preserve useful `[GAMEEXPORT]` report-console messages.
- Never replace a working implementation without preserving its functional behavior.
- Every important module should retain a header with name, purpose, main behavior, modification notes, version, date, and time.

## 4. Important package areas

- `Init.py`, `InitGui.py`: FreeCAD Workbench bootstrap and command/toolbars registration.
- `commands/`: thin FreeCAD command wrappers.
- `core/`: reusable logic such as export, GameStart, lights, materials, JSON/AI helpers, persistence, and diagnostics.
- `ui/`: TaskPanels, Help/Information, output defaults, and GUI-specific behavior.
- `resources/icons/`: command and Workbench SVG icons.
- `resources/textures/`: small built-in demonstration textures.
- `translations/`: FreeCAD/Qt localization sources.
- `macros/`: runtime macros still used by some commands; do not remove them merely because the project is becoming an Addon.
- `examples/`: example data/assets.
- `tests/`: automated QA; not necessarily required at runtime.
- `README.md`: user/developer overview.
- `TAREA_ACTUAL.md`, `ESTADO_PROYECTO.md`, `RESULTADO_CODEX.md`: task coordination and traceability.

## 5. GameStart

GameStart defines the initial exported X3D viewpoint. Quick Examples should place it outside the main entrance and orient it inward. Eye height is handled separately from the marker floor position. Axis conversion must remain consistent with the X3D export transformation.

## 6. Lighting

The Workbench can export PointLight, SpotLight, and DirectionalLight information from FreeCAD objects/properties. Light-property tools and automatic luminaire detection are complementary. Lighting profiles are visualization aids and are not a substitute for formal lighting calculations.

## 7. Materials, textures, polished surfaces, and mirrors

GameEngineExport-specific material properties are stored as a non-destructive layer and must not erase native FreeCAD Material information. Persisted properties currently use the `GEE_` prefix, including material mode, texture selection/path/projection/tile size, reflectivity, and mirror size.

Texture mode supports built-in demonstration textures and custom image files. UV mapping can use Auto, XY, XZ, or YZ projection with physical tile dimensions in millimeters.

Polished mode is a specular/shininess approximation, not complete PBR or physically correct environment reflection.

True Mirror uses Castle extensions based on RenderedTexture, ViewpointMirror, and MIRROR-PLANE texture coordinate generation, and should be applied mainly to approximately planar surfaces.

## 8. JSON and AI workflow

There are two different kinds of AI context:

1. `AI_CONTEXT.md` explains the Workbench itself and how to safely modify it.
2. `GEE_ContextJSON` describes a concrete Quick Example scene that an AI can edit.

The manual scene workflow requires no API:

1. Create a Quick Example.
2. Copy prompt + current JSON.
3. Paste into an AI and request scene changes in natural language.
4. Require the AI to return valid JSON only.
5. Paste that JSON into Import JSON / AI.
6. Generate the updated FreeCAD example.

The pure JSON must remain separate from the human-readable prompt so structured data stays machine-safe.

## 9. Help and onboarding

Help has four tabs:

- Getting Started: teaches the two-button entry flow.
- Buttons: icon + concise purpose for each command.
- AI / JSON: scene prompt tools plus a button that copies this Workbench context for an AI.
- Information: the same technical information source reused by the main panel.

A compact startup Tips dialog may be disabled with a persistent FreeCAD ParamGet preference and must remain recoverable from Help.

## 10. Diagnostics and logging

Diagnostics should preserve traceability while avoiding unnecessary disclosure. Prefer module names, object names, relative package references, and generated output names over absolute installation paths in normal report-console messages.

Absolute external paths may be necessary internally for file access, but they should not be hardcoded into source, examples, documentation, defaults, or committed logs.

## 11. Privacy and portability

This Workbench is intended to be portable and distributable. Do not place any of the following in source code, documentation, examples, default configuration, committed diagnostics, or AI context:

- employer or organization names;
- client names or project-site names unless an example is intentionally public and generic;
- usernames, email addresses, workstation names, internal network shares, or organization-specific directories;
- personal Google Drive/OneDrive paths or other machine-specific absolute paths;
- confidential document data copied from real projects.

Runtime-selected external files may naturally have absolute paths in memory. Avoid echoing full paths to normal logs when a basename, module name, relative package path, or redacted path is sufficient.

Quick Examples must not silently inherit an external legacy ground-texture preference from another document when the configured target object is absent. In that case the preference should be ignored for the example export rather than guessed onto unrelated geometry.

## 12. Addon portability

The Workbench should be installable from a Git repository through FreeCAD Addon Manager custom repositories before any official-catalog publication is considered. Runtime loading must not depend on a particular development folder. Resources must resolve relative to the installed Workbench. Castle is an optional external application and its absence must not prevent the Workbench itself from loading.

## 13. Before editing

An AI or developer should:

1. Read the repository/project instructions first.
2. Read this `AI_CONTEXT.md`.
3. Read the current task/status files when available.
4. Inspect the current implementation and existing tests before proposing parallel functionality.
5. Research whether FreeCAD, Castle, an existing Workbench, Addon, macro, or plugin already provides the needed function before creating a new implementation.
6. Reuse or extend existing behavior when possible.
7. Make the smallest coherent change that preserves working features.

## 14. Minimum validation after changes

When applicable:

- run Python syntax/compile checks;
- run pure core tests;
- validate `package.xml`;
- test Quick Example;
- test Run in Castle;
- test Help and startup Tips;
- test AI/JSON copy-paste flow;
- test materials/textures and material-status UI;
- test Analyze X3D and Castle Diagnostics;
- test the real Workbench in FreeCAD 1.1.3 when behavior depends on FreeCAD/GUI/runtime paths.

Do not claim real-FreeCAD behavior is validated when only pure Python tests were executed.

## 15. Known areas still under refinement

- broader native FreeCAD Material integration;
- PBR/environment reflection;
- mirror behavior on complex/multi-shape objects;
- compiled translation `.qm` validation;
- large-model performance/stress testing;
- clean Addon install/update/uninstall/reinstall testing;
- wider real-project validation of material and Castle diagnostic workflows.

## 16. Modification principle

The Workbench should become easier to use without hiding its diagnostic depth. Keep the normal workflow simple, keep advanced tools grouped by purpose, and keep the internal architecture reusable for future automation/MCP integration.
