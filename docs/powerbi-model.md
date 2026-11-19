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

La migración de archivos antiguos puede dejar IDs de local/visitante vacíos
cuando el orden previo de IDs no codificaba la localía. Esas filas no aparecerán
en segmentadores por rol hasta que la fuente aporte localía verificable.

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
        COUNTROWS(GAMES),
        GAMES[GAME_STATUS] = "Finalizado",
        GAMES[WINNER_TEAM_ID] = GAMES[HOME_TEAM_ID]
    )

Victorias visitante :=
    CALCULATE(
        COUNTROWS(GAMES),
        GAMES[GAME_STATUS] = "Finalizado",
        GAMES[WINNER_TEAM_ID] = GAMES[AWAY_TEAM_ID]
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
