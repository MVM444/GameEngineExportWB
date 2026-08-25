# Game Engine Export WB

## Resumen / Summary

**Espanol:** Game Engine Export WB es un Workbench complementario para FreeCAD que prepara y exporta escenas CAD/BIM a X3D y las abre en Castle Model Viewer / Castle Game Engine para visualizacion interactiva, navegacion, iluminacion, materiales, diagnostico y pruebas. FreeCAD permanece como fuente principal del modelo.

**English:** Game Engine Export WB is a complementary FreeCAD Workbench that prepares and exports CAD/BIM scenes to X3D and opens them in Castle Model Viewer / Castle Game Engine for interactive visualization, navigation, lighting, materials, diagnostics and testing. FreeCAD remains the primary source of the model.

Flujo principal / Main workflow:

```text
FreeCAD -> GameEngineExportWB -> X3D -> Castle Model Viewer
```

## Estado actual / Current status

Version publica actual `0.2.1` (2026-08-22), disponible para instalacion desde el repositorio publico como Addon personalizado de FreeCAD. Ya existen exportacion X3D, lanzamiento de Castle, Quick Examples, GameStart, luces, perfiles visuales, analisis X3D, diagnostico Castle y ayuda integrada.

Current public version `0.2.1` (2026-08-22), available from the public repository as a custom FreeCAD Addon. X3D export, Castle launch, Quick Examples, GameStart, lights, visual profiles, X3D analysis, Castle diagnostics and integrated help are already available.

La asignacion general de materiales/texturas por objeto ya esta implementada en fase experimental. Espejo, reflexiones y diagnostico visual inteligente requieren validacion adicional en Castle y modelos reales.

## Idiomas / Languages

La interfaz se esta migrando a un esquema bilingue real Espanol/Ingles usando el mecanismo de traduccion de FreeCAD/Qt. Los identificadores internos, comandos, claves JSON y preferencias permanecen independientes del idioma. El ejemplo rapido y la ayuda ya usan esta infraestructura; el resto de la interfaz se migra progresivamente sin cambiar la logica funcional.

The UI is being migrated to true Spanish/English localization using FreeCAD/Qt translation mechanisms. Internal identifiers, command names, JSON keys and preferences remain language-independent. Quick Example and Help already use this infrastructure; the rest of the UI is being migrated progressively without changing functional logic.

## Instalacion / Installation

El repositorio publico dedicado es `https://github.com/MVM444/GameEngineExportWB` y su rama principal es `main`. La raiz del repositorio contiene directamente los archivos del Workbench.

The dedicated public repository is `https://github.com/MVM444/GameEngineExportWB`, with `main` as its default branch. The repository root directly contains the Workbench files.

### Espanol

1. Abra **Edit > Preferences > Addon Manager > Addon Manager Options** en FreeCAD 1.1.3.
2. En **Custom Repositories**, agregue `https://github.com/MVM444/GameEngineExportWB` y establezca la rama exactamente como `main`.
3. Aplique los cambios y cierre Preferencias.
4. Abra **Tools > Addon Manager**.
5. Busque e instale **GameEngineExportWB**.
6. Reinicie FreeCAD y seleccione **Game Engine Export WB** desde el selector de Workbenches.

### English

1. Open **Edit > Preferences > Addon Manager > Addon Manager Options** in FreeCAD 1.1.3.
2. Under **Custom Repositories**, add `https://github.com/MVM444/GameEngineExportWB` and set the branch exactly to `main`.
3. Apply the changes and close Preferences.
4. Open **Tools > Addon Manager**.
5. Find and install **GameEngineExportWB**.
6. Restart FreeCAD and select **Game Engine Export WB** from the Workbench selector.

Addon Manager administra la instalacion y las actualizaciones desde ese repositorio; no es necesario copiar manualmente recursos a `Mod`. Castle Model Viewer es una dependencia externa opcional: su ausencia no impide cargar el Workbench.

Addon Manager manages installation and updates from that repository; manually copying resources into `Mod` is unnecessary. Castle Model Viewer is an optional external dependency: its absence does not prevent the Workbench from loading.

