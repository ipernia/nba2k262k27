# NBA Local Stats

Proyecto local para recopilar estadísticas de la NBA y preparar archivos CSV
que se puedan consumir desde Excel y Power BI. La fuente prevista es el
endpoint `LeagueGameLog` de `nba_api`.

> **Estado:** ya se pueden descargar las estadísticas por partido de jugadores
> y equipos y acumularlas en CSV. El lanzador BAT y la programación diaria aún
> no están implementados.

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

Los registros se guardan en `data/player_game_logs.csv` y
`data/team_game_logs.csv`, en UTF-8 con BOM. Las filas se acumulan por
`GAME_ID` y `PLAYER_ID` o `TEAM_ID`; si se vuelve a descargar una misma clave,
se actualiza en vez de duplicarse. Las solicitudes tienen timeout y hasta tres
intentos por tipo de registro. Si falla la descarga de jugadores o equipos,
ninguno de los dos CSV se modifica. Los errores y las ejecuciones correctas se
registran en `logs/nba_stats.log`.

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
├── .gitignore
├── pyproject.toml
└── README.md
```

## Próximas fases

- Añadir un lanzador BAT y documentar su programación diaria con el Programador
  de tareas de Windows.
- Valorar CSV de catálogos independientes para jugadores, equipos y partidos,
  además de los registros estadísticos por partido que ya se generan.

Los archivos de datos y los registros se guardarán localmente en `data/` y
`logs/`. Ambas carpetas están excluidas de Git para no publicar datos generados
ni archivos de ejecución.
