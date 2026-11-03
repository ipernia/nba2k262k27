# Tareas pendientes

## Hecho

- [x] Generar las URLs de caras y escudos a partir de `PLAYER_ID` y `TEAM_ID`.
- [x] Hacer opcional `CommonTeamRoster` y retirar las caras/escudos del flujo de Commons.
- [x] Actualizar CSVs, documentación e instrucciones de Python y tests.
- [x] Añadir tests unitarios para las URLs, las consultas y el manifiesto de camisetas.

## Pendiente

- [x] Ampliar datos de TEAMS que no pertenezcan a TEAM_SEASSONS. Mover los campos que deban pertenecer a la entidad TEAMS desde TEAM_SEASSONS, y dejar en esta última entidad solo los datos que sean de SEASSONS. Quitar campos innecesarios de TEAM_SEASSONS (ej. TEAM_LOGO_URL,PRIMARY_COLOR_RGB,SECONDARY_COLOR_RGB,COLOR_SOURCE_URL).
- [x] Ampliar datos de PLAYERS que no pertenezcan a PLAYER_SEASSONS. Mover los campos que deban pertenecer a la entidad PLAYERS desde PLAYERS_SEASSONS, y dejar en esta última entidad solo los datos que sean de SEASSONS. Quitar campos innecesarios de PLAYER_SEASSONS (ej. PLAYER_FACE_URL,INDIVIDUAL_ACHIEVEMENTS).
- [ ] Nuevo CSV de GAMES para quitar datos de los CSV de *_GAME_STATS y que esten aqui. Quietar los campos de 'MATCHUP', ya que en GAMES deberan aparecer los dos equipos con su ID.
- [ ] Configurar la ejecución diaria en el Programador de tareas de Windows.
