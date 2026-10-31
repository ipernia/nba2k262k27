# Diccionario de datos

Todos los CSV se escriben en UTF-8 con BOM. Las claves de entidad NBA se
conservan como texto para evitar conversiones de Power BI y Excel.

## Tablas y claves

| Archivo | Granularidad | Clave |
|---|---|---|
| `players.csv` | Un jugador | `PLAYER_ID` |
| `teams.csv` | Un equipo | `TEAM_ID` |
| `player_seasons.csv` | Un jugador, equipo y temporada | `PLAYER_ID`, `TEAM_ID`, `SEASON_ID` |
| `team_seasons.csv` | Un equipo y temporada | `TEAM_ID`, `SEASON_ID` |
| `player_game_stats.csv` | Un jugador en un partido | `GAME_ID`, `PLAYER_ID` |
| `team_game_stats.csv` | Un equipo en un partido | `GAME_ID`, `TEAM_ID` |
| `team_uniform_assets.csv` | Un asset de camiseta por equipo, temporada y edición | `TEAM_ID`, `SEASON_ID`, `EDITION` |

Las claves de estadísticas por partido siguen siendo las del sistema original.
Los catálogos se fusionan por clave: columnas nuevas se añaden al encabezado y
una respuesta vacía no elimina un valor previo.

## Relaciones sugeridas en Power BI

- `teams[TEAM_ID]` 1:* `team_game_stats[TEAM_ID]`
- `teams[TEAM_ID]` 1:* `player_game_stats[TEAM_ID]`
- `teams[TEAM_ID]` 1:* `player_seasons[TEAM_ID]`
- `teams[TEAM_ID]` 1:* `team_seasons[TEAM_ID]`
- `teams[TEAM_ID]` 1:* `team_uniform_assets[TEAM_ID]`
- `players[PLAYER_ID]` 1:* `player_game_stats[PLAYER_ID]`
- `players[PLAYER_ID]` 1:* `player_seasons[PLAYER_ID]`

`player_seasons` es una tabla puente: un jugador puede relacionarse con más de
un equipo en una temporada. En los datos descargados se incluyen las
asociaciones de la plantilla y las observadas en los partidos de la temporada.

## Columnas principales

### `players.csv`

- Clave y nombre: `PLAYER_ID`, `PLAYER_NAME`.
- Biografía disponible: `BIRTHDATE`, `HEIGHT`, `WEIGHT`, `POSITION`,
  `COUNTRY`, `SCHOOL`.
- Draft: `DRAFT_YEAR`, `DRAFT_ROUND`, `DRAFT_NUMBER`.

No se almacena `AGE`: se puede derivar desde `BIRTHDATE` con una fecha de
referencia definida en el informe. Los campos sin fuente o sin valor se dejan
vacíos.

### `teams.csv`

`TEAM_ID`, `TEAM_ABBREVIATION`, `TEAM_NAME`, `CITY`, `NICKNAME`, `ARENA`,
`ARENA_CAPACITY`, `OWNER`, `GENERAL_MANAGER`, `HEAD_COACH` y
`D_LEAGUE_AFFILIATION`. La información organizativa procede del endpoint
`TeamDetails`; puede cambiar con el tiempo y no es una fotografía histórica.

### `player_seasons.csv`

`PLAYER_ID`, `TEAM_ID`, `SEASON_ID`, `PLAYER_NAME`, `JERSEY_NUM`, `POSITION`,
`HEIGHT`, `WEIGHT`, `EXP` y `SCHOOL`. Los datos de plantilla son una consulta
de la temporada y los equipos jugados se agregan a partir de `LeagueGameLog`.
Los campos de altura, peso y posición pueden estar vacíos si NBA.com no los
proporciona.

### `team_seasons.csv`

`TEAM_ID`, `SEASON_ID`, `CONFERENCE`, `DIVISION`, `WINS`, `LOSSES`, `WIN_PCT`,
`HOME_RECORD`, `ROAD_RECORD`, `L10` y `STREAK`. Es una actualización de la
clasificación disponible en el momento de la consulta, no una serie diaria de
posiciones.

### Tablas de estadísticas

`player_game_stats.csv` y `team_game_stats.csv` conservan las columnas
estadísticas de `LeagueGameLog`. Las columnas descriptivas de jugador/equipo
se separan en sus catálogos; `TEAM_ID` se conserva en las estadísticas de
jugador como clave foránea.

### `team_uniform_assets.csv`

Incluye `TEAM_ID`, `SEASON_ID`, `EDITION`, `FILE_TITLE`, `IMAGE_URL`, `PAGE_URL`,
`MIME_TYPE`, `LICENSE`, `ATTRIBUTION` y `SOURCE`. Cada fila procede de una
asociación revisada manualmente en el manifiesto y de metadatos consultados en
Wikimedia Commons. No se crea una fila si falta licencia o atribución o si la
imagen directa no supera la validación.

## Fuentes y límites

- Estadísticas por partido: `LeagueGameLog` de NBA.com mediante `nba_api`.
- Biografía de jugador: `LeagueDashPlayerBioStats` y `CommonTeamRoster`.
- Datos de equipo y temporada: `TeamDetails`, `CommonTeamRoster` y
  `LeagueStandings`.
- Licencia, atribución, página y URL de imagen: API de Wikimedia Commons para
  los títulos de archivo seleccionados manualmente.

El proyecto no contiene credenciales. La licencia MIT de `nba_api` no concede
derechos de reutilización sobre los datos de NBA.com. La licencia de un asset
de Commons aplica a ese archivo y debe cumplirse individualmente.
