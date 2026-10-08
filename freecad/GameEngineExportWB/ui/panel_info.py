"""Information and Help UI for Game Engine Export WB.

Name: ui/panel_info.py
Purpose: provide one generous help source for the panel Info tab and the standalone Help command.
Main behavior: selects Spanish or English from the active FreeCAD language preference and exposes read-only help text.
Modification notes: keep one source of help content; do not duplicate a second divergent manual in command code.
Version: 2026-08-22-castle-config-v1
Date and time: 2026-08-22 10:58 -06:00
"""

# Qt compatibility for FreeCAD 1.x (PySide6) and older builds.
def _ensure_qt_compat():
    import sys
    import types

    QtCore = QtGui = QtWidgets = None
    binding_name = None

    for candidate in ("PySide6", "PySide2", "PySide"):
        try:
            if candidate == "PySide":
                from PySide import QtCore as _QtCore, QtGui as _QtGui
                _QtWidgets = _QtGui
            else:
                module = __import__(candidate, fromlist=["QtCore", "QtGui", "QtWidgets"])
                _QtCore = module.QtCore
                _QtGui = module.QtGui
                _QtWidgets = module.QtWidgets
            QtCore, QtGui, QtWidgets = _QtCore, _QtGui, _QtWidgets
            binding_name = candidate
            break
        except Exception:
            continue

    if QtCore is None:
        return

    qtgui_compat = types.ModuleType("QtGui")
    qtgui_compat.__dict__.update(getattr(QtGui, "__dict__", {}))
    qtgui_compat.__dict__.update(getattr(QtWidgets, "__dict__", {}))

    qtsvg_compat = None
    for module_name in ("QtSvg", "QtSvgWidgets"):
        try:
            module = __import__(binding_name, fromlist=[module_name])
            qt_module = getattr(module, module_name)
        except Exception:
            continue
        if qtsvg_compat is None:
            qtsvg_compat = types.ModuleType("QtSvg")
        qtsvg_compat.__dict__.update(getattr(qt_module, "__dict__", {}))

    qtuitools_compat = None
    try:
        module = __import__(binding_name, fromlist=["QtUiTools"])
        qtuitools_compat = module.QtUiTools
    except Exception:
        pass

    for package_name in ("PySide2", "PySide"):
        package = sys.modules.get(package_name)
        if package is None:
            package = types.ModuleType(package_name)
            sys.modules[package_name] = package
        package.QtCore = QtCore
        package.QtGui = qtgui_compat
        package.QtWidgets = QtWidgets
        sys.modules[package_name + ".QtCore"] = QtCore
        sys.modules[package_name + ".QtGui"] = qtgui_compat
        sys.modules[package_name + ".QtWidgets"] = QtWidgets
        if qtsvg_compat is not None:
            package.QtSvg = qtsvg_compat
            sys.modules[package_name + ".QtSvg"] = qtsvg_compat
        if qtuitools_compat is not None:
            package.QtUiTools = qtuitools_compat
            sys.modules[package_name + ".QtUiTools"] = qtuitools_compat


_ensure_qt_compat()

from PySide import QtCore, QtGui

import os

from .. import i18n
from ..core import json_ai