## Abrir el proyecto en Visual Studio Code

1. Abre Visual Studio Code y elige **File > Open Folder**.
2. Selecciona la carpeta raiz `GameEngineExportWB`.
3. Cuando el editor termine de indexar, podras navegar por los subdirectorios `core`, `ui`, `commands` y `resources`.
4. Si deseas conservar notas de las sesiones, utiliza el archivo `notes/GameEngineExportWB_chat.md` descrito mas adelante.

## Aplicar cambios en Visual Studio Code

1. Abre la misma carpeta del repositorio en Visual Studio Code.
2. En la vista **Source Control** revisa los cambios pendientes y usa **Pull** para traer la ultima version.
3. Si trabajas dentro del monorepositorio de desarrollo, puedes usar su loader externo para recargar el Workbench. Ese loader no forma parte del Addon ni es una dependencia de runtime.
4. Tambien puedes usar **Recargar Workbench** desde el menu del propio Workbench.
5. Si modificas archivos, confirma en el panel de Source Control que los cambios se hayan guardado y versionado antes de probar en FreeCAD.

## Cargar el workbench en FreeCAD

1. Instala o enlaza la carpeta completa bajo el nombre `GameEngineExportWB` en el directorio de modulos de usuario.
2. Reinicia FreeCAD para probar el mismo ciclo de carga que usara el Addon.
3. Desde la barra superior elige el workbench **Game Engine Export WB**.
4. Abre **Exportar X3D** para mostrar el TaskPanel.
5. Veras mensajes `[GAMEEXPORT]` en la consola de reportes confirmando la carga.

## Uso rapido

Abre el comando **GameEngineExport Open** para mostrar el panel principal. Desde ahi puedes elegir la raiz de la escena, listas de objetos, marcador GameStart, iluminacion, cielo de Castle Viewer, materiales X3D y carpeta de salida.

El comando **Quick Example** (`GameEngineExport_QuickExample_*`) genera Casa, Oficina, Fotometria, Laberinto o un tipo Aleatorio. La etiqueta visible se presenta en el idioma activo de FreeCAD. Sirve para probar el flujo completo sin preparar un modelo manualmente. Los ejemplos arquitectonicos conservan sketches, `Arch Wall`, aberturas, terreno y piso; Fotometria agrega una escena controlada de iluminacion; Laberinto agrega un recorrido reproducible para navegacion.

Por convencion, `GameStart` se coloca frente al acceso principal y mirando hacia el interior cuando el acceso puede identificarse. En el Laberinto, el piso incluye una acera perimetral de `1000 mm` y existe suelo exterior a otra cota para evitar superficies coplanares y z-fighting. El cielo/techo del Laberinto sigue siendo opcional.

Los sketches quedan como fuente parametrica:

- `GEE_SK_ExteriorWalls`
- `GEE_SK_InteriorWalls`
- `GEE_SK_DoorOpenings`
- `GEE_SK_WindowOpenings`

Las paredes se crean con `Arch.makeWall(...)` desde esos sketches. Los buques se crean como cutters parametricos enlazados a los sketches de puertas y ventanas, y se asignan como `Subtractions` de los muros.

El grupo `SiteAndFloors` incluye:

- `GEE_Terrain_Irregular`: terreno triangulado no plano para probar exportacion de suelo, sombras y textura.
- `GEE_Building_Floor_Slab`: losa/piso del edificio, elevada sobre el terreno y con sobresaliente visible. Si `Arch.makeStructure` esta disponible, se genera como estructura BIM; si no, queda como solido `Part`.

El panel permite activar `Aplanar terreno bajo edificio`. Con esa opcion, el area de la casa/oficina y un margen configurable quedan en una plataforma horizontal real dentro de la malla del terreno; si se desactiva, el relieve continua bajo la huella del edificio.

