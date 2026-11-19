# Diccionario de datos

Los CSV son UTF-8 con BOM y usan identificadores oficiales de NBA donde están
disponibles. Los campos desconocidos permanecen vacíos.

## TEAMS (`teams.csv`)

| Campo | Tipo | Procedencia / notas |
|---|---|---|
| TEAM_ID | entero textual | Clave primaria; ID oficial de NBA |
| TEAM_NAME | texto | NBA LeagueGameLog / registro histórico |
| TEAM_ABBREVIATION | texto | NBA LeagueGameLog |
| TEAM_CITY, TEAM_NICKNAME | texto | No disponible de forma fiable en el flujo actual |
| TEAM_LOGO_URL | URL | URL construida desde TEAM_ID |
| TEAM_PRIMARY_COLOR, TEAM_SECONDARY_COLOR | texto HEX | Pendiente de fuente verificada |
| CONFERENCE, DIVISION | texto | Datos históricos normalizados cuando existen |
| WINS, LOSSES, GAMES_PLAYED, WIN_PCT | enteros / decimal | Temporada regular disponible |
| RANKS, GAMES_BACK, HOME_*, AWAY_* | enteros / decimal | Pendiente de endpoint de clasificación oficial |
| NBA_CHAMPIONSHIPS, ARENA_NAME, ARENA_CAPACITY | entero / texto | Pendiente de fuente histórica y oficial verificada |
| LAST_UPDATED | fecha-hora ISO 8601 | Pendiente de llenado automático |

## GAMES (`games.csv`)

`GAME_ID` es la clave primaria. `SEASON` usa formato `YYYY-YY`.

Los campos incluyen temporada, tipo de temporada, fecha/hora local y UTC,
estado, equipos local y visitante, marcadores, ganador, duración, prórrogas,
neutralidad, pabellón, asistencia, ronda de playoffs, URL de highlights y
fecha de actualización. Las columnas marcadas como desconocidas permanecen
vacías. `TEAM_ID_1/TEAM_ID_2`, `SEASON_ID`, `MATCHUP` y `VIDEO_AVAILABLE`
pertenecen al formato legado y no forman parte del modelo nuevo.

## PLAYERS (`players.csv`)

`PLAYER_ID` es la clave primaria. Los campos nuevos incluyen nombre desglosado,
nacionalidad y código ISO, bandera, nacimiento y edad, altura/peso normalizados,
posición, dorsal, fotografía, procedencia, Draft, experiencia y premios
históricos. Los campos no presentes en LeagueGameLog permanecen vacíos hasta
disponer de una fuente oficial y verificable.

## TEAM_GAME_STATS (`team_game_stats.csv`)

Clave compuesta `GAME_ID + TEAM_ID`. Cada partido debe tener exactamente dos
filas. `IS_HOME`, `TEAM_POINTS` y las estadísticas disponibles se normalizan
desde LeagueGameLog. Las estadísticas avanzadas no disponibles no se convierten
en cero.

## PLAYER_GAME_STATS (`player_game_stats.csv`)

Clave compuesta `GAME_ID + PLAYER_ID`. `TEAM_ID` representa el equipo del
jugador en ese partido. Las estadísticas disponibles proceden de LeagueGameLog.
Los dobles-dobles, triples-dobles y datos avanzados no presentes en la fuente
se dejan vacíos.

## Tablas de temporada legacy

`player_seasons.csv` y `team_seasons.csv` se conservan temporalmente solo por
compatibilidad de migración. No forman parte de las relaciones de Power BI.
Sus datos de entidad se trasladan a `players.csv` y `teams.csv`; no se elimina
ningún archivo hasta confirmar una migración completa.

## Relaciones de Power BI

- `TEAMS[TEAM_ID]` uno-a-muchos con `TEAM_GAME_STATS[TEAM_ID]`.
- `GAMES[GAME_ID]` uno-a-muchos con `TEAM_GAME_STATS[GAME_ID]`.
- `PLAYERS[PLAYER_ID]` uno-a-muchos con `PLAYER_GAME_STATS[PLAYER_ID]`.
- `GAMES[GAME_ID]` uno-a-muchos con `PLAYER_GAME_STATS[GAME_ID]`.
- `TEAMS[TEAM_ID]` con `GAMES[HOME_TEAM_ID]` y `GAMES[AWAY_TEAM_ID]`.

Se recomienda desactivar una de las relaciones bidireccionales si se usan
medidas DAX simultáneamente para local y visitante, o crear una tabla Calendar
independiente sin usar `SEASONS` como eje obligatorio.