HELP_TEXT_ES = """GAME ENGINE EXPORT WB - AYUDA

1. PROPOSITO
Game Engine Export WB es un Workbench complementario para FreeCAD. Su objetivo es preparar y exportar modelos CAD/BIM a X3D y abrirlos en Castle Model Viewer / Castle Game Engine para visualizacion interactiva, navegacion, iluminacion, materiales, diagnostico y pruebas.

FreeCAD sigue siendo la fuente principal del modelo. El Workbench no pretende reemplazar FreeCAD ni convertirlo en un motor de juego. Castle se utiliza como visor 3D interactivo y como entorno para probar las capacidades visuales del X3D exportado.

Flujo general:
FreeCAD -> GameEngineExportWB -> X3D -> Castle Model Viewer

2. INICIO RAPIDO
1) Active Game Engine Export WB.
2) Si desea una prueba controlada, use Ejemplo rapido.
3) Genere Casa, Oficina, Fotometria o Laberinto.
4) Revise o cree GameStart.
5) Use Exportar y abrir Castle.
6) Navegue la escena en Castle.
7) Si aparece un problema, use Analizar X3D o Diagnostico Castle.

3. EJEMPLOS RAPIDOS
Casa y Oficina crean pequenas escenas arquitectonicas con muros, aberturas, piso y contexto JSON. Fotometria crea dos recintos de prueba con luminarias y accesos. Laberinto crea un recorrido tipo Doom para probar navegacion y visibilidad. Aleatorio selecciona uno de los tipos arquitectonicos disponibles.

El Laberinto permite incluir o quitar el cielo/techo. Su piso sobresale 1000 mm alrededor de las paredes como acera perimetral y existe suelo exterior separado para evitar superficies coplanares. GameStart se coloca frente a la entrada principal y orientado hacia el recorrido.

4. GAMESTART
GameStart define la ubicacion y orientacion inicial de la camara X3D. En los ejemplos debe quedar fuera de la puerta o acceso principal y mirando hacia el interior. La altura visual se maneja con HeightOffset, por lo que el marcador puede permanecer sobre la cota del piso.

5. EXPORTACION X3D
El exportador transforma la escena de FreeCAD a X3D, aplica la conversion de unidades y el cambio de eje necesario para Castle, inserta Viewpoint desde GameStart y puede exportar luces y ajustes visuales. El archivo X3D no debe sustituir el modelo FreeCAD como fuente de verdad.

6. ILUMINACION
El Workbench puede preparar PointLight, SpotLight y DirectionalLight a partir de objetos y propiedades de FreeCAD. Existen perfiles de iluminacion para comparar resultados. Algunos perfiles son experimentales y buscan facilitar la evaluacion visual, no sustituir un calculo luminotecnico formal.

7. MATERIALES Y TEXTURAS
La pestana Texturas permite seleccionar uno o varios objetos de FreeCAD, tomar la seleccion y guardar un acabado directamente como propiedades del objeto. La asignacion se conserva en el FCStd cuando el documento se guarda y vuelve a aplicarse en exportaciones posteriores. El sistema no reemplaza ni borra el Material nativo de FreeCAD: actua como una capa especifica de GameEngineExport cuando hace falta una representacion X3D/Castle.

La biblioteca de demostracion incluye ceramica/porcelanato, madera, concreto, piedra, ladrillo/bloque, panel de cielo y metal cepillado. Tambien se puede seleccionar un archivo PNG/JPG/WebP personalizado. Para evitar texturas estiradas se puede usar proyeccion UV Automatica, XY, XZ o YZ y definir el tamano fisico de repeticion en milimetros.

8. ESPEJO Y SUPERFICIES REFLECTANTES
Se distinguen dos efectos. Espejo real usa la extension de Castle basada en RenderedTexture + ViewpointMirror + TextureCoordinateGenerator MIRROR-PLANE y debe aplicarse preferiblemente a superficies aproximadamente planas. El parametro de resolucion permite equilibrar calidad y rendimiento.

Pulido / reflectante conserva el material o textura y aumenta el componente especular y el brillo. Es adecuado para porcelanato, pisos pulidos y metales. Esta primera implementacion no pretende reemplazar un material PBR completo ni una reflexion ambiental fisicamente correcta. Los efectos deben considerarse experimentales hasta verificarlos visualmente en Castle Model Viewer.

9. CASTLE MODEL VIEWER
Castle Model Viewer permite inspeccionar el X3D de forma interactiva. Desde FreeCAD puede configurarse la ruta del visor y lanzar el archivo exportado. Si la ruta no existe o deja de ser valida, Ejecutar en Castle abre automaticamente un selector para ubicar el ejecutable y guarda la seleccion. La ruta tambien puede cambiarse en Game Engine Export > Configuracion > Castle Engine > Ejecutable. El visor tambien permite probar opciones de iluminacion, sombreado y rendimiento sin alterar el modelo original.

10. DIAGNOSTICO CASTLE
Diagnostico Castle analiza el X3D, puede ejecutar castle-model-converter --validate, recopila informacion de geometria, luces y registros y guarda resultados en una carpeta _castle_debug junto al X3D. El stdout/stderr del visor se conserva separado del registro nativo de Castle para no perder informacion. En modos interactivo/captura el manifiesto comienza como started y se actualiza a completed o failed cuando Castle termina; en captura tambien registra si la imagen solicitada realmente existe. El diagnostico debe ser de solo lectura respecto al X3D fuente.

11. PROBLEMAS FRECUENTES
- Castle no abre: use Ejecutar en Castle para volver a seleccionar el ejecutable o cambielo en Configuracion > Castle Engine > Ejecutable.
- La escena aparece oscura: revise luces, perfiles, materiales y limites de luces por objeto.
- Los colores cambian: compare Material de FreeCAD, propiedades X3D y ajustes del visor.
- La textura no aparece: revise ruta, objeto destino, UV y archivos copiados a assets.
- La escena es lenta: use Analizar X3D para localizar geometria excesiva o muchas luces locales.
- GameStart no queda bien: revise que exista un acceso principal reconocible y que el marcador quede fuera de la geometria.

12. ESTADO DEL PROYECTO
Funcional o utilizable: exportacion X3D, lanzamiento de Castle, Quick Examples, GameStart, luces, perfiles, analisis X3D y diagnostico Castle.
En depuracion/experimental: materiales avanzados/PBR, espejo Castle, superficies pulidas, sombras, acabado arquitectonico y diagnostico visual inteligente. La asignacion de texturas a objetos seleccionados ya esta implementada, pendiente de validacion amplia en modelos reales.

13. PARA DESARROLLADORES
La arquitectura preferida es: nucleo reutilizable -> adaptador FreeCAD -> comando/boton -> macro pequena -> futuro MCP. Los nucleos no triviales deben evitar depender de FreeCADGui o Qt y devolver datos compatibles con JSON cuando sea razonable.

14. ORIGEN
El Workbench surgio de necesidades reales de mantenimiento y remodelacion de edificios y del interes por utilizar software libre. El desarrollo se apoya en FreeCAD, Castle y herramientas de asistencia de IA, con verificacion humana y pruebas en los programas reales.

15. SOPORTE Y TRAZABILIDAD
Use la consola de reportes de FreeCAD para mensajes [GAMEEXPORT]. Mantenga los archivos del Workbench y su documentacion sincronizados con la fuente vigente del proyecto. Las funciones experimentales deben identificarse como tales y no reemplazar una version funcional sin pruebas.
"""

