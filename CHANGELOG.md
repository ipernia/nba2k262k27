# Registro de cambios

## Sin publicar

- Se normalizaron los esquemas principales de equipos, partidos y estadísticas
  de equipo/jugador para el modelo relacional 2026-27.
- `games.csv` pasó de equipo 1/equipo 2 a local/visitante, resultado y estado.
- Se incorporó soporte opcional a playoffs en la descarga.
- Se añadieron reintentos selectivos, backoff exponencial y respeto de
  `Retry-After` para errores temporales.
- Se recuperan campos de catálogos legados y se convierten altura a metros y
  peso a kilogramos; los acumulados regulares se derivan sin mezclar playoffs.
- Se documentaron las fuentes, límites y relaciones de Power BI.
- Se migraron los campos disponibles de los CSV antiguos sin eliminar
  `data/old/` ni las tablas legacy de temporada.
- Los campos no disponibles de forma oficial permanecen vacíos.
- Se completan los perfiles incompletos de jugadores desde `CommonPlayerInfo`,
  con fecha, medidas, posición, dorsal y nacionalidad; los valores se
  normalizan y se deriva la URL de bandera.
- Se infiere cancha neutral si ambos equipos carecen de `IS_HOME` y no existe
  señal explícita de cancha.
- Se conservan los campos `*_PCT` en escala decimal de 0 a 1 para aplicar el
  formato visual de porcentaje en Power BI.

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
