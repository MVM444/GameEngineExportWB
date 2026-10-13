# GameEngineExportWB translations

This directory contains Qt translation resources for the Workbench.

- Source language: English.
- Initial translation: Spanish (Costa Rica / generic Spanish UI).
- Runtime registration: `GameEngineExportWB/i18n.py` calls `FreeCADGui.addLanguagePath(...)` and `FreeCADGui.updateLocale()`.
- The `.ts` source should be compiled to `.qm` with Qt `lrelease` in the local FreeCAD/Codex environment.
- Until the `.qm` catalog is compiled, `i18n.py` contains a small Spanish fallback for migrated UI strings.
- Internal command names, JSON keys and saved identifiers must remain language-independent.

When new visible strings are added, route them through `i18n.tr(...)`, update this catalog, compile the `.qm`, and verify both English and Spanish in FreeCAD 1.1.3.