HELP_TEXT_EN = """GAME ENGINE EXPORT WB - HELP

1. PURPOSE
Game Engine Export WB is a complementary FreeCAD Workbench. It prepares and exports CAD/BIM models to X3D and opens them in Castle Model Viewer / Castle Game Engine for interactive visualization, navigation, lighting, materials, diagnostics and testing.

FreeCAD remains the primary source of the model. The Workbench does not attempt to replace FreeCAD or turn it into a game engine. Castle is used as an interactive 3D viewer and as an environment to test the visual capabilities of the exported X3D.

General workflow:
FreeCAD -> GameEngineExportWB -> X3D -> Castle Model Viewer

2. QUICK START
1) Activate Game Engine Export WB.
2) For a controlled test, use Quick Example.
3) Generate House, Office, Photometric or Maze.
4) Review or create GameStart.
5) Use Export and launch Castle.
6) Navigate the scene in Castle.
7) If something looks wrong, use Analyze X3D or Castle Diagnostics.

3. QUICK EXAMPLES
House and Office create small architectural scenes with walls, openings, a floor and JSON context. Photometric creates two test rooms with luminaires and access openings. Maze creates a Doom-like path for navigation and visibility tests. Random selects one of the available architectural types.

Maze can include or omit its ceiling. Its floor extends 1000 mm beyond the outer walls as a perimeter sidewalk, and separate exterior ground avoids coplanar surfaces. GameStart is placed in front of the main entrance and faces the path inside.

4. GAMESTART
GameStart defines the initial X3D camera location and orientation. In examples it should be outside the main door or entrance and face inward. Eye height is handled by HeightOffset, so the marker itself may remain at floor elevation.

5. X3D EXPORT
The exporter converts the FreeCAD scene to X3D, applies unit conversion and the axis transformation required by Castle, inserts a Viewpoint from GameStart and can export lights and visual settings. The X3D file should not replace the FreeCAD model as the source of truth.

6. LIGHTING
The Workbench can prepare PointLight, SpotLight and DirectionalLight information from FreeCAD objects and properties. Lighting profiles are available to compare results. Some profiles are experimental visual aids and are not a substitute for a formal lighting calculation.

7. MATERIALS AND TEXTURES
The Textures tab can capture one or more selected FreeCAD objects and store a finish directly as object properties. The assignment is preserved in the FCStd when the document is saved and is reused on later exports. The system does not replace or erase FreeCAD native Material data; it acts as a GameEngineExport-specific layer when an X3D/Castle representation is required.

The lightweight demonstration library includes ceramic/porcelain, wood, concrete, stone, brick/block, ceiling panel and brushed metal. A custom PNG/JPG/WebP file can also be selected. UV projection can be Automatic, XY, XZ or YZ, and physical tile size is expressed in millimeters to reduce stretching.

8. MIRROR AND REFLECTIVE SURFACES
The two effects are intentionally different. True mirror uses Castle's RenderedTexture + ViewpointMirror + MIRROR-PLANE TextureCoordinateGenerator extension and should preferably be assigned to approximately planar surfaces. Mirror resolution balances quality and performance.

Polished / reflective preserves the material or texture while increasing specular response and shininess. It is intended for polished tile, floors and metals. This first implementation is not a complete PBR material or physically accurate environment reflection. Both effects remain experimental until visually verified in Castle Model Viewer.

9. CASTLE MODEL VIEWER
Castle Model Viewer lets you inspect X3D interactively. FreeCAD can store the viewer path and launch the exported file. If the path is missing or no longer valid, Run in Castle automatically opens a file picker and saves the selected executable. The path can also be changed under Game Engine Export > Configuration > Castle Engine > Executable. The viewer is also useful for testing lighting, shading and performance options without altering the source model.

10. CASTLE DIAGNOSTICS
Castle Diagnostics analyzes X3D, can run castle-model-converter --validate, collects geometry/light/log information and stores results in a _castle_debug folder next to the X3D. Viewer stdout/stderr is kept separate from the native Castle log so neither source overwrites the other. In interactive/capture modes the manifest starts as started and is updated to completed or failed when Castle exits; capture mode also records whether the requested screenshot actually exists. Diagnostics must remain read-only with respect to the source X3D.

11. COMMON PROBLEMS
- Castle does not open: use Run in Castle to select the executable again, or change it under Configuration > Castle Engine > Executable.
- The scene is too dark: review lights, profiles, materials and per-shape light limits.
- Colors look different: compare FreeCAD Material, X3D properties and viewer settings.
- A texture is missing: check file path, target object, UV mapping and copied asset files.
- The scene is slow: use Analyze X3D to find excessive geometry or many local lights.
- GameStart is misplaced: confirm a recognizable main entrance and keep the marker outside geometry.

12. PROJECT STATUS
Functional or usable: X3D export, Castle launch, Quick Examples, GameStart, lights, profiles, X3D analysis and Castle diagnostics.
Under refinement/experimental: advanced/PBR materials, Castle mirrors, polished surfaces, shadows, architectural finishes and intelligent visual diagnostics. Texture assignment to selected objects is implemented and awaits broader validation on real models.

13. FOR DEVELOPERS
Preferred architecture: reusable core -> FreeCAD adapter -> command/button -> small macro -> future MCP. Non-trivial cores should avoid FreeCADGui/Qt dependencies and return JSON-compatible data when reasonable.

14. ORIGIN
The Workbench grew from real building maintenance and renovation needs and an interest in free and open-source software. Development uses FreeCAD, Castle and AI development assistants, with human review and testing in the real applications.

15. SUPPORT AND TRACEABILITY
Use the FreeCAD report console for [GAMEEXPORT] messages. Keep Workbench files and documentation synchronized with the current project source. Experimental functions must be identified as such and must not replace a working version without testing.
"""