El generador tambien crea `AI_Contexto_QuickExample`, un `App::TextDocument` pensado como puente manual con una IA. Contiene un prompt sugerido y el JSON del ejemplo: dimensiones, semilla, recintos aproximados, sketches, muros, buques, terreno, losa y objetos creados. La opcion `Copiar contexto para IA (prompt + JSON)` copia ambos al portapapeles para pegarlos directamente en ChatGPT u otra IA. `GEE_ContextJSON` se conserva como JSON puro para que la reconstruccion no dependa del texto del prompt.

El comando **Importar JSON / Import JSON** (`GameEngineExport_ImportJSONExample`) abre un dialogo para pegar JSON de ChatGPT y reconstruir una casa u oficina con el mismo motor del Quick Example. Acepta JSON puro o texto con encabezado y extrae automaticamente el bloque desde el primer `{` hasta el ultimo `}`. La reconstruccion usa `dimensions`, `terrain`, `segments` y `rooms`; la seccion `objects` se ignora porque pertenece al documento anterior.

Flujo recomendado con IA:

- Genere un `Quick Example`.
- Marque `Copiar contexto para IA (prompt + JSON)` o use `Importar JSON / Import JSON` > `Copiar prompt + JSON actual`.
- Pegue el contenido en ChatGPT u otra IA y describa el cambio en lenguaje natural.
- La IA debe devolver un objeto JSON completo y valido, conservando `units = mm` y los segmentos `[x1,y1,x2,y2]`.
- Abra `Importar JSON / Import JSON`, pegue el JSON devuelto y pulse `Generar`.
- Para otra iteracion puede activar `Copiar contexto actualizado para IA (prompt + JSON)`.

Hay un ejemplo en `examples/json/quick_example_house_sample.json`.

El comando **Puertas y ventanas BIM** agrega objetos de puerta/ventana sobre el ultimo `GEE_QuickExample_*`. Lee los sketches `GEE_SK_DoorOpenings` y `GEE_SK_WindowOpenings`, intenta crear objetos con `Arch.makeWindow(...)` y agrega hojas de puerta abiertas a 90 grados para pruebas visuales y de exportacion.

El comando **Agregar techo / Add Roof** agrega un techo sencillo al ultimo `GEE_QuickExample_*` generado o importado desde JSON. Lee `GEE_ContextJSON` cuando esta disponible, toma `width_mm`, `depth_mm`, `wall_height_mm` y los segmentos exteriores, y crea un techo a dos aguas como solido `Part::Feature` exportable a X3D. Internamente ejecuta `macros/AgregarTechoBIM_QuickExample.FCMacro`.

Parametros iniciales del techo:

- Tipo: dos aguas con cumbrera longitudinal.
- Alero: `600 mm`.
- Altura de cumbrera: `1800 mm` sobre la altura de muro.
- Espesor: `120 mm`.
- Material visual: teja oscura.

Por ahora no usa un objeto techo BIM complejo. Queda etiquetado con propiedades `GEE_Role = roof`, `IfcType = Roof`, `GEE_QuickExampleObject = True` y `GEE_BIMFallback = True` para exportacion, filtrado y futuras conversiones BIM.

Para proyectos que no vienen del Quick Example existen macros genericas:

- `CrearPuertasBIMDesdeSketch.FCMacro`: convierte el sketch seleccionado en puertas `Arch_Window` con `IfcType = Door` y apertura nativa `Opening = 100`.
- `CrearVentanasBIMDesdeSketch.FCMacro`: convierte el sketch seleccionado en ventanas `Arch_Window` con marco y vidrio definidos en `WindowParts`.

En ambos casos el sketch debe contener lineas de centro de los buques. No dependen de nombres `GEE_*` ni de grupos del generador. Las macros usan una transaccion de FreeCAD, por lo que `Ctrl+Z` elimina el conjunto completo creado.

Reglas de ventana:

