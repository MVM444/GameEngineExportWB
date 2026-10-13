# Validación reproducible de sombras solares

Este ejemplo comprueba la integración Solar de **GameEngineExportWB DEV** sin modificar un modelo de trabajo. Genera un plano horizontal de 20 m × 20 m, un poste vertical de 3 m, cuatro ejes cardinales y una línea celeste segmentada calculada con una fórmula de referencia independiente del adaptador Solar.

Convención: `+X = Este`, `+Y = Norte`, `+Z = arriba`. El azimut aumenta en sentido horario desde el norte configurado. La longitud esperada es `altura_poste / tan(Altitude)` y la sombra apunta en sentido contrario al sol.

## Presets

| Archivo | Altitude | Azimuth | North | Resultado esperado |
|---|---:|---:|---:|---|
| `01_east_alt45` | 45° | 90° | 0° | Oeste (`-X`), 3000 mm |
| `02_south_alt30` | 30° | 180° | 0° | Norte (`+Y`), 5196.152 mm |
| `03_west_alt60` | 60° | 270° | 0° | Este (`+X`), 1732.051 mm |
| `04_rotated_north_alt30` | 30° | 315° | 45° | Sur (`-Y`), 5196.152 mm |

Los cuatro casos cubren ambos signos de X/Y y una rotación explícita de `North`, reduciendo el riesgo de falsos positivos por inversión de vector o intercambio de ejes.

## Alcance de la prueba

La prueba base usa únicamente `shadows="true"` en `DirectionalLight`. **No** activa `shadowVolumes` ni `shadowVolumesMain`, y tampoco ajusta `defaultShadowMap`, resolución, bias ni rangos de proyección. Así se valida primero la geometría solar con el mismo camino de sombras que ya utilizaba GameEngineExport.

El informe `solar_shadow_validation_report.json` registra los ángulos, el punto final teórico, la intersección obtenida desde el rayo del adaptador, el error, los atributos de la luz X3D y el resultado opcional de `castle-model-converter --validate`.

## Ejecución

Desde PowerShell, situado en el directorio `Macros-de-Freecad`:

```powershell
$env:GAMEEXPORT_SOLAR_SHADOW_OUTPUT = "$env:TEMP\GameEngineExportWB_SolarShadowValidation"
$env:CASTLE_MODEL_CONVERTER = 'C:\ruta\a\castle-model-converter.exe'
$script = (Resolve-Path '.\GameEngineExportWB\examples\solar_shadow_validation.py').Path
$python = "exec(compile(open(r'$script', encoding='utf-8').read(), r'$script', 'exec'))"
"$python`nexit()" | & 'C:\ruta\FreeCAD 1.1\bin\freecadcmd.exe' `
  --disable-addon FacilArquitecturaWB -c
```

En Castle, la sombra renderizada del poste debe coincidir con la línea celeste. `castle-model-converter --validate` confirma la validez del X3D, pero **no sustituye la comprobación visual de la sombra renderizada**. La calidad visual de los shadow maps queda deliberadamente fuera de esta fase.

## Solar Workbench real

Los presets anteriores son deterministas y usan el contrato de `SunProperties` para aislar signos/ejes. Después de que estos casos pasen, ejecutar también el smoke existente `tests/freecad_solar_live_integration_smoke.py`, que crea un `SunProperties` mediante la implementación instalada de Solar Workbench y llama a `get_sun_position`. Esa prueba LIVE es complementaria y no debe reemplazar la comparación geométrica en Castle.

## Estado

- DEV únicamente.
- RELEASE/GitHub sin cambios.
- Siguiente validación manual: abrir los X3D en Castle Model Viewer y comparar la sombra real con la referencia celeste en los cuatro presets.
