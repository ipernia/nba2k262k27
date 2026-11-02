# NBA Local Stats

Descarga las estadísticas de los partidos de una temporada NBA y las acumula
en cuatro CSV UTF-8 con BOM, listos para Excel o Power BI:

- `players.csv`: `PLAYER_ID`, `PLAYER_NAME`, `PLAYER_FACE_URL`.
- `teams.csv`: `TEAM_ID`, `TEAM_ABBREVIATION`, `TEAM_NAME`, `TEAM_LOGO_URL`.
- `player_game_stats.csv`: estadísticas por partido y jugador, incluido
  `TEAM_ID` para conservar el equipo por el que jugó.
- `team_game_stats.csv`: estadísticas por partido y equipo.

Las URLs de imagen se construyen directamente con los IDs de NBA.com:

- Jugadores: `https://cdn.nba.com/headshots/nba/latest/1040x760/{PLAYER_ID}.png`
- Equipos: `https://cdn.nba.com/logos/nba/{TEAM_ID}/primary/L/logo.svg`

No se descargan imágenes ni se consultan camisetas, colores, premios o
metadatos de licencia. Los catálogos de jugadores y equipos se forman con las
entidades que aparecen en los registros de partidos de la temporada; no
incluyen jugadores que todavía no hayan participado en un partido.

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
borran los valores previos cuando llegan vacíos. Los CSV antiguos que ya
existan en `data/` se conservan; esta versión solo crea o actualiza los cuatro
archivos listados arriba.

Opciones disponibles:

```powershell
python -m nba_stats --help
python -m nba_stats --season 2026-27 --data-dir data --attempts 3 --timeout 30 --retry-delay 2
```

Los errores y las ejecuciones correctas se registran en
`logs/nba_stats.log`. Los datos locales de `data/` y los registros están
excluidos de Git.

## Comprobaciones

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

## Ejecución diaria en Windows

`run_daily.bat` ejecuta la actualización con el Python del entorno `.venv`.
Se puede iniciar desde el Explorador de archivos o desde PowerShell:

```powershell
.\run_daily.bat --season 2026-27
```

Para programarlo, configura el BAT en el Programador de tareas de Windows y
establece la carpeta del proyecto como directorio de inicio.
