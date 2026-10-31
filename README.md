# NBA Local Stats

Proyecto local para recopilar estadísticas de la NBA y preparar archivos CSV
que se puedan consumir desde Excel y Power BI. La fuente prevista es el
endpoint `LeagueGameLog` de `nba_api`.

> **Estado:** ya se pueden descargar las estadísticas por partido de jugadores
> y equipos y acumularlas en CSV. El lanzador BAT está disponible; la
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

- `players.csv`: catálogo con una fila por `PLAYER_ID` y el nombre del jugador.
- `teams.csv`: catálogo con una fila por `TEAM_ID`, nombre y abreviatura.
- `player_game_stats.csv`: estadísticas por `GAME_ID` y `PLAYER_ID`; incluye
  `TEAM_ID` para conservar el equipo por el que jugó en ese partido.
- `team_game_stats.csv`: estadísticas por `GAME_ID` y `TEAM_ID`.

Las claves repetidas se actualizan en lugar de duplicarse. Los archivos
antiguos `player_game_logs.csv` y `team_game_logs.csv`, si existen, se importan
al nuevo formato cuando se ejecuta la actualización; no se borran ni se
modifican. Las solicitudes tienen timeout y hasta tres intentos por tipo de
registro. Si falla la descarga de jugadores o equipos, los nuevos CSV no se
actualizan. Los errores y las ejecuciones correctas se registran en
`logs/nba_stats.log`.

### Relaciones en Power BI

Configura relaciones uno-a-muchos desde `teams[TEAM_ID]` hacia
`team_game_stats[TEAM_ID]` y `player_game_stats[TEAM_ID]`, y desde
`players[PLAYER_ID]` hacia `player_game_stats[PLAYER_ID]`. No se guarda un
equipo fijo en `players.csv`: un jugador puede cambiar de equipo; el `TEAM_ID`
de cada fila de `player_game_stats.csv` conserva la relación histórica.

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
```

El endpoint proporciona datos estadísticos de NBA.com; tener instalada la
biblioteca no determina las condiciones de reutilización de esos datos.

## Estructura actual

```text
.
├── .vscode/
├── src/
│   └── nba_stats/
│       ├── __main__.py
│       ├── client.py
│       └── storage.py
├── tests/
├── run_daily.bat
├── .gitignore
├── pyproject.toml
└── README.md
```

## Próximas fases

- Documentar la programación diaria con el Programador de tareas de Windows.

Los archivos de datos y los registros se guardarán localmente en `data/` y
`logs/`. Ambas carpetas están excluidas de Git para no publicar datos generados
ni archivos de ejecución.