- La cota `Z` del sketch o de la linea seleccionada se usa como base/antepecho de la ventana.
- La altura de ventana se indica en un dialogo.
- Si el sketch contiene geometria con variacion vertical suficiente en `Z`, la macro puede deducir la altura del buque.
- La macro genera un sketch rectangular de perfil por cada buque y llama `Arch.makeWindow(baseobj=perfil_sketch, parts=...)`, replicando el flujo de la herramienta BIM `Arch_Window` sin agregar geometria auxiliar `Part`.

### Barras de herramientas por funcion

El Workbench separa los comandos en tres barras para que los iconos indiquen el tipo de trabajo:

- **Game Engine Export**: `Ejemplo rapido`, `Ejecutar en Castle`, `Exportar X3D` y `Ayuda`. Los dos primeros forman el flujo minimo para comenzar.
- **Game Engine Export - Escena / IA**: propiedades de luz, `Importar JSON / IA`, puertas/ventanas BIM y techo.
- **Game Engine Export - Diagnostico**: `Analizar X3D` y `Diagnostico Castle`.

`Recargar Workbench` se mantiene en el menu, pero no ocupa una barra de usuario porque es principalmente una herramienta de desarrollo.

### Contexto para inteligencia artificial

`AI_CONTEXT.md` se distribuye en la raiz del Workbench como contexto tecnico estable para GPT, Codex u otros asistentes. Explica que hace el Workbench, su arquitectura, comandos, flujo X3D/Castle, materiales, GameStart, JSON/IA, diagnostico, pruebas minimas, privacidad y reglas para modificarlo sin romper comportamiento existente.

La pestana **Ayuda > IA / JSON** incluye **Copiar contexto del Workbench para IA**, que copia ese Markdown con una instruccion breve para pegarlo en una conversacion. Esto es diferente de `GEE_ContextJSON`: el Markdown describe el Workbench; el JSON describe la escena concreta.

### Ayuda y primeros pasos

El comando **Ayuda / Help** usa un icono propio `resources/icons/gameexport_help.svg` y abre una ventana con pestanas `Primeros pasos`, `Botones`, `IA / JSON` e `Informacion`. La pestana `Informacion` reutiliza la misma fuente tecnica que permanece disponible dentro del panel principal, evitando dos manuales divergentes.

Al activar el Workbench se muestra una ventana corta de primeros pasos una sola vez por sesion. Explica que para comenzar basta usar **Ejemplo rapido** y **Ejecutar en Castle**. El usuario puede marcar `No volver a mostrar este mensaje`; la preferencia se guarda mediante `FreeCAD.ParamGet` y la ventana puede abrirse nuevamente desde la pestana `Primeros pasos` de Ayuda.

## Materiales e iluminacion interior

En la pestana **Iluminacion / Lighting**, marca **Mejorar iluminacion interior / Improve interior lighting** y usa **Architectural** o **Bright** para interiores cerrados. Este ajuste solo modifica el X3D exportado mediante atributos `ambientIntensity`, `emissiveColor` y `shininess`; no cambia los materiales del archivo `.FCStd`.

Los `PointLight` exportados usan **Atenuacion / Falloff = Interior** para evitar una iluminacion constante hasta el borde del radio. Las **Sombras limitadas / Limited shadows** son experimentales y estan desactivadas por defecto: si se activan, solo se escriben en unas pocas luces para evitar errores de shader morado y lentitud en Castle Viewer.

Nota: las sombras dependen de la geometria. Paredes con espesor y caras cerradas funcionan mejor que superficies simples de una sola cara.

## Cielo Castle Viewer

En la pestana **Configuracion / Config**, marca **Usar cielo de Castle Viewer / Use Castle Viewer sky** para insertar un `Background` con seis imagenes de cielo en el X3D exportado.

La macro detecta la carpeta desde el ejecutable configurado. Si el ejecutable esta en `<CastleModelViewer>/castle-model-viewer.exe`, busca automaticamente `<CastleModelViewer>/example_models/skies`. Tambien puedes usar **Detectar / Detect** o **Examinar / Browse** si la carpeta esta en otra ubicacion.

El selector acepta una carpeta con archivos terminados en `back`, `bottom`, `front`, `left`, `right` y `top`, como `foggy_sky_back.png`.

