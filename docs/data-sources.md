# Fuentes y proceso de extracción

## Fuente actual

La extracción usa `nba_api` como cliente comunitario del endpoint NBA Stats
`LeagueGameLog`, consultado por separado para `PlayerOrTeam=P` y `T`.
`nba_api` no es una API oficial de NBA ni garantiza estabilidad, disponibilidad
ni límites de uso. NBA puede modificar, limitar o bloquear el servicio. El
proyecto no incorpora scraping de páginas web.

La opción `--season-type` permite solicitar `Regular Season` o `Playoffs`.
Timeouts, reintentos, retroceso exponencial y el encabezado `Retry-After` se
aplican a fallos de red, HTTP 429 y HTTP 5xx. HTTP 403/404 y errores de formato
no se reintentan. No se conoce ni se promete un límite oficial de peticiones.

## Catálogo estático de franquicias

El catálogo de [`team_catalog.py`](../src/nba_stats/team_catalog.py) se carga
localmente y no realiza peticiones diarias. Sus grupos de campos se mantienen
con estas referencias:

- Identidad, conferencia y división: [NBA Teams](https://www.nba.com/teams) y
  la clasificación oficial de [NBA Standings](https://www.nba.com/standings).
- Colores: identidad visual publicada por cada franquicia; se almacenan
  únicamente valores HEX curados y se dejan vacíos los que no puedan
  verificarse.
- Títulos: historial oficial de cada franquicia en NBA.com; se cuentan los
  títulos de la franquicia aunque se hayan conseguido en otra ciudad.
- Arena y capacidad: página oficial del equipo o del pabellón vigente a
  2026-11-19.

Las capacidades y los nombres de pabellón son datos estáticos y deben revisarse
cuando exista un cambio de nombre o configuración. No se sustituyen por una
respuesta vacía de NBA Stats.

## Procedencia por tabla

| Datos | Fuente/transformación |
|---|---|
| IDs, nombres y abreviaturas de equipo; estadísticas de equipo por partido | `LeagueGameLog` de NBA Stats |
| IDs, nombres y estadísticas de jugadores por partido | `LeagueGameLog` de NBA Stats |
| Local/visitante | Solo se confirma con los dos `MATCHUP` recíprocos (`vs.` y `@`); si no, los IDs de `GAMES` se ordenan de forma determinista y `TEAM_GAME_STATS.IS_HOME` queda vacío |
| Marcador y ganador | `PTS` de ambos equipos; ganador es el ID del mayor marcador |
| `SEASON` / `SEASON_TYPE` | Parámetros de la ejecución y `SEASON_ID` legado |
| Acumulados regulares en TEAMS | Agregación de partidos finalizados para la temporada consultada; los playoffs se excluyen |
| Ciudad, conferencia y división | Catálogo estático de franquicias basado en directorio oficial NBA |
| Colores | Catálogo estático de identidad visual oficial; HEX curado, no extraído de logotipos |
| Títulos, pabellón y capacidad | Catálogo histórico/instalaciones verificado con historial oficial NBA y sitios oficiales |
| Clasificación y `GAMES_BACK` | `LeagueStandings` de NBA Stats, solo temporada regular |
| Logos y headshots | Plantillas NBA.com compuestas con IDs; no se comprueba la respuesta HTTP |
| Catálogos estáticos e históricos | CSV locales previos, migrados cuando hay correspondencia inequívoca |

## Campos no recuperados

El endpoint utilizado no proporciona en este flujo nacionalidad, nacimiento,
Draft, premios, datos de carrera, arena/capacidad, color ni clasificación oficial;
horas locales/UTC, asistencia, overtime, neutralidad, ronda de playoffs ni
highlights verificados. `IS_NEUTRAL_SITE` queda vacío si no llega una señal
explícita; no se deduce de `MATCHUP`. Cuando la entrada sí incluye esa señal,
se respeta sin añadir columnas al modelo. `AGE` debe calcularse en Power BI
desde `BIRTH_DATE`, no persistirse como un valor fijo. No se realizan
peticiones a servicios adicionales para fotografías, banderas o vídeos.
`FIRST_NAME` y `LAST_NAME` no forman parte del esquema final porque
`PLAYER_NAME` ya identifica al jugador. `COUNTRY_CODE` solo se conserva si
puede proceder de una fuente válida; una URL de bandera de `flagcdn.com` se
deriva automáticamente únicamente con un código ISO 3166-1 alpha-2 de dos
letras. Los demás datos personales permanecen vacíos hasta disponer de una
fuente documentada.

La falta o ambigüedad de `MATCHUP` no descarta partidos ni estadísticas. Si la
fuente confirma cancha neutral pero no localía oficial, se conserva el orden
de equipos recibido en `HOME_TEAM_ID` y `AWAY_TEAM_ID`; sin localía confirmada
ni señal neutral se usa el orden numérico de `TEAM_ID`. En ambos casos
`IS_HOME` queda vacío para no presentar esa asignación como localía real.
Los partidos neutrales y los de localía desconocida no participan en los
acumulados de rendimiento en casa o fuera, pero sí en victorias, derrotas y
partidos jugados. La localización estática de franquicias se carga sin depender
de esta extracción diaria.

No se depende de `CommonTeamRoster` para imágenes. Una futura ampliación de
fuentes debe documentar condiciones de uso y probarse en una tarea separada;
el fallo de una fuente nueva no debe borrar datos previamente válidos.

## Actualización y preservación

Las claves estables hacen que la escritura sea idempotente. Las filas vacías
recibidas no borran valores previos. Los archivos `data/old/` no se eliminan;
la migración de catálogos puede usar sus campos estáticos para completar el
modelo vigente. Los datos históricos de partidos permanecen archivados y no se
mezclan en estadísticas de 2026-27.
