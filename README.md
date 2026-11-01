# NBA Local Stats

Proyecto local para recopilar estadísticas de la NBA y preparar archivos CSV
que se puedan consumir desde Excel y Power BI. Las estadísticas por partido
proceden de `LeagueGameLog`; los catálogos usan endpoints públicos de `nba_api`.
Los assets de camisetas se incorporan
únicamente mediante asociaciones curadas con archivos de Wikimedia Commons.

> **Estado:** el programa descarga estadísticas por partido y actualiza
> catálogos de jugadores/equipos y dimensiones de temporada. Los datos se
> guardan en CSV UTF-8 con BOM. El lanzador BAT está disponible; la
> programación diaria todavía debe configurarse en Windows.

## Requisitos

- Windows 10/11.
- Python 3.10 o posterior.
- Visual Studio Code (recomendado).

La biblioteca `nba_api` facilita las consultas, pero su licencia MIT no concede
por sí misma derechos sobre los datos de la NBA. Antes de su uso, revisa las
condiciones aplicables y evita consultas excesivas.

## Preparar el entorno

Desde PowerShell, en la carpeta del proyecto:

Si `.venv` ya existe, no vuelvas a crearla; activa el entorno existente y
continúa con la instalación de dependencias.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Si PowerShell impide activar el entorno, puedes invocar sus herramientas
directamente sin activarlo:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

La instalación editable instala el paquete, `nba_api` y las herramientas de
desarrollo declaradas en `pyproject.toml`.

## Comprobaciones de desarrollo

Con el entorno preparado, ejecuta desde la raíz:

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

VS Code recomienda las extensiones de Python, Pylance y Ruff. Su configuración
selecciona `.venv` y pytest, y aplica el formato de Ruff al guardar archivos
Python.

## Descargar estadísticas

Desde la terminal integrada de VS Code, en la raíz del proyecto y con sus
dependencias instaladas:

```powershell
python -m nba_stats
```

El comando consulta la temporada actual. Para seleccionar una temporada
concreta, por ejemplo:

```powershell
python -m nba_stats --season 2025-26
```

Los archivos se guardan en `data/`, en UTF-8 con BOM:

- `players.csv`: catálogo de jugadores con datos biográficos disponibles,
  como fecha de nacimiento, altura, peso, posición, país y datos del draft.
- `teams.csv`: catálogo de equipos con nombre, abreviatura, arena y datos
  organizativos disponibles.
- `player_game_stats.csv`: estadísticas por `GAME_ID` y `PLAYER_ID`; incluye
  `TEAM_ID` para conservar el equipo por el que jugó en ese partido.
- `team_game_stats.csv`: estadísticas por `GAME_ID` y `TEAM_ID`.
- `player_seasons.csv`: relación jugador-equipo-temporada. La actualización
  combina plantillas NBA con los equipos observados en los registros por
  partido, por lo que puede representar traspasos dentro de una temporada.
  Incluye `PLAYER_FACE_URL` y `INDIVIDUAL_ACHIEVEMENTS`.
- `team_seasons.csv`: conferencia, división y clasificación acumulada por
  `TEAM_ID` y `SEASON_ID`, con `TEAM_LOGO_URL`, colores `PRIMARY_COLOR_RGB` y
  `SECONDARY_COLOR_RGB` y `COLOR_SOURCE_URL`. Los valores de clasificación
  son la última observación disponible para esa temporada.
- `player_awards.csv`: detalle normalizado de los logros curados, jugador,
  temporada y URL de la fuente. Solo se crea si hay entradas en su manifiesto.
- `media_assets.csv`: metadatos de licencia, atribución, página y URL
  verificada para caras de jugadores y escudos de equipos; solo se crea si
  alguno se valida correctamente.
- `team_uniform_assets.csv`: camisetas verificadas por equipo, temporada y
  edición, con enlace directo, página de origen, MIME, licencia y atribución.
  Solo se crea cuando el manifiesto contiene camisetas válidas.

Las claves repetidas se actualizan en lugar de duplicarse. Los campos vacíos
de una respuesta nueva no borran valores existentes. Los archivos antiguos
`player_game_logs.csv` y `team_game_logs.csv`, si existen, se importan al nuevo
formato; no se borran ni se modifican. Las consultas NBA tienen timeout y
reintentos limitados. Sus respuestas de catálogo se almacenan en una caché
local de 20 horas bajo `data/.cache/`; usa `--refresh-catalogs` para ignorarla.

La descarga y el guardado de estadísticas por partido ocurre antes del
enriquecimiento de catálogos. Si falla una consulta de catálogos o de Commons,
se informa el error y se conservan tanto los CSV válidos existentes como las
estadísticas recién guardadas. Los errores y las ejecuciones correctas se
registran en `logs/nba_stats.log`.

### Relaciones en Power BI