def get_ui_language() -> str:
    """Return the compact language code from the shared Workbench i18n helper."""
    return i18n.current_language()


def get_info_text(language=None) -> str:
    lang = str(language or get_ui_language()).lower()
    return HELP_TEXT_ES if lang.startswith("es") else HELP_TEXT_EN


_ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "resources", "icons"))
HELP_ICON_PATH = os.path.join(_ICON_DIR, "gameexport_help.svg").replace(os.sep, "/")
TIP_PARAM_GROUP = "User parameter:Plugins/GameEngineExportWB/Help"

_AI_CONTEXT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "AI_CONTEXT.md")
)


def get_ai_context_text():
    """Return the stable Workbench AI context stored beside the package root."""
    try:
        with open(_AI_CONTEXT_PATH, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except Exception:
        return ""


def build_workbench_ai_package():
    """Build a copy/paste package for an AI without runtime-specific paths."""
    context = get_ai_context_text()
    if not context:
        return ""
    return (
        i18n.bi(
            "Estoy trabajando con GameEngineExportWB para FreeCAD 1.1.3. "
            "Lea el siguiente contexto tecnico antes de proponer cambios. "
            "Conserve el comportamiento funcional, diagnostique antes de modificar "
            "y no introduzca rutas personales ni datos de organizaciones o clientes.",
            "I am working with GameEngineExportWB for FreeCAD 1.1.3. "
            "Read the following technical context before proposing changes. "
            "Preserve working behavior, diagnose before modifying, and do not add "
            "personal paths or organization/client data.",
        )
        + "\n\n--- GAMEENGINEEXPORTWB AI CONTEXT ---\n\n"
        + context
        + "\n\n--- END GAMEENGINEEXPORTWB AI CONTEXT ---"
    )


def _icon_path(filename):
    return os.path.join(_ICON_DIR, filename).replace(os.sep, "/")


def _main_window():
    try:
        import FreeCADGui
        return FreeCADGui.getMainWindow()
    except Exception:
        return None


def _make_icon_label(filename, size=32):
    label = QtGui.QLabel()
    pixmap = QtGui.QPixmap(_icon_path(filename))
    if not pixmap.isNull():
        try:
            mode = QtCore.Qt.KeepAspectRatio
            transform = QtCore.Qt.SmoothTransformation
            pixmap = pixmap.scaled(size, size, mode, transform)
        except Exception:
            pixmap = pixmap.scaled(size, size)
        label.setPixmap(pixmap)
    label.setFixedSize(size + 8, size + 8)
    label.setAlignment(QtCore.Qt.AlignCenter)
    return label


def _make_step_row(icon_name, title, description, icon_size=48):
    row = QtGui.QWidget()
    layout = QtGui.QHBoxLayout(row)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.addWidget(_make_icon_label(icon_name, icon_size), 0)
    text_box = QtGui.QVBoxLayout()
    title_label = QtGui.QLabel(title)
    font = title_label.font()
    font.setBold(True)
    font.setPointSize(max(font.pointSize(), 10))
    title_label.setFont(font)
    desc_label = QtGui.QLabel(description)
    desc_label.setWordWrap(True)
    text_box.addWidget(title_label)
    text_box.addWidget(desc_label)
    layout.addLayout(text_box, 1)
    return row


def build_info_tab():
    """Return the Information QWidget using the current FreeCAD language."""
    lang = get_ui_language()
    tab = QtGui.QWidget()
    layout = QtGui.QVBoxLayout(tab)

    text = QtGui.QPlainTextEdit()
    text.setPlainText(get_info_text(lang))
    text.setReadOnly(True)
    layout.addWidget(text)

    btn_copy = QtGui.QPushButton(i18n.tr("Copy"))
    btn_copy.setToolTip(i18n.tr("Copy the full help text."))
    layout.addWidget(btn_copy)
    btn_copy.clicked.connect(lambda: _copy_to_clipboard(text.toPlainText()))
    return tab


def build_first_steps_tab():
    """Build the practical two-button introduction used by the Help dialog."""
    tab = QtGui.QWidget()
    layout = QtGui.QVBoxLayout(tab)

    title = QtGui.QLabel(i18n.bi("Para empezar solo necesita dos botones", "You only need two buttons to get started"))
    title_font = title.font()
    title_font.setBold(True)
    title_font.setPointSize(max(title_font.pointSize() + 3, 13))
    title.setFont(title_font)
    title.setWordWrap(True)
    layout.addWidget(title)

    intro = QtGui.QLabel(i18n.bi(
        "No necesita configurar todo el Workbench antes de probarlo. Cree una escena de ejemplo y ejecutela en Castle. Eso es suficiente para ver el flujo completo.",
        "You do not need to configure the whole Workbench before trying it. Create an example scene and run it in Castle. That is enough to see the complete workflow.",
    ))
    intro.setWordWrap(True)
    layout.addWidget(intro)

    layout.addWidget(_make_step_row(
        "quick_example.svg",
        i18n.bi("1. Ejemplo rapido", "1. Quick Example"),
        i18n.bi("Crea automaticamente una casa, oficina, escena fotometrica o laberinto de prueba.", "Automatically creates a test house, office, photometric scene, or maze."),
    ))
    layout.addWidget(_make_step_row(
        "export_launch_x3d.svg",
        i18n.bi("2. Ejecutar en Castle", "2. Run in Castle"),
        i18n.bi("Exporta la escena cuando hace falta y abre el X3D en Castle Model Viewer.", "Exports the scene when needed and opens the X3D in Castle Model Viewer."),
    ))

    note = QtGui.QLabel(i18n.bi(
        "Despues puede explorar materiales, luces, GameStart, JSON/IA y herramientas de diagnostico.",
        "After that you can explore materials, lights, GameStart, JSON/AI, and diagnostic tools.",
    ))
    note.setWordWrap(True)
    layout.addWidget(note)

    btn_tips = QtGui.QPushButton(i18n.bi("Mostrar ventana de primeros pasos", "Show getting-started tips"))
    btn_tips.setIcon(QtGui.QIcon(HELP_ICON_PATH))
    btn_tips.clicked.connect(lambda: show_startup_tips(parent=_main_window(), force=True))
    layout.addWidget(btn_tips)
    layout.addStretch(1)
    return tab


def _button_help_entries():
    return [
        ("quick_example.svg", i18n.bi("Ejemplo rapido", "Quick Example"), i18n.bi("Crea una escena de prueba lista para usar. Es el primer boton recomendado para aprender el Workbench.", "Creates a ready-to-use test scene. This is the first recommended button for learning the Workbench.")),
        ("export_launch_x3d.svg", i18n.bi("Ejecutar en Castle", "Run in Castle"), i18n.bi("Flujo normal de un clic: exporta si el modelo cambio y abre Castle; si no cambio, reutiliza el X3D existente.", "Normal one-click flow: exports when the model changed and opens Castle; otherwise it reuses the existing X3D.")),
        ("gameexport.svg", i18n.bi("Exportar X3D / Panel principal", "Export X3D / Main panel"), i18n.bi("Abre el panel completo para escoger objetos, exportacion, materiales, texturas, GameStart y otras opciones.", "Opens the full panel for object selection, export, materials, textures, GameStart, and other options.")),
        ("add_light_properties.svg", i18n.bi("Agregar propiedades a luz", "Add light properties"), i18n.bi("Prepara una luminaria u objeto seleccionado con propiedades que el exportador puede convertir a luces X3D/Castle.", "Prepares a selected luminaire or object with properties the exporter can convert into X3D/Castle lights.")),
        ("bim_doors_windows.svg", i18n.bi("Puertas y ventanas BIM", "BIM doors and windows"), i18n.bi("Agrega puertas y ventanas BIM al ultimo Quick Example para probar aberturas y visualizacion.", "Adds BIM doors and windows to the latest Quick Example to test openings and visualization.")),
        ("quick_example_roof.svg", i18n.bi("Agregar techo", "Add Roof"), i18n.bi("Agrega un techo sencillo al ultimo Quick Example generado o importado desde JSON.", "Adds a simple roof to the latest Quick Example generated or imported from JSON.")),
        ("import_json_example.svg", i18n.bi("Importar JSON / IA", "Import JSON / AI"), i18n.bi("Puente manual con una IA: copie contexto + prompt, pida cambios en lenguaje natural, pegue el JSON devuelto y reconstruya el ejemplo.", "Manual bridge to an AI: copy context + prompt, request changes in natural language, paste the returned JSON, and rebuild the example.")),
        ("analyze_x3d.svg", i18n.bi("Analizar X3D", "Analyze X3D"), i18n.bi("Analiza geometria, tamano, luces y posibles problemas del X3D sin modificar el archivo fuente.", "Analyzes geometry, size, lights, and possible X3D issues without modifying the source file.")),
        ("castle_diagnostics.svg", i18n.bi("Diagnostico Castle", "Castle Diagnostics"), i18n.bi("Ejecuta una revision mas profunda: validacion, registros, manifiesto y captura cuando corresponde.", "Runs a deeper review: validation, logs, manifest, and capture when applicable.")),
        ("reload_workbench.svg", i18n.bi("Recargar Workbench", "Reload Workbench"), i18n.bi("Recarga modulos sin reiniciar FreeCAD. Es un comando de desarrollo disponible en el menu y no ocupa una barra de usuario normal.", "Reloads modules without restarting FreeCAD. It is a development command available from the menu and does not occupy a normal user toolbar.")),
        ("gameexport_help.svg", i18n.bi("Ayuda", "Help"), i18n.bi("Abre Primeros pasos, la explicacion de cada boton, el flujo IA/JSON y la Informacion tecnica.", "Opens Getting Started, button explanations, the AI/JSON workflow, and technical Information.")),
    ]


def build_buttons_tab():
    """Build a visual command reference using the same icons as the toolbar."""
    tab = QtGui.QWidget()
    outer = QtGui.QVBoxLayout(tab)
    intro = QtGui.QLabel(i18n.bi(
        "Identifique el boton por su icono. Los dos primeros son suficientes para comenzar; los demas amplian o diagnostican el flujo.",
        "Identify each button by its icon. The first two are enough to get started; the others extend or diagnose the workflow.",
    ))
    intro.setWordWrap(True)
    outer.addWidget(intro)

    scroll = QtGui.QScrollArea()
    scroll.setWidgetResizable(True)
    body = QtGui.QWidget()
    body_layout = QtGui.QVBoxLayout(body)
    for icon_name, title, description in _button_help_entries():
        body_layout.addWidget(_make_step_row(icon_name, title, description, icon_size=32))
    body_layout.addStretch(1)
    scroll.setWidget(body)
    outer.addWidget(scroll, 1)
    return tab


def _find_current_context_json():
    """Read the newest persisted Quick Example JSON from the active document."""
    try:
        import FreeCAD
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return ""
        objects = list(getattr(doc, "Objects", []) or [])
        for obj in reversed(objects):
            props = list(getattr(obj, "PropertiesList", []) or [])
            if "GEE_ContextJSON" in props:
                value = str(getattr(obj, "GEE_ContextJSON", "") or "").strip()
                if value:
                    return value
    except Exception:
        pass
    return ""


def build_ai_json_tab():
    """Build the manual copy/paste AI bridge help and prompt controls."""
    lang = get_ui_language()
    tab = QtGui.QWidget()
    layout = QtGui.QVBoxLayout(tab)

    intro = QtGui.QLabel(i18n.bi(
        "Hay dos contextos distintos: AI_CONTEXT.md explica el Workbench y como desarrollarlo; el JSON describe la escena concreta. El flujo JSON no requiere API: copie el contexto, pegelo en la IA, describa el cambio y pegue de vuelta el JSON resultante en Importar JSON.",
        "There are two different contexts: AI_CONTEXT.md explains the Workbench and how to develop it; JSON describes the concrete scene. The JSON workflow requires no API: copy the context, paste it into the AI, describe the change, and paste the resulting JSON back into Import JSON.",
    ))
    intro.setWordWrap(True)
    layout.addWidget(intro)

    steps = QtGui.QLabel(i18n.bi(
        "Flujo: 1) Genere un Ejemplo rapido. 2) Copie contexto para IA (prompt + JSON). 3) Peguelo en la IA y pida cambios. 4) Copie el JSON devuelto. 5) Use Importar JSON > Generar.",
        "Workflow: 1) Generate a Quick Example. 2) Copy AI context (prompt + JSON). 3) Paste it into the AI and request changes. 4) Copy the returned JSON. 5) Use Import JSON > Generate.",
    ))
    steps.setWordWrap(True)
    layout.addWidget(steps)

    prompt = QtGui.QPlainTextEdit()
    prompt.setReadOnly(True)
    prompt.setPlainText(json_ai.get_prompt_template(lang))
    prompt.setMinimumHeight(260)
    layout.addWidget(prompt, 1)

    buttons = QtGui.QHBoxLayout()
    btn_workbench_context = QtGui.QPushButton(
        i18n.bi(
            "Copiar contexto del Workbench para IA",
            "Copy Workbench context for AI",
        )
    )
    btn_workbench_context.setIcon(QtGui.QIcon(HELP_ICON_PATH))
    btn_prompt = QtGui.QPushButton(i18n.bi("Copiar prompt", "Copy prompt"))
    btn_package = QtGui.QPushButton(i18n.bi("Copiar prompt + JSON actual", "Copy prompt + current JSON"))
    buttons.addWidget(btn_workbench_context)
    buttons.addWidget(btn_prompt)
    buttons.addWidget(btn_package)
    buttons.addStretch(1)
    layout.addLayout(buttons)

    def _copy_workbench_context():
        package = build_workbench_ai_package()
        if package:
            _copy_to_clipboard(package)
            return
        QtGui.QMessageBox.warning(
            tab,
            i18n.bi("IA / JSON", "AI / JSON"),
            i18n.bi(
                "No se encontro AI_CONTEXT.md en la raiz del Workbench.",
                "AI_CONTEXT.md was not found in the Workbench root.",
            ),
        )

    btn_workbench_context.clicked.connect(_copy_workbench_context)
    btn_prompt.clicked.connect(lambda: _copy_to_clipboard(json_ai.get_prompt_template(lang)))

    def _copy_package():
        context = _find_current_context_json()
        _copy_to_clipboard(json_ai.build_ai_prompt(context, lang))
        if not context:
            QtGui.QMessageBox.information(
                tab,
                i18n.bi("IA / JSON", "AI / JSON"),
                i18n.bi("No se encontro un GEE_ContextJSON activo; se copio solamente el prompt.", "No active GEE_ContextJSON was found; only the prompt was copied."),
            )

    btn_package.clicked.connect(_copy_package)
    return tab


def build_help_dialog(parent=None):
    """Return the standalone Help dialog with practical and technical tabs."""
    dialog = QtGui.QDialog(parent or _main_window())
    dialog.setWindowTitle("Game Engine Export WB - " + i18n.tr("Help"))
    dialog.setWindowIcon(QtGui.QIcon(HELP_ICON_PATH))
    dialog.resize(980, 760)
    layout = QtGui.QVBoxLayout(dialog)

    tabs = QtGui.QTabWidget()
    tabs.addTab(build_first_steps_tab(), QtGui.QIcon(_icon_path("quick_example.svg")), i18n.bi("Primeros pasos", "Getting Started"))
    tabs.addTab(build_buttons_tab(), QtGui.QIcon(HELP_ICON_PATH), i18n.bi("Botones", "Buttons"))
    tabs.addTab(build_ai_json_tab(), QtGui.QIcon(_icon_path("import_json_example.svg")), i18n.bi("IA / JSON", "AI / JSON"))
    tabs.addTab(build_info_tab(), QtGui.QIcon(_icon_path("gameexport.svg")), i18n.bi("Informacion", "Information"))
    layout.addWidget(tabs, 1)

    buttons = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Close)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return dialog


