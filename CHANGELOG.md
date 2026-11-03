# Registro de cambios

## Sin publicar

- Se simplificó la salida a `players.csv`, `teams.csv`,
  `player_game_stats.csv` y `team_game_stats.csv`.
- Se generan las URLs de caras y escudos de NBA.com en los catálogos con los
  IDs de jugador y equipo.
- Se separaron los datos de jugador/equipo de los datos propios de cada
  temporada en los CSV existentes.
- Se retiró la descarga de datos de temporada y metadatos externos; los CSV de
  temporada existentes se conservan y normalizan.
- Se actualizó el README y se redujeron las pruebas al flujo de estadísticas y
  persistencia de los cuatro CSV.