Durante el postproceso, las imagenes se copian junto al X3D en `<BaseName>_assets/skies/` y el `Background` usa rutas relativas. Esto mantiene portable la exportacion y no modifica el archivo `.FCStd`.

Cuando la carpeta se detecta desde el ejecutable, el sidecar guarda el modo automatico en vez de guardar una ruta absoluta de usuario. Asi otro equipo puede usar su propio ejecutable Castle y su propia carpeta `example_models/skies`.

## Materiales, texturas y reflejos

La pestana **Texturas / Textures** permite ahora tomar **uno o varios objetos seleccionados de FreeCAD** y guardar en ellos un acabado reproducible para la exportacion. La configuracion queda en propiedades `GEE_*` del propio objeto, por lo que se conserva al guardar el `.FCStd`; no se elimina ni se reemplaza la propiedad nativa `Material` de FreeCAD.

Los acabados iniciales son:

- **Textura / Texture**: aplica una imagen y genera UV planares con proyeccion `Auto`, `XY`, `XZ` o `YZ`. El tamano de baldosa/repeticion se expresa fisicamente en milimetros.
- **Pulido / Reflectante / Polished**: conserva una textura opcional y aumenta `specularColor` y `shininess` en el X3D. Es una aproximacion visual ligera, no PBR completo ni reflexion fisicamente exacta.
- **Espejo real / True mirror**: para superficies aproximadamente planas, exporta el mecanismo de Castle basado en `RenderedTexture`, `ViewpointMirror` y `TextureCoordinateGenerator mode="MIRROR-PLANE"`. La resolucion del espejo es configurable y afecta calidad/rendimiento.

Se incluye una biblioteca pequena y redistribuible, generada especificamente para el proyecto, con ceramica/porcelanato, madera, concreto, piedra, ladrillo/bloque, panel de cielo y metal cepillado. Tambien puede elegirse una imagen `.png`, `.jpg`, `.jpeg` o `.webp` personalizada. Las texturas exportadas se copian a `<BaseName>_assets/textures/` y se referencian mediante rutas relativas.

El flujo anterior de **textura de suelo** se conserva internamente por compatibilidad con preferencias y sidecars existentes, pero la interfaz principal utiliza la nueva asignacion por objeto. El espejo y el acabado pulido deben considerarse **experimentales hasta completar prueba visual en Castle Model Viewer**.

## Herramienta Add Light Properties

El comando **Agregar propiedades a luz** (`GameEngineExport_AddLightProperties`) permite seleccionar una luminaria master o una instancia `App::Link`. Si se selecciona un Link, el comando resuelve el master y guarda alli las propiedades `CGE_Light*`; el Link no se modifica.

Durante la exportacion X3D, cada Link genera sus propios `PointLight` usando su `Placement`. La configuracion vive en el master y las instancias heredan intensidad, color, rango, direccion, offset y distribucion.

La vista previa crea objetos temporales `CGE_TempLightPreview*`, que se excluyen de la geometria exportada.

### Luminarias 3D automaticas

La opcion **Detectar luminarias 3D automaticamente / Auto-detect 3D luminaires** crea una luz para cada instancia `App::Link` de luminaria que tenga un solido con volumen. El origen se calcula con la envolvente de los solidos, no con la envolvente completa del objeto. Asi se ignoran simbolos 2D, lineas y anotaciones incluidos dentro del mismo master.

En distribuciones `Grid`, `Line` o `Ring`, la intensidad configurada representa la potencia total de la luminaria y se reparte entre los puntos generados. Esto evita que un panel de cuatro puntos produzca cuatro veces la intensidad solicitada.

