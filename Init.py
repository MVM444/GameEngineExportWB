"""Application bootstrap for GameEngineExportWB.

FreeCAD executes ``Init.py`` as an application module, without a package
import context, and loads ``InitGui.py`` separately when the GUI is available.
The Workbench has no headless registration work. This file only makes the
package importable from a clean Addon installation; it does not import GUI
modules or register commands.
"""

import os
import sys


def _ensure_package_parent_on_sys_path(_os=os, _sys=sys):
    """Expose the parent of the Addon folder for package imports.

    FreeCAD 1.1 adds each module directory itself to ``sys.path`` before it
    executes ``Init.py`` and ``InitGui.py``. Python needs the directory above
    ``GameEngineExportWB`` in order to resolve imports such as
    ``GameEngineExportWB.core``. Discover that parent from FreeCAD's existing
    module path instead of assuming a user-specific installation location.
    """
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
