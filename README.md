# NBA Local Stats

Descarga las estadísticas de los partidos de una temporada NBA y las acumula
en cinco CSV UTF-8 con BOM, listos para Excel o Power BI:

- `players.csv`: catálogo de jugadores.
- `teams.csv`: catálogo de equipos.
- `games.csv`: fecha, temporada y los dos IDs de equipo por partido.
- `player_game_stats.csv`: estadísticas por partido y jugador, incluido
  `TEAM_ID` para conservar el equipo por el que jugó.
- `team_game_stats.csv`: estadísticas por partido y equipo.

Las URLs de imagen se construyen directamente con los IDs de NBA.com:

- Jugadores: `https://cdn.nba.com/headshots/nba/latest/1040x760/{PLAYER_ID}.png`
- Equipos: `https://cdn.nba.com/logos/nba/{TEAM_ID}/primary/L/logo.svg`

No se descargan imágenes ni se consultan camisetas, colores, premios o
metadatos de licencia. Los catálogos de jugadores y equipos se forman con las
entidades que aparecen en los registros de partidos de la temporada; no
incluyen jugadores que todavía no hayan participado en un partido, salvo que
se incorporen desde un CSV de temporadas existente.

Si un jugador ya tiene una fila en `players.csv` pero no tiene
`PLAYER_FACE_URL`, se usa la imagen de respaldo
[player_silhouette.png](assets/player_silhouette.png). Su valor en el CSV es
`assets/player_silhouette.png`, una ruta relativa a la carpeta del proyecto.

## Requisitos

- Windows 10/11.
- Python 3.10 o posterior.

## Preparar el entorno

Desde PowerShell, en la carpeta del proyecto:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Si el entorno virtual ya existe, actívalo y continúa desde la instalación de
dependencias. También puedes invocar Python sin activar el entorno:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Descargar una temporada

La temporada se determina automáticamente: empieza en octubre. Para
actualizar la actual:

```powershell
python -m nba_stats
```

Para descargar o actualizar 2026-27 explícitamente:

```powershell
python -m nba_stats --season 2026-27
```

Los registros se acumulan por sus claves de partido. Volver a ejecutar el
comando actualiza las filas existentes sin duplicarlas. Los nuevos datos no
borran los valores previos cuando llegan vacíos. La ejecución crea o actualiza
los cinco CSV de partidos y catálogos descritos arriba.

Si ya existen `player_seasons.csv` o `team_seasons.csv`, también se normalizan
al guardar registros: los datos propios de cada jugador o equipo se trasladan
a `players.csv` o `teams.csv`, respectivamente, y en los CSV de temporadas se
conservan únicamente los campos estacionales. El programa actual no descarga
ni crea esos dos CSV.

Los catálogos contienen:

- `players.csv`: `PLAYER_ID`, `PLAYER_NAME`, `PLAYER_FACE_URL`, `HEIGHT`,
  `WEIGHT`, `SCHOOL`, `INDIVIDUAL_ACHIEVEMENTS`.
- `teams.csv`: `TEAM_ID`, `TEAM_ABBREVIATION`, `TEAM_NAME`, `TEAM_LOGO_URL`,
  `PRIMARY_COLOR_RGB`, `SECONDARY_COLOR_RGB`, `COLOR_SOURCE_URL`.

Los CSV de temporadas, cuando existen, contienen:

- `player_seasons.csv`: `PLAYER_ID`, `TEAM_ID`, `SEASON_ID`, `JERSEY_NUM`,
  `POSITION`, `EXP`.
- `team_seasons.csv`: `TEAM_ID`, `SEASON_ID`, `CONFERENCE`, `DIVISION`,
  `WINS`, `LOSSES`, `WIN_PCT`, `HOME_RECORD`, `ROAD_RECORD`, `L10`, `STREAK`.

`games.csv` contiene `GAME_ID`, `SEASON_ID`, `GAME_DATE`, `TEAM_ID_1`,
`TEAM_ID_2` y `VIDEO_AVAILABLE`. Los IDs están ordenados numéricamente; no
representan localía. Las columnas de esos datos (incluido `MATCHUP`) se retiran
de los dos CSV de estadísticas; `GAME_ID` permanece como clave para
relacionarlos con `games.csv`. Las filas antiguas se migran al actualizar los
datos.

Opciones disponibles:

```powershell
python -m nba_stats --help
python -m nba_stats --season 2026-27 --data-dir data --attempts 3 --timeout 30 --retry-delay 2
```

Los errores y las ejecuciones correctas se registran en
`logs/nba_stats.log`. Los datos locales de `data/` y los registros están
excluidos de Git.

## Comprobaciones

Con el entorno virtual activado:

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

O sin activarlo, usando explícitamente su intérprete:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

## Ejecución diaria en Windows

`run_daily.bat` ejecuta la actualización con el Python del entorno `.venv`.
Se puede iniciar desde el Explorador de archivos o desde PowerShell:

```powershell
.\run_daily.bat --season 2026-27
```

Para programarlo, configura el BAT en el Programador de tareas de Windows y
establece la carpeta del proyecto como directorio de inicio.