Cuando la lista de exportacion esta vacia, el Workbench crea una seleccion 3D automatica. Si existe una lista explicita guardada, la conserva y aplica la misma politica para completarla con objetos 3D ocultos. Cuando esta activa **Incluir objetos 3D ocultos / Include hidden 3D objects**, incluye cualquier objeto con un solido de volumen positivo o una malla real aunque el objeto o su grupo esten ocultos. Esto cubre cielorrasos, columnas, equipos, mobiliario e instancias `App::Link` sin depender de los nombres usados por un proyecto. Excluye sketches, objetos `Part2DObject`, geometria de solo lineas, objetos identificados como 2D aunque tengan un espesor artificial, textos auxiliares, masters usados por `App::Link` y contenido de grupos de biblioteca, masters, internos, referencias, prototipos o catalogos.

Antes de llamar al exportador GUI, el Workbench activa temporalmente la visibilidad de los objetos seleccionados y sus grupos padre. Esto evita que FreeCAD omita dispositivos de grupos electricos o HVAC ocultos. Al terminar, incluso si ocurre una excepcion, restaura una instantanea completa de `ViewObject.Visibility` sin guardar el documento.

Para excepciones documentales, un objeto o su master enlazado puede tener propiedades booleanas `GameExportInclude` o `GameExportExclude`. La exclusion tiene prioridad. Estas propiedades son opcionales; el Workbench no las agrega ni modifica automaticamente.

La deteccion automatica de luminarias acepta nombres comunes, metadatos semanticos como `IfcType`, `PredefinedType`, `ObjectType`, `Category`, `Role`, `EquipmentType`, `DeviceType` y `GameExportRole`, o una propiedad booleana `IsGameExportLuminaire`, `IsLuminaire` o `IsLightFixture`. Siempre exige un solido 3D con volumen antes de generar una luz.

## Vista previa Web

En **Salida / Output**, el boton **Vista previa Web / Web preview** exporta el X3D con el mismo flujo normal, genera un `index.html` junto al X3D e inicia un servidor HTTP local en segundo plano. El navegador abre siempre `http://127.0.0.1:<puerto>/index.html`; no se utiliza `file://`.

El servidor usa solo librerias estandar de Python, escucha exclusivamente en `127.0.0.1`, busca un puerto libre entre 8000 y 9000 y sirve unicamente la carpeta del HTML. Se reutiliza para vistas de la misma carpeta y se cierra al cambiar de carpeta, tras 15 minutos sin solicitudes, durante la recarga del Workbench o al terminar FreeCAD.

La pagina usa X3DOM estable desde `https://www.x3dom.org/release/`. El `Scene` del X3D se inserta directamente dentro del HTML, conservando `Viewpoint` y `NavigationInfo`. El generador convierte etiquetas X3D autocerradas a cierres explicitos compatibles con HTML y muestra un estado de carga en la barra superior. Los assets relativos, como texturas y cielos en `<BaseName>_assets/`, siguen funcionando. Las referencias locales absolutas o `file://` se convierten a rutas relativas; si apuntan fuera de la carpeta servida, el recurso se copia a `.gee_web_assets/`.

Para evitar interiores oscuros en archivos sin iluminacion, el HTML activa `headlight="true"` en una copia del `NavigationInfo` solo cuando no existen nodos `DirectionalLight`, `PointLight` o `SpotLight`. Si el X3D ya contiene luces, conserva el valor exportado para no sobreexponer la vista previa. Este ajuste no modifica el X3D exportado, el documento FreeCAD ni la iluminacion usada por Castle Game Engine.

## Diagnostico Castle

El comando **Diagnostico Castle / Castle Diagnostics** (`GameEngineExport_CastleDiagnostics`) localiza el X3D asociado al documento activo y permite analizarlo, abrirlo en Castle con registro de shaders o solicitar una captura automatica desde `GameStart`. Si no existe un X3D asociado, solicita un archivo manualmente y no reutiliza la ruta de otro documento.

El nucleo `core/castle_diagnostics.py` no importa FreeCAD, FreeCADGui ni Qt. Su funcion publica `run_diagnostic(...)` recibe parametros explicitos y devuelve un diccionario versionado compatible con JSON para reutilizacion desde pruebas, macros y una futura herramienta MCP.

