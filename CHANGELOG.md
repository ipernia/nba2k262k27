# Registro de cambios

## Sin publicar

- Se simplificó la salida a los CSV de catálogos y estadísticas de partidos.
- Se añadió `games.csv` con los datos del partido y los IDs de los equipos
  participantes, retirando los datos repetidos de los CSV de estadísticas.
- Se añadió una imagen PNG de silueta como respaldo para jugadores sin imagen.
- Se generan las URLs de caras y escudos de NBA.com en los catálogos con los
  IDs de jugador y equipo.
- Se separaron los datos de jugador/equipo de los datos propios de cada
  temporada en los CSV existentes.
- Se retiró la descarga de datos de temporada y metadatos externos; los CSV de
  temporada existentes se conservan y normalizan.
- Se actualizaron el README y las pruebas para la persistencia de los CSV.