def show_help_dialog(parent=None):
    dialog = build_help_dialog(parent)
    dialog.exec_()
    return dialog


def build_startup_tips_dialog(parent=None):
    """Build the compact first-use tips dialog."""
    dialog = QtGui.QDialog(parent or _main_window())
    dialog.setWindowTitle(i18n.bi("Game Engine Export - Primeros pasos", "Game Engine Export - Getting Started"))
    dialog.setWindowIcon(QtGui.QIcon(HELP_ICON_PATH))
    dialog.resize(620, 360)
    layout = QtGui.QVBoxLayout(dialog)

    title = QtGui.QLabel(i18n.bi("Para empezar solo use estos dos botones", "To get started, just use these two buttons"))
    font = title.font()
    font.setBold(True)
    font.setPointSize(max(font.pointSize() + 3, 13))
    title.setFont(font)
    title.setWordWrap(True)
    layout.addWidget(title)

    layout.addWidget(_make_step_row(
        "quick_example.svg",
        i18n.bi("1. Ejemplo rapido", "1. Quick Example"),
        i18n.bi("Crea una escena lista para probar.", "Creates a scene ready to test."),
        icon_size=48,
    ))
    layout.addWidget(_make_step_row(
        "export_launch_x3d.svg",
        i18n.bi("2. Ejecutar en Castle", "2. Run in Castle"),
        i18n.bi("Exporta cuando hace falta y abre la escena en Castle Model Viewer.", "Exports when needed and opens the scene in Castle Model Viewer."),
        icon_size=48,
    ))

    done = QtGui.QLabel(i18n.bi("Eso es suficiente para comenzar.", "That is enough to get started."))
    done_font = done.font()
    done_font.setBold(True)
    done.setFont(done_font)
    layout.addWidget(done)

    dont_show = QtGui.QCheckBox(i18n.bi("No volver a mostrar este mensaje", "Do not show this message again"))
    layout.addWidget(dont_show)

    buttons = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Close)
    btn_help = QtGui.QPushButton(i18n.tr("Help"))
    btn_help.setIcon(QtGui.QIcon(HELP_ICON_PATH))
    buttons.addButton(btn_help, QtGui.QDialogButtonBox.ActionRole)
    buttons.rejected.connect(dialog.reject)
    btn_help.clicked.connect(lambda: show_help_dialog(dialog))
    layout.addWidget(buttons)
    dialog._gee_dont_show = dont_show
    return dialog