Todos los resultados se escriben en `_castle_debug` junto al X3D: manifiesto JSON, resumen Markdown, reportes del analizador, validacion de `castle-model-converter`, **stdout/stderr del visor en un archivo separado**, copia del **registro nativo de Castle** cuando se actualiza y captura cuando corresponde. El manifiesto registra el ciclo `started -> completed/failed` cuando el visor termina y comprueba la existencia de la captura solicitada. El FCStd y el X3D de origen permanecen sin cambios.

## Archivos incluidos

- `Init.py`, `InitGui.py`: arranque del workbench y registro de comandos.
- `core/`: modulos para exportar, manejar luces, persistencia y utilidades.
- `ui/`: paneles TaskPanel de escena, configuracion y texto informativo.
- `commands/`: comando principal GameEngineExport_Open.
- `core/quick_examples.py`: generador de ejemplos rapidos con Sketcher y Arch Wall.
- `core/json_importer.py`: lectura, validacion y reconstruccion de Quick Example desde JSON.
- `macros/AgregarPuertasVentanasBIM_QuickExample.FCMacro`: macro usada por el comando de puertas y ventanas BIM.
- `macros/AgregarTechoBIM_QuickExample.FCMacro`: macro independiente para agregar un techo simple exportable al ultimo Quick Example.
- `macros/bim_from_selected_sketch.py`: base reutilizable para crear puertas o ventanas desde el sketch seleccionado.
- `macros/CrearPuertasBIMDesdeSketch.FCMacro`: macro generica de puertas desde sketch seleccionado.
- `macros/CrearVentanasBIMDesdeSketch.FCMacro`: macro generica de ventanas desde sketch seleccionado.
- `resources/icons/gameexport.svg`: icono del workbench.
- `resources/icons/add_light_properties.svg`: icono del comando para propiedades de luz.
- `resources/icons/quick_example.svg`: icono del comando de ejemplo rapido.
- `resources/icons/import_json_example.svg`: icono del comando para importar JSON.
- `resources/icons/bim_doors_windows.svg`: icono del comando para puertas y ventanas BIM.
- `resources/icons/quick_example_roof.svg`: icono del comando para agregar techo simple.
- `examples/json/quick_example_house_sample.json`: payload de prueba para importacion JSON.
- `tests/`: pruebas automatizadas puras y de integracion para QA.
- `translations/`: catalogo fuente y traduccion Qt compilada.

Los archivos de coordinacion, respaldos y `notes/` se conservan en el entorno de desarrollo, pero se excluyen del repositorio publico dedicado y del runtime del Addon.

## Ubicacion dentro del repositorio / Location inside repository

- `Init.py`, `InitGui.py`, `package.xml` y `README.md` viven en la raiz del repositorio dedicado.
- Los iconos, texturas y demas recursos estan bajo `resources/` y se resuelven desde la ubicacion del propio Workbench.
- Un loader del monorepositorio puede seguir usandose durante desarrollo, pero queda fuera del repositorio dedicado y no es necesario para instalar, actualizar o ejecutar el Addon.

## Workbench vs macro

- **Workbench**: ofrece menus y toolbars propios, y carga paneles dedicados sin mezclar con otras macros. Es mas facil mantener configuraciones (ParamGet) y sidecars por archivo, y se actualiza como paquete completo.
- **Macro unitaria**: suele ser un unico archivo en `Macro/`, rapida de compartir pero tiende a mezclar UI y logica en un bloque, con menos separacion de modulos y sin menues persistentes. Para funciones simples es ligera, pero para flujos largos se vuelve dificil de mantener.
- **En este proyecto**: se eligio Workbench porque se necesitan paneles, comandos, persistencia, iconos y recursos adicionales. La recarga rapida del entorno de desarrollo no forma parte del flujo normal del Addon.

## Creditos / Credits

Creado por Marco Vinicio Mora Fallas a partir de necesidades reales de mantenimiento y remodelacion de edificios, utilizando FreeCAD y software libre. El desarrollo ha contado con asistencia de herramientas de IA para programacion, documentacion y diagnostico, con revision humana y pruebas en FreeCAD y Castle.
