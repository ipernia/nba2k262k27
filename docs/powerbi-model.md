# Modelo para Power BI

Importa los cinco CSV descritos en el [diccionario de datos](../DATA_DICTIONARY.md).
No hace falta una tabla `SEASONS`: `GAMES[SEASON]` y `GAMES[SEASON_TYPE]`
identifican el ámbito de cada encuentro.

## Relaciones

Relaciones de filtro en una sola dirección, de dimensión a hechos:

- `TEAMS[TEAM_ID]` 1:* `TEAM_GAME_STATS[TEAM_ID]`
- `GAMES[GAME_ID]` 1:* `TEAM_GAME_STATS[GAME_ID]`
- `PLAYERS[PLAYER_ID]` 1:* `PLAYER_GAME_STATS[PLAYER_ID]`
- `GAMES[GAME_ID]` 1:* `PLAYER_GAME_STATS[GAME_ID]`

Para analizar local y visitante sin rutas ambiguas, crea dos consultas de
referencia de `TEAMS` en Power Query, llamadas `HOME_TEAMS` y `AWAY_TEAMS`.
Relaciona sus claves respectivamente con `GAMES[HOME_TEAM_ID]` y
`GAMES[AWAY_TEAM_ID]`, ambas activas y de una sola dirección. Mantén `TEAMS`
como la dimensión relacionada con `TEAM_GAME_STATS`. No conectes esa dimensión
directamente a ambos roles de `GAMES` si ello activa rutas de filtro alternativas.

`GAMES[HOME_TEAM_ID]` y `GAMES[AWAY_TEAM_ID]` conservan la localía oficial si
se verifica. En caso contrario pueden contener una asignación técnica
determinista; no uses esos IDs para analizar localía cuando `TEAM_GAME_STATS`
no tenga `IS_HOME` confirmado. Los partidos neutrales tampoco deben contarse
como rendimiento en casa/fuera: su `IS_HOME` se deja vacío.

## Medidas de ejemplo

```DAX
Puntos equipo := SUM(TEAM_GAME_STATS[TEAM_POINTS])

Puntos jugadores := SUM(PLAYER_GAME_STATS[POINTS])

Partidos finalizados :=
    CALCULATE(
        DISTINCTCOUNT(GAMES[GAME_ID]),
        GAMES[GAME_STATUS] = "Finalizado"
    )

Victorias local :=
    CALCULATE(
        COUNTROWS(TEAM_GAME_STATS),
        GAMES[GAME_STATUS] = "Finalizado",
        FILTER(
            TEAM_GAME_STATS,
            TEAM_GAME_STATS[IS_HOME] = TRUE()
                && TEAM_GAME_STATS[TEAM_ID] = RELATED(GAMES[WINNER_TEAM_ID])
        )
    )

Victorias visitante :=
    CALCULATE(
        COUNTROWS(TEAM_GAME_STATS),
        GAMES[GAME_STATUS] = "Finalizado",
        FILTER(
            TEAM_GAME_STATS,
            TEAM_GAME_STATS[IS_HOME] = FALSE()
                && TEAM_GAME_STATS[TEAM_ID] = RELATED(GAMES[WINNER_TEAM_ID])
        )
    )

Edad :=
VAR BirthDate = SELECTEDVALUE(PLAYERS[BIRTH_DATE])
VAR TodayDate = TODAY()
RETURN
    IF(
        ISBLANK(BirthDate),
        BLANK(),
        YEAR(TodayDate) - YEAR(BirthDate)
            - IF(
                DATE(YEAR(TodayDate), MONTH(BirthDate), DAY(BirthDate)) > TodayDate,
                1,
                0
            )
    )
```

Las medidas de victorias usan las columnas de cada fila de `GAMES` y no
necesitan propagar filtros de equipo a través de hechos. Filtra la temporada
regular 2026-27 con `GAMES[SEASON] = "2026-27"` y
`GAMES[SEASON_TYPE] = "Regular Season"`.