def show_startup_tips(parent=None, force=False):
    """Show the getting-started dialog and persist the user's opt-out choice."""
    import FreeCAD
    params = FreeCAD.ParamGet(TIP_PARAM_GROUP)
    if not force and not params.GetBool("show_startup_tips", True):
        return None
    dialog = build_startup_tips_dialog(parent)
    dialog.exec_()
    if bool(dialog._gee_dont_show.isChecked()):
        params.SetBool("show_startup_tips", False)
        FreeCAD.Console.PrintMessage("[GAMEEXPORT] Getting-started tips disabled by user\n")
    return dialog


def maybe_show_startup_tips():
    """Show tips once per FreeCAD session unless the user disabled them persistently."""
    import FreeCAD
    if bool(getattr(FreeCAD, "_GEE_TipsShownThisSession", False)):
        return None
    setattr(FreeCAD, "_GEE_TipsShownThisSession", True)
    try:
        return show_startup_tips(parent=_main_window(), force=False)
    except Exception as exc:
        FreeCAD.Console.PrintWarning("[GAMEEXPORT] Could not show getting-started tips: %s\n" % exc)
        return None


def schedule_startup_tips(delay_ms=250):
    """Schedule first-use tips after Workbench activation so the main UI is ready."""
    try:
        QtCore.QTimer.singleShot(int(delay_ms), maybe_show_startup_tips)
    except Exception:
        maybe_show_startup_tips()


def _copy_to_clipboard(value):
    """Copy text to clipboard (best effort)."""
    clipboard = QtGui.QApplication.clipboard()
    clipboard.setText(value, QtGui.QClipboard.Clipboard)
    try:
        if bool(getattr(clipboard, "supportsSelection", lambda: False)()):
            clipboard.setText(value, QtGui.QClipboard.Selection)
    except Exception:
        pass
    FreeCAD = __import__("FreeCAD")
    FreeCAD.Console.PrintMessage("[GAMEEXPORT] Help/AI text copied\n")


__all__ = [
    "HELP_ICON_PATH",
    "build_ai_json_tab",
    "build_buttons_tab",
    "build_first_steps_tab",
    "build_help_dialog",
    "build_info_tab",
    "build_workbench_ai_package",
    "build_startup_tips_dialog",
    "get_ai_context_text",
    "get_info_text",
    "get_ui_language",
    "maybe_show_startup_tips",
    "schedule_startup_tips",
    "show_help_dialog",
    "show_startup_tips",
]