Consulta [el diccionario de datos](docs/DATA_DICTIONARY.md) para las claves y
relaciones sugeridas en Power BI. No se guarda un equipo fijo en
`players.csv`: las relaciones históricas se conservan en `player_game_stats`
y `player_seasons`.

### Camisetas de Wikimedia Commons

Las imágenes no se buscan por nombre ni se descargan automáticamente de
NBA.com. Cada archivo debe revisarse manualmente y añadirse a
`config/team_uniform_manifest.csv` con su título exacto de Commons y el ID de
entidad. `PLAYER_FACE` y `TEAM_LOGO` no llevan temporada ni edición; esos
assets se auditan además en `media_assets.csv`.
`JERSEY` requiere temporada y edición. El programa consulta la licencia y
atribución actuales en Commons, comprueba el enlace HTTPS directo, el MIME y la
firma del contenido, y solo admite CC0, CC BY, CC BY-SA o dominio público.

Las consultas de metadatos y de imagen tienen timeout y reintentos limitados
por `--attempts` y `--retry-delay`. Si un asset falla, se registra el error en
`logs/nba_stats.log`, se continúa con los demás, se conservan los datos
anteriores y la ejecución termina con código distinto de cero para que el
Programador de tareas pueda detectar el problema.

Los colores y premios se gestionan mediante estos manifiestos curados:

- `config/team_branding_manifest.csv`: `TEAM_ID`, colores primario/secundario
  como `R,G,B` (cada componente entre 0 y 255) y `SOURCE_URL` HTTPS. No se
  inventan colores ni se copian valores sin fuente verificable.
- `config/player_awards_manifest.csv`: `PLAYER_ID`, `SEASON_ID`,
  `ACHIEVEMENT` y `SOURCE_URL` HTTPS. Los logros, incluidos MVP y selecciones
  All-NBA, se introducen a partir de una fuente revisada. Se mantiene una
  tabla detallada `player_awards.csv` y un resumen en `player_seasons.csv`.

No se hacen cientos de consultas NBA de premios por jugador. Los tres
manifiestos se versionan con cabeceras, pero sin datos preseleccionados.

No se ha preseleccionado ningún archivo ni se debe inferir la correspondencia
por una coincidencia de nombres. La licencia del archivo no elimina la
obligación de respetar sus condiciones de atribución ni las condiciones de uso
de los datos de la NBA.

### Ejecutar en Windows con el BAT

Una vez instalado el proyecto en `.venv`, puedes iniciar la actualización de
forma rápida:

- Desde el Explorador de archivos, haz doble clic en `run_daily.bat`.
- Desde la terminal integrada de VS Code, en la raíz del proyecto:

  ```powershell
  .\run_daily.bat
  ```

El BAT cambia a la carpeta del proyecto antes de ejecutarlo, por lo que también
se puede invocar desde otra carpeta. Acepta las mismas opciones que el módulo,
por ejemplo `.\run_daily.bat --season 2025-26`. En VS Code la salida queda
visible en la terminal; en ejecución desatendida, consulta
`logs\nba_stats.log`. El BAT devuelve un código distinto de cero si falla.

Opciones disponibles:

```powershell
python -m nba_stats --help
python -m nba_stats --season 2025-26 --data-dir data --attempts 3 --timeout 30 --retry-delay 2
python -m nba_stats --skip-catalogs
python -m nba_stats --catalogs-only --refresh-catalogs
python -m nba_stats --catalogs-only --asset-manifest config/team_uniform_manifest.csv `
  --team-branding-manifest config/team_branding_manifest.csv `
  --awards-manifest config/player_awards_manifest.csv
```

El endpoint proporciona datos estadísticos de NBA.com; tener instalada la
biblioteca no determina las condiciones de reutilización de esos datos.

## Estructura actual

```text
.
├── .vscode/
├── config/
│   ├── player_awards_manifest.csv
│   ├── team_branding_manifest.csv
│   └── team_uniform_manifest.csv
├── docs/
│   └── DATA_DICTIONARY.md
├── src/
│   └── nba_stats/
│       ├── __main__.py
│       ├── catalog_client.py
│       ├── client.py
│       ├── commons.py
│       ├── curated_data.py
│       └── storage.py
├── tests/
├── CHANGELOG.md
├── run_daily.bat
├── .gitignore
├── pyproject.toml
└── README.md
```

## Programación diaria

El BAT es apto para ejecutarse desde el Programador de tareas de Windows.
Configura `run_daily.bat` como programa y usa la carpeta del proyecto como
directorio de inicio. Revisa `logs\nba_stats.log` para confirmar el resultado.

Los archivos de datos y los registros se guardarán localmente en `data/` y
`logs/`. Ambas carpetas están excluidas de Git para no publicar datos generados
ni archivos de ejecución.
