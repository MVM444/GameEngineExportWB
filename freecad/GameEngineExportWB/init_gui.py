"""FreeCAD GUI entry point for GameEngineExportWB.

FreeCAD 1.1+ discovers this module through the shared ``freecad`` namespace.
Keep this adapter small and delegate Workbench registration to ``ui.workbench``.
"""

from .ui.workbench import register_workbench as _register_workbench

_register_workbench()
