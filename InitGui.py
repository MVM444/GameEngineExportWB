"""FreeCAD GUI entry point for GameEngineExportWB.

FreeCAD 1.1 executes this file inside its GUI loader function rather than as a
normal Python module. Keep this adapter small: expose the package parent, then
delegate Workbench registration to a regular package module whose globals have
normal Python semantics.
"""

import os
import sys


def _ensure_package_parent_on_sys_path(_os=os, _sys=sys):
    """Make package imports work when FreeCAD executes this file directly."""
    for entry in tuple(_sys.path):
        if not entry:
            continue
        candidate = _os.path.normpath(_os.path.abspath(entry))
        if _os.path.basename(candidate).lower() != "gameengineexportwb":
            continue
        if not (
            _os.path.isfile(_os.path.join(candidate, "__init__.py"))
            and _os.path.isfile(_os.path.join(candidate, "package.xml"))
        ):
            continue
        parent = _os.path.dirname(candidate)
        parent_key = _os.path.normcase(parent)
        existing = {
            _os.path.normcase(_os.path.normpath(_os.path.abspath(path)))
            for path in _sys.path
            if path
        }
        if parent_key not in existing:
            _sys.path.insert(0, parent)
        return


_ensure_package_parent_on_sys_path()

from GameEngineExportWB.ui.workbench import register_workbench as _register_workbench


_register_workbench()
