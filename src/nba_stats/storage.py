"""Persistencia acumulativa de catálogos y estadísticas en CSV."""

from __future__ import annotations

import csv
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from numbers import Integral, Real
from pathlib import Path
from typing import TypeAlias

Row: TypeAlias = dict[str, object]
CSVRow: TypeAlias = dict[str, str]
RowKey: TypeAlias = tuple[str, ...]
RowsByKey: TypeAlias = dict[RowKey, CSVRow]
PreparedTable: TypeAlias = tuple[Path, list[str], RowsByKey]

_PLAYER_REQUIRED_COLUMNS = (
    "GAME_ID",
    "PLAYER_ID",
    "PLAYER_NAME",
    "TEAM_ID",
    "TEAM_ABBREVIATION",
    "TEAM_NAME",
)
_TEAM_REQUIRED_COLUMNS = (
    "GAME_ID",
    "SEASON_ID",
    "GAME_DATE",
    "MATCHUP",
    "TEAM_ID",
    "TEAM_ABBREVIATION",
    "TEAM_NAME",
)
_GAME_CATALOG_COLUMNS = (
    "GAME_ID",
    "SEASON",
    "SEASON_TYPE",
    "GAME_DATE",
    "GAME_TIME",
    "GAME_TIME_UTC",
    "GAME_STATUS",
    "HOME_TEAM_ID",
    "AWAY_TEAM_ID",
    "HOME_TEAM_SCORE",
    "AWAY_TEAM_SCORE",
    "WINNER_TEAM_ID",
    "GAME_DURATION",
    "OVERTIME_PERIODS",
    "IS_NEUTRAL_SITE",
    "ARENA_NAME",
    "ATTENDANCE",
    "PLAYOFF_ROUND",
    "YOUTUBE_HIGHLIGHTS_URL",
    "LAST_UPDATED",
)
_DEFAULT_PLAYER_FACE_URL = "assets/player_silhouette.png"
_PLAYER_CATALOG_COLUMNS = (
    "PLAYER_ID",
    "PLAYER_NAME",
    "FIRST_NAME",
    "LAST_NAME",
    "NATIONALITY",
    "COUNTRY_CODE",
    "FLAG_URL",
    "BIRTH_DATE",
    "HEIGHT_METERS",
    "WEIGHT_KG",
    "POSITION",
    "JERSEY_NUMBER",
    "PLAYER_HEADSHOT_URL",
    "COLLEGE",
    "COUNTRY_OF_ORIGIN",
    "DRAFT_YEAR",
    "DRAFT_ROUND",
    "DRAFT_NUMBER",
    "DRAFT_TEAM_ID",
    "NBA_EXPERIENCE",
    "NBA_CHAMPIONSHIPS",
    "NBA_MVP_AWARDS",
    "NBA_FINALS_MVP_AWARDS",
    "ALL_STAR_SELECTIONS",
    "IS_ACTIVE",
    "CURRENT_TEAM_ID",
    "LAST_UPDATED",
)
_TEAM_CATALOG_COLUMNS = (
    "TEAM_ID",
    "TEAM_NAME",
    "TEAM_ABBREVIATION",
    "TEAM_CITY",
    "TEAM_NICKNAME",
    "TEAM_LOGO_URL",
    "TEAM_PRIMARY_COLOR",
    "TEAM_SECONDARY_COLOR",
    "CONFERENCE",
    "DIVISION",
    "WINS",
    "LOSSES",
    "GAMES_PLAYED",
    "WIN_PCT",
    "CONFERENCE_RANK",
    "DIVISION_RANK",
    "GAMES_BACK",
    "HOME_WINS",
    "HOME_LOSSES",
    "AWAY_WINS",
    "AWAY_LOSSES",
    "NBA_CHAMPIONSHIPS",
    "ARENA_NAME",
    "ARENA_CAPACITY",
    "LAST_UPDATED",
)
_TEAM_GAME_STATS_COLUMNS = (
    "GAME_ID",
    "TEAM_ID",
    "IS_HOME",
    "TEAM_POINTS",
    "FIELD_GOALS_MADE",
    "FIELD_GOALS_ATTEMPTED",
    "FIELD_GOAL_PCT",
    "THREE_POINTS_MADE",
    "THREE_POINTS_ATTEMPTED",
    "THREE_POINT_PCT",
    "FREE_THROWS_MADE",
    "FREE_THROWS_ATTEMPTED",
    "FREE_THROW_PCT",
    "OFFENSIVE_REBOUNDS",
    "DEFENSIVE_REBOUNDS",
    "TOTAL_REBOUNDS",
    "ASSISTS",
    "STEALS",
    "BLOCKS",
    "TURNOVERS",
    "PERSONAL_FOULS",
    "PLUS_MINUS",
    "POINTS_IN_PAINT",
    "SECOND_CHANCE_POINTS",
    "FAST_BREAK_POINTS",
    "BENCH_POINTS",
    "BIGGEST_LEAD",
    "TEAM_TURNOVERS",
)
_PLAYER_GAME_STATS_COLUMNS = (
    "GAME_ID",
    "PLAYER_ID",
    "TEAM_ID",
    "IS_STARTER",
    "MINUTES",
    "POINTS",
    "FIELD_GOALS_MADE",
    "FIELD_GOALS_ATTEMPTED",
    "FIELD_GOAL_PCT",
    "THREE_POINTS_MADE",
    "THREE_POINTS_ATTEMPTED",
    "THREE_POINT_PCT",
    "FREE_THROWS_MADE",
    "FREE_THROWS_ATTEMPTED",
    "FREE_THROW_PCT",
    "OFFENSIVE_REBOUNDS",
    "DEFENSIVE_REBOUNDS",
    "TOTAL_REBOUNDS",
    "ASSISTS",
    "STEALS",
    "BLOCKS",
    "TURNOVERS",
    "PERSONAL_FOULS",
    "PLUS_MINUS",
    "DOUBLE_DOUBLES",
    "TRIPLE_DOUBLES",
    "FOULS_DRAWN",
    "POINTS_OFF_TURNOVERS",
    "POINTS_IN_PAINT",
    "SECOND_CHANCE_POINTS",
)
_PLAYER_SEASON_KEY = ("PLAYER_ID", "TEAM_ID", "SEASON_ID")
_PLAYER_SEASON_COLUMNS = (
    "PLAYER_ID",
    "TEAM_ID",
    "SEASON_ID",
    "JERSEY_NUM",
    "POSITION",
    "EXP",
)
_TEAM_SEASON_KEY = ("TEAM_ID", "SEASON_ID")
_TEAM_SEASON_COLUMNS = (
    "TEAM_ID",
    "SEASON_ID",
    "CONFERENCE",
    "DIVISION",
    "WINS",
    "LOSSES",
    "WIN_PCT",
    "HOME_RECORD",
    "ROAD_RECORD",
    "L10",
    "STREAK",
)


class CSVStorageError(RuntimeError):
    """Error al validar o guardar un archivo CSV de estadísticas."""


def save_game_logs(
    data_directory: Path,
    player_rows: Sequence[Mapping[str, object]],
    team_rows: Sequence[Mapping[str, object]],
    season: str | None = None,
    season_type: str = "Regular Season",
) -> dict[str, int]:
    """Acumula catálogos y estadísticas, normalizando temporadas existentes."""
    players = _validate_rows(player_rows, _PLAYER_REQUIRED_COLUMNS, "jugadores")
    teams = _validate_rows(team_rows, _TEAM_REQUIRED_COLUMNS, "equipos")
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    player_season_entities, team_season_entities, season_tables = (
        _prepare_existing_seasons(data_directory)
    )
    player_catalog: RowsByKey = {}
    existing_player_path = data_directory / "players.csv"
    if existing_player_path.exists():
        _, existing_players = _read_existing(existing_player_path, ("PLAYER_ID",))
        for row in existing_players.values():
            headshot = (
                row.get("PLAYER_HEADSHOT_URL", "").strip()
                or row.get("PLAYER_FACE_URL", "").strip()
                or _DEFAULT_PLAYER_FACE_URL
            )
            _merge_row(
                player_catalog,
                list(_PLAYER_CATALOG_COLUMNS),
                _map_existing_player(row, headshot),
                ("PLAYER_ID",),
            )
    for row in player_season_entities:
        _merge_row(
            player_catalog,
            list(_PLAYER_CATALOG_COLUMNS),
            row,
            ("PLAYER_ID",),
        )
    archived_players_path = data_directory / "old" / "players.csv"
    if archived_players_path.exists():
        _, archived_players = _read_existing(archived_players_path, ("PLAYER_ID",))
        for row in archived_players.values():
            player_id = _numeric_identifier(row["PLAYER_ID"], "PLAYER_ID")
            _merge_row(
                player_catalog,
                list(_PLAYER_CATALOG_COLUMNS),
                _map_existing_player(
                    row,
                    row.get("PLAYER_FACE_URL", "").strip()
                    or f"https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png",
                ),
                ("PLAYER_ID",),
            )
    for row in players:
        player_id = _numeric_identifier(row["PLAYER_ID"], "PLAYER_ID")
        _merge_row(
            player_catalog,
            list(_PLAYER_CATALOG_COLUMNS),
            {
                "PLAYER_ID": player_id,
                "PLAYER_NAME": row["PLAYER_NAME"],
                "PLAYER_HEADSHOT_URL": (
                    f"https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"
                ),
                "LAST_UPDATED": updated_at,
            },
            ("PLAYER_ID",),
        )

    team_catalog: RowsByKey = {}
    existing_team_path = data_directory / "teams.csv"
    if existing_team_path.exists():
        _, existing_teams = _read_existing(existing_team_path, ("TEAM_ID",))
        for row in existing_teams.values():
            _merge_row(
                team_catalog,
                list(_TEAM_CATALOG_COLUMNS),
                _map_existing_team(row),
                ("TEAM_ID",),
            )
    for row in team_season_entities:
        _merge_row(
            team_catalog,
            list(_TEAM_CATALOG_COLUMNS),
            row,
            ("TEAM_ID",),
        )
    archived_teams_path = data_directory / "old" / "teams.csv"
    if archived_teams_path.exists():
        _, archived_teams = _read_existing(archived_teams_path, ("TEAM_ID",))
        for row in archived_teams.values():
            _merge_row(
                team_catalog,
                list(_TEAM_CATALOG_COLUMNS),
                _map_existing_team(row),
                ("TEAM_ID",),
            )
    for row in teams:
        team_id = _numeric_identifier(row["TEAM_ID"], "TEAM_ID")
        _merge_row(
            team_catalog,
            list(_TEAM_CATALOG_COLUMNS),
            {
                "TEAM_ID": team_id,
                "TEAM_ABBREVIATION": row["TEAM_ABBREVIATION"],
                "TEAM_NAME": row["TEAM_NAME"],
                "TEAM_LOGO_URL": (
                    f"https://cdn.nba.com/logos/nba/{team_id}/primary/L/logo.svg"
                ),
                "LAST_UPDATED": updated_at,
            },
            ("TEAM_ID",),
        )

    player_stats: list[Row] = []
    existing_player_stats_path = data_directory / "player_game_stats.csv"
    if existing_player_stats_path.exists():
        _, existing_player_stats_by_key = _read_existing(
            existing_player_stats_path, ("GAME_ID", "PLAYER_ID")
        )
        player_stats.extend(
            _map_player_game_row(row) for row in existing_player_stats_by_key.values()
        )
    player_stats.extend(_map_player_game_row(row) for row in players)

    team_stats: list[Row] = []
    existing_team_stats: list[CSVRow] = []
    team_stats_path = data_directory / "team_game_stats.csv"
    if team_stats_path.exists():
        _, existing_team_stats_by_key = _read_existing(
            team_stats_path, ("GAME_ID", "TEAM_ID")
        )
        existing_team_stats = list(existing_team_stats_by_key.values())
        team_stats.extend(_map_team_game_row(row) for row in existing_team_stats)
    team_stats.extend(_map_team_game_row(row) for row in teams)
    games_path = data_directory / "games.csv"
    if teams:
        incoming_game_ids = {_row_key(row, ("GAME_ID",))[0] for row in teams}
        game_team_rows = [
            row
            for row in existing_team_stats
            if _row_key(row, ("GAME_ID",))[0] in incoming_game_ids
        ]
        known_games = _migrate_games(data_directory) if games_path.exists() else []
        known_by_id: RowsByKey = {}
        game_headers: list[str] = list(_GAME_CATALOG_COLUMNS)
        for row in known_games:
            _merge_row(known_by_id, game_headers, row, ("GAME_ID",))
        known_game_types = {
            key[0]: row.get("SEASON_TYPE", "") for key, row in known_by_id.items()
        }
        updated_games = _build_games(
            teams,
            game_team_rows,
            season,
            season_type,
            known_game_types,
            updated_at,
        )
        for row in updated_games:
            _merge_row(known_by_id, game_headers, row, ("GAME_ID",))
        games = list(known_by_id.values())
    elif games_path.exists():
        games = _migrate_games(data_directory)
    else:
        games = _build_games([], existing_team_stats, season, season_type)
    if season:
        _update_team_records(team_catalog, team_stats, games, season, updated_at)

    tables = (
        (
            "players.csv",
            ("PLAYER_ID",),
            list(player_catalog.values()),
            _PLAYER_CATALOG_COLUMNS,
            frozenset(),
        ),
        (
            "teams.csv",
            ("TEAM_ID",),
            list(team_catalog.values()),
            _TEAM_CATALOG_COLUMNS,
            frozenset(),
        ),
        (
            "games.csv",
            ("GAME_ID",),
            games,
            _GAME_CATALOG_COLUMNS,
            frozenset(),
        ),
        (
            "player_game_stats.csv",
            ("GAME_ID", "PLAYER_ID"),
            player_stats,
            _PLAYER_GAME_STATS_COLUMNS,
            frozenset(),
        ),
        (
            "team_game_stats.csv",
            ("GAME_ID", "TEAM_ID"),
            team_stats,
            _TEAM_GAME_STATS_COLUMNS,
            frozenset(),
        ),
    )
    prepared: list[PreparedTable] = []
    counts = {"P": 0, "T": 0}
    for filename, key_columns, rows, fixed_columns, excluded_columns in tables:
        table = _prepare_table(
            data_directory / filename,
            key_columns,
            rows,
            fixed_columns,
            excluded_columns,
        )
        if table is not None:
            prepared.append(table)
            if filename == "player_game_stats.csv":
                counts["P"] = len(table[2])
            elif filename == "team_game_stats.csv":
                counts["T"] = len(table[2])
    prepared.extend(season_tables)
    _write_tables(prepared)
    return counts


def _prepare_existing_seasons(
    data_directory: Path,
) -> tuple[list[CSVRow], list[CSVRow], list[PreparedTable]]:
    player_entities: RowsByKey = {}
    team_entities: RowsByKey = {}
    season_tables: list[PreparedTable] = []

    player_season_path = data_directory / "player_seasons.csv"
    if player_season_path.exists():
        _, rows = _read_existing(player_season_path, _PLAYER_SEASON_KEY)
        for row in rows.values():
            player_id = _numeric_identifier(row["PLAYER_ID"], "PLAYER_ID")
            player = _map_existing_player(
                row,
                row.get("PLAYER_HEADSHOT_URL", "").strip()
                or row.get("PLAYER_FACE_URL", "").strip()
                or f"https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png",
            )
            player["PLAYER_ID"] = player_id
            height_meters = _height_to_meters(row.get("HEIGHT", ""))
            weight_kg = _pounds_to_kilograms(row.get("WEIGHT", ""))
            if height_meters:
                player["HEIGHT_METERS"] = height_meters
            if weight_kg:
                player["WEIGHT_KG"] = weight_kg
            if row.get("SCHOOL", "").strip():
                player["COLLEGE"] = row["SCHOOL"].strip()
            if row.get("POSITION", "").strip():
                player["POSITION"] = row["POSITION"]
            if row.get("JERSEY_NUM", "").strip():
                player["JERSEY_NUMBER"] = row["JERSEY_NUM"]
            _merge_row(
                player_entities,
                list(_PLAYER_CATALOG_COLUMNS),
                player,
                ("PLAYER_ID",),
            )
        table = _prepare_table(
            player_season_path,
            _PLAYER_SEASON_KEY,
            [],
            _PLAYER_SEASON_COLUMNS,
        )
        if table is not None:
            season_tables.append(table)

    team_season_path = data_directory / "team_seasons.csv"
    if team_season_path.exists():
        _, rows = _read_existing(team_season_path, _TEAM_SEASON_KEY)
        for row in rows.values():
            team_id = _numeric_identifier(row["TEAM_ID"], "TEAM_ID")
            wins = row.get("WINS", "").strip()
            losses = row.get("LOSSES", "").strip()
            games_played = ""
            if wins and losses:
                try:
                    games_played = str(int(wins) + int(losses))
                except ValueError:
                    games_played = ""
            team = {
                "TEAM_ID": team_id,
                "TEAM_LOGO_URL": row.get("TEAM_LOGO_URL", "")
                or f"https://cdn.nba.com/logos/nba/{team_id}/primary/L/logo.svg",
                "TEAM_PRIMARY_COLOR": _rgb_to_hex(row.get("PRIMARY_COLOR_RGB", "")),
                "TEAM_SECONDARY_COLOR": _rgb_to_hex(row.get("SECONDARY_COLOR_RGB", "")),
                "CONFERENCE": row.get("CONFERENCE", ""),
                "DIVISION": row.get("DIVISION", ""),
                "WINS": wins,
                "LOSSES": losses,
                "GAMES_PLAYED": games_played,
                "WIN_PCT": row.get("WIN_PCT", ""),
            }
            _merge_row(
                team_entities,
                list(_TEAM_CATALOG_COLUMNS),
                team,
                ("TEAM_ID",),
            )
        table = _prepare_table(
            team_season_path,
            _TEAM_SEASON_KEY,
            [],
            _TEAM_SEASON_COLUMNS,
        )
        if table is not None:
            season_tables.append(table)

    return list(player_entities.values()), list(team_entities.values()), season_tables


def _build_games(
    team_rows: Sequence[Mapping[str, object]],
    existing_team_rows: Sequence[Mapping[str, object]],
    season: str | None = None,
    season_type: str = "Regular Season",
    known_game_types: Mapping[str, str] | None = None,
    updated_at: str = "",
) -> list[Row]:
    rows_by_key: RowsByKey = {}
    headers: list[str] = []
    for row in existing_team_rows:
        _merge_row(rows_by_key, headers, row, ("GAME_ID", "TEAM_ID"))
    for row in team_rows:
        _merge_row(rows_by_key, headers, row, ("GAME_ID", "TEAM_ID"))

    games_by_id: dict[str, list[Mapping[str, object]]] = {}
    for row in rows_by_key.values():
        game_id = _serialize_value(row["GAME_ID"]).strip()
        games_by_id.setdefault(game_id, []).append(row)

    games: list[Row] = []
    for game_id, rows in games_by_id.items():
        if len(rows) != 2:
            raise CSVStorageError(
                f"El partido {game_id} debe tener exactamente dos equipos."
            )
        team_ids = {_numeric_identifier(row["TEAM_ID"], "TEAM_ID") for row in rows}
        if len(team_ids) != 2:
            raise CSVStorageError(
                f"El partido {game_id} debe tener dos TEAM_ID distintos."
            )

        matchups: list[tuple[str, str, str, str]] = []
        metadata: tuple[str, str] | None = None
        score_by_team: dict[str, str] = {}
        for row in rows:
            matchup = _serialize_value(row["MATCHUP"]).strip()
            if " vs. " in matchup:
                first, second = matchup.split(" vs. ", maxsplit=1)
                home_away = "HOME"
            elif " @ " in matchup:
                first, second = matchup.split(" @ ", maxsplit=1)
                home_away = "AWAY"
            else:
                raise CSVStorageError(
                    f"El partido {game_id} tiene un MATCHUP inválido: {matchup!r}."
                )
            own_abbreviation = str(row.get("TEAM_ABBREVIATION", "")).strip()
            if own_abbreviation and first != own_abbreviation:
                raise CSVStorageError(
                    f"El partido {game_id} tiene un MATCHUP que no coincide "
                    "con sus equipos."
                )
            team_id = _numeric_identifier(row["TEAM_ID"], "TEAM_ID")
            matchups.append((first, second, home_away, team_id))
            score_by_team[team_id] = _serialize_value(row.get("PTS", "")).strip()
            row_metadata = (
                _serialize_value(row.get("SEASON_ID", "")).strip(),
                _serialize_value(row.get("GAME_DATE", "")).strip(),
            )
            if metadata is not None and row_metadata != metadata:
                raise CSVStorageError(
                    f"El partido {game_id} tiene metadatos inconsistentes."
                )
            metadata = row_metadata

        if (matchups[0][0], matchups[0][1]) != (
            matchups[1][1],
            matchups[1][0],
        ):
            raise CSVStorageError(
                f"El partido {game_id} tiene datos de MATCHUP inconsistentes."
            )
        home_rows = [row for row in matchups if row[2] == "HOME"]
        away_rows = [row for row in matchups if row[2] == "AWAY"]
        if len(home_rows) != 1 or len(away_rows) != 1:
            raise CSVStorageError(
                f"El partido {game_id} no identifica localía de forma inequívoca."
            )
        home_team_id = home_rows[0][3]
        away_team_id = away_rows[0][3]
        season_id, game_date = metadata or ("", "")
        season_value = season or _season_from_id(season_id)
        home_score = score_by_team.get(home_team_id, "")
        away_score = score_by_team.get(away_team_id, "")
        winner_team_id = ""
        if home_score and away_score:
            try:
                home_points = int(float(home_score))
                away_points = int(float(away_score))
            except ValueError:
                home_points = away_points = 0
            if home_points > away_points:
                winner_team_id = home_team_id
            elif away_points > home_points:
                winner_team_id = away_team_id
        game_status = "Finalizado" if winner_team_id else ""
        games.append(
            {
                "GAME_ID": game_id,
                "SEASON": season_value,
                "SEASON_TYPE": (known_game_types or {}).get(game_id, "") or season_type,
                "GAME_DATE": game_date,
                "GAME_STATUS": game_status,
                "HOME_TEAM_ID": home_team_id,
                "AWAY_TEAM_ID": away_team_id,
                "HOME_TEAM_SCORE": home_score,
                "AWAY_TEAM_SCORE": away_score,
                "WINNER_TEAM_ID": winner_team_id,
                "IS_NEUTRAL_SITE": "",
                "LAST_UPDATED": updated_at,
            }
        )
    return games


def _validate_rows(
    rows: Sequence[Mapping[str, object]],
    required_columns: tuple[str, ...],
    kind: str,
) -> list[Row]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise CSVStorageError("Los registros deben ser una secuencia de filas.")
    validated: list[Row] = []
    key_columns = (
        ("GAME_ID", "PLAYER_ID") if kind == "jugadores" else ("GAME_ID", "TEAM_ID")
    )
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise CSVStorageError(f"El registro {index} de {kind} no es un mapa.")
        if any(not isinstance(column, str) or not column for column in row):
            raise CSVStorageError(
                f"Las columnas del registro de {kind} deben tener nombres válidos."
            )
        missing = [column for column in required_columns if column not in row]
        if missing:
            raise CSVStorageError(
                f"El registro {index} de {kind} no tiene las columnas requeridas: "
                + ", ".join(missing)
            )
        _row_key(row, key_columns)
        normalized = dict(row)
        id_column = "PLAYER_ID" if kind == "jugadores" else "TEAM_ID"
        normalized[id_column] = _numeric_identifier(row[id_column], id_column)
        normalized["TEAM_ID"] = _numeric_identifier(row["TEAM_ID"], "TEAM_ID")
        validated.append(normalized)
    return validated


def _season_from_id(season_id: str) -> str:
    if len(season_id) == 5 and season_id.isdigit():
        start_year = int(season_id[1:])
        if season_id[0] in {"2", "4", "5"}:
            return f"{start_year}-{(start_year + 1) % 100:02d}"
    return season_id


def _season_type_from_id(season_id: str) -> str:
    if len(season_id) == 5 and season_id.isdigit():
        if season_id[0] == "2":
            return "Regular Season"
        if season_id[0] in {"4", "5"}:
            return "Playoffs"
    return ""


def _update_team_records(
    teams: RowsByKey,
    team_stats: Sequence[Mapping[str, object]],
    games: Sequence[Mapping[str, object]],
    season: str,
    updated_at: str,
) -> None:
    games_by_id = {
        _serialize_value(game.get("GAME_ID", "")).strip(): game for game in games
    }
    records: dict[str, dict[str, int]] = {}
    for stats in team_stats:
        game_id = _serialize_value(stats.get("GAME_ID", "")).strip()
        game = games_by_id.get(game_id)
        if (
            game is None
            or _serialize_value(game.get("SEASON", "")).strip() != season
            or _serialize_value(game.get("SEASON_TYPE", "")).strip() != "Regular Season"
            or not _serialize_value(game.get("WINNER_TEAM_ID", "")).strip()
        ):
            continue
        team_id = _serialize_value(stats.get("TEAM_ID", "")).strip()
        if not team_id:
            continue
        record = records.setdefault(
            team_id,
            {
                "WINS": 0,
                "LOSSES": 0,
                "HOME_WINS": 0,
                "HOME_LOSSES": 0,
                "AWAY_WINS": 0,
                "AWAY_LOSSES": 0,
                "HOME_GAMES": 0,
                "AWAY_GAMES": 0,
                "GAMES_PLAYED": 0,
            },
        )
        is_win = _serialize_value(game.get("WINNER_TEAM_ID", "")).strip() == team_id
        result = "WINS" if is_win else "LOSSES"
        record[result] += 1
        record["GAMES_PLAYED"] += 1
        location = _serialize_value(stats.get("IS_HOME", "")).strip()
        if location == "True":
            record["HOME_GAMES"] += 1
            record["HOME_WINS" if is_win else "HOME_LOSSES"] += 1
        elif location == "False":
            record["AWAY_GAMES"] += 1
            record["AWAY_WINS" if is_win else "AWAY_LOSSES"] += 1

    for team_id, record in records.items():
        key = (team_id,)
        if key not in teams or record["GAMES_PLAYED"] == 0:
            continue
        games_played = record["GAMES_PLAYED"]
        record_row = {
            "TEAM_ID": team_id,
            **{name: str(record[name]) for name in ("WINS", "LOSSES", "GAMES_PLAYED")},
            "WIN_PCT": f"{record['WINS'] / games_played:.3f}",
            "LAST_UPDATED": updated_at,
        }
        if record["HOME_GAMES"] + record["AWAY_GAMES"] == games_played:
            for name in (
                "HOME_WINS",
                "HOME_LOSSES",
                "AWAY_WINS",
                "AWAY_LOSSES",
            ):
                record_row[name] = str(record[name])
        _merge_row(teams, list(_TEAM_CATALOG_COLUMNS), record_row, ("TEAM_ID",))


def _map_existing_player(row: Mapping[str, object], headshot: str) -> CSVRow:
    mapped = {
        "PLAYER_ID": _serialize_value(row.get("PLAYER_ID", "")).strip(),
        "PLAYER_NAME": _serialize_value(row.get("PLAYER_NAME", "")).strip(),
        "PLAYER_HEADSHOT_URL": headshot,
    }
    for column in _PLAYER_CATALOG_COLUMNS:
        value = _serialize_value(row.get(column, "")).strip()
        if value:
            mapped[column] = value
    mapped["PLAYER_HEADSHOT_URL"] = headshot

    height_meters = _height_to_meters(row.get("HEIGHT", ""))
    weight_kg = _pounds_to_kilograms(row.get("WEIGHT", ""))
    college = _serialize_value(row.get("SCHOOL", "")).strip()
    jersey_number = _serialize_value(row.get("JERSEY_NUM", "")).strip()
    if height_meters and not mapped.get("HEIGHT_METERS"):
        mapped["HEIGHT_METERS"] = height_meters
    if weight_kg and not mapped.get("WEIGHT_KG"):
        mapped["WEIGHT_KG"] = weight_kg
    if college and not mapped.get("COLLEGE"):
        mapped["COLLEGE"] = college
    if jersey_number and not mapped.get("JERSEY_NUMBER"):
        mapped["JERSEY_NUMBER"] = jersey_number
    return mapped


def _map_existing_team(row: Mapping[str, object]) -> CSVRow:
    team_id = _serialize_value(row.get("TEAM_ID", "")).strip()
    mapped = {
        "TEAM_ID": team_id,
        "TEAM_ABBREVIATION": _serialize_value(row.get("TEAM_ABBREVIATION", "")).strip(),
        "TEAM_NAME": _serialize_value(row.get("TEAM_NAME", "")).strip(),
        "TEAM_LOGO_URL": (
            _serialize_value(row.get("TEAM_LOGO_URL", "")).strip()
            or f"https://cdn.nba.com/logos/nba/{team_id}/primary/L/logo.svg"
        ),
    }
    for column in _TEAM_CATALOG_COLUMNS:
        value = _serialize_value(row.get(column, "")).strip()
        if value:
            mapped[column] = value
    arena_name = _serialize_value(row.get("ARENA", "")).strip()
    primary_color = _rgb_to_hex(row.get("PRIMARY_COLOR_RGB", ""))
    secondary_color = _rgb_to_hex(row.get("SECONDARY_COLOR_RGB", ""))
    if arena_name and not mapped.get("ARENA_NAME"):
        mapped["ARENA_NAME"] = arena_name
    if primary_color and not mapped.get("TEAM_PRIMARY_COLOR"):
        mapped["TEAM_PRIMARY_COLOR"] = primary_color
    if secondary_color and not mapped.get("TEAM_SECONDARY_COLOR"):
        mapped["TEAM_SECONDARY_COLOR"] = secondary_color
    return mapped


def _height_to_meters(value: object) -> str:
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", _serialize_value(value))
    if not match:
        return ""
    feet, inches = (int(part) for part in match.groups())
    if inches > 11:
        return ""
    return f"{(feet * 12 + inches) * 0.0254:.2f}"


def _pounds_to_kilograms(value: object) -> str:
    text = _serialize_value(value).strip()
    if not text.isdigit():
        return ""
    return f"{int(text) * 0.45359237:.2f}"


def _rgb_to_hex(value: object) -> str:
    text = _serialize_value(value).strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", text):
        return text.upper()
    match = re.fullmatch(
        r"\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*",
        text,
    )
    if not match:
        return ""
    channels = [int(channel) for channel in match.groups()]
    if any(channel > 255 for channel in channels):
        return ""
    return "#{:02X}{:02X}{:02X}".format(*channels)


def _map_team_game_row(row: Mapping[str, object]) -> Row:
    matchup = _serialize_value(row.get("MATCHUP", "")).strip()
    is_home = _stat_value(row, "IS_HOME")
    if not is_home:
        if " vs. " in matchup:
            is_home = "True"
        elif " @ " in matchup:
            is_home = "False"
    return {
        "GAME_ID": _stat_value(row, "GAME_ID"),
        "TEAM_ID": _stat_value(row, "TEAM_ID"),
        "IS_HOME": is_home,
        "TEAM_POINTS": _stat_value(row, "TEAM_POINTS", "PTS"),
        "FIELD_GOALS_MADE": _stat_value(row, "FIELD_GOALS_MADE", "FGM"),
        "FIELD_GOALS_ATTEMPTED": _stat_value(row, "FIELD_GOALS_ATTEMPTED", "FGA"),
        "FIELD_GOAL_PCT": _stat_value(row, "FIELD_GOAL_PCT", "FG_PCT"),
        "THREE_POINTS_MADE": _stat_value(row, "THREE_POINTS_MADE", "FG3M"),
        "THREE_POINTS_ATTEMPTED": _stat_value(row, "THREE_POINTS_ATTEMPTED", "FG3A"),
        "THREE_POINT_PCT": _stat_value(row, "THREE_POINT_PCT", "FG3_PCT"),
        "FREE_THROWS_MADE": _stat_value(row, "FREE_THROWS_MADE", "FTM"),
        "FREE_THROWS_ATTEMPTED": _stat_value(row, "FREE_THROWS_ATTEMPTED", "FTA"),
        "FREE_THROW_PCT": _stat_value(row, "FREE_THROW_PCT", "FT_PCT"),
        "OFFENSIVE_REBOUNDS": _stat_value(row, "OFFENSIVE_REBOUNDS", "OREB"),
        "DEFENSIVE_REBOUNDS": _stat_value(row, "DEFENSIVE_REBOUNDS", "DREB"),
        "TOTAL_REBOUNDS": _stat_value(row, "TOTAL_REBOUNDS", "REB"),
        "ASSISTS": _stat_value(row, "ASSISTS", "AST"),
        "STEALS": _stat_value(row, "STEALS", "STL"),
        "BLOCKS": _stat_value(row, "BLOCKS", "BLK"),
        "TURNOVERS": _stat_value(row, "TURNOVERS", "TOV"),
        "PERSONAL_FOULS": _stat_value(row, "PERSONAL_FOULS", "PF"),
        "PLUS_MINUS": _serialize_value(row.get("PLUS_MINUS", "")).strip(),
        "POINTS_IN_PAINT": _stat_value(row, "POINTS_IN_PAINT"),
        "SECOND_CHANCE_POINTS": _stat_value(row, "SECOND_CHANCE_POINTS"),
        "FAST_BREAK_POINTS": _stat_value(row, "FAST_BREAK_POINTS"),
        "BENCH_POINTS": _stat_value(row, "BENCH_POINTS"),
        "BIGGEST_LEAD": _stat_value(row, "BIGGEST_LEAD"),
        "TEAM_TURNOVERS": _stat_value(row, "TEAM_TURNOVERS"),
    }


def _migrate_games(data_directory: Path) -> list[CSVRow]:
    game_headers, game_rows = _read_existing(
        data_directory / "games.csv",
        ("GAME_ID",),
    )
    if {"SEASON", "HOME_TEAM_ID", "AWAY_TEAM_ID"}.issubset(game_headers):
        return list(game_rows.values())

    team_stats_path = data_directory / "team_game_stats.csv"
    scores: dict[str, dict[str, str]] = {}
    if team_stats_path.exists():
        _, team_rows = _read_existing(team_stats_path, ("GAME_ID", "TEAM_ID"))
        for row in team_rows.values():
            game_id = _serialize_value(row.get("GAME_ID", "")).strip()
            team_id = _serialize_value(row.get("TEAM_ID", "")).strip()
            scores.setdefault(game_id, {})[team_id] = _serialize_value(
                row.get("PTS", "")
            ).strip()

    migrated: list[CSVRow] = []
    for key, row in game_rows.items():
        game_id = key[0] if isinstance(key, tuple) else str(key)
        season_id = _serialize_value(row.get("SEASON_ID", "")).strip()
        season = _season_from_id(season_id)
        team_id_1 = _serialize_value(row.get("TEAM_ID_1", "")).strip()
        team_id_2 = _serialize_value(row.get("TEAM_ID_2", "")).strip()
        team_scores = scores.get(game_id, {})
        score_1 = team_scores.get(team_id_1, "")
        score_2 = team_scores.get(team_id_2, "")
        winner_team_id = ""
        if score_1 and score_2:
            try:
                if int(float(score_1)) > int(float(score_2)):
                    winner_team_id = team_id_1
                elif int(float(score_2)) > int(float(score_1)):
                    winner_team_id = team_id_2
            except ValueError:
                winner_team_id = ""
        migrated.append(
            {
                "GAME_ID": game_id,
                "SEASON": season,
                "SEASON_TYPE": _season_type_from_id(season_id),
                "GAME_DATE": _serialize_value(row.get("GAME_DATE", "")).strip(),
                "GAME_STATUS": "Finalizado" if winner_team_id else "",
                "HOME_TEAM_ID": "",
                "AWAY_TEAM_ID": "",
                "HOME_TEAM_SCORE": "",
                "AWAY_TEAM_SCORE": "",
                "WINNER_TEAM_ID": winner_team_id,
                "IS_NEUTRAL_SITE": "",
            }
        )
    return migrated


def _map_player_game_row(row: Mapping[str, object]) -> Row:
    return {
        "GAME_ID": _stat_value(row, "GAME_ID"),
        "PLAYER_ID": _stat_value(row, "PLAYER_ID"),
        "TEAM_ID": _stat_value(row, "TEAM_ID"),
        "IS_STARTER": _stat_value(row, "IS_STARTER"),
        "MINUTES": _stat_value(row, "MINUTES", "MIN"),
        "POINTS": _stat_value(row, "POINTS", "PTS"),
        "FIELD_GOALS_MADE": _stat_value(row, "FIELD_GOALS_MADE", "FGM"),
        "FIELD_GOALS_ATTEMPTED": _stat_value(row, "FIELD_GOALS_ATTEMPTED", "FGA"),
        "FIELD_GOAL_PCT": _stat_value(row, "FIELD_GOAL_PCT", "FG_PCT"),
        "THREE_POINTS_MADE": _stat_value(row, "THREE_POINTS_MADE", "FG3M"),
        "THREE_POINTS_ATTEMPTED": _stat_value(row, "THREE_POINTS_ATTEMPTED", "FG3A"),
        "THREE_POINT_PCT": _stat_value(row, "THREE_POINT_PCT", "FG3_PCT"),
        "FREE_THROWS_MADE": _stat_value(row, "FREE_THROWS_MADE", "FTM"),
        "FREE_THROWS_ATTEMPTED": _stat_value(row, "FREE_THROWS_ATTEMPTED", "FTA"),
        "FREE_THROW_PCT": _stat_value(row, "FREE_THROW_PCT", "FT_PCT"),
        "OFFENSIVE_REBOUNDS": _stat_value(row, "OFFENSIVE_REBOUNDS", "OREB"),
        "DEFENSIVE_REBOUNDS": _stat_value(row, "DEFENSIVE_REBOUNDS", "DREB"),
        "TOTAL_REBOUNDS": _stat_value(row, "TOTAL_REBOUNDS", "REB"),
        "ASSISTS": _stat_value(row, "ASSISTS", "AST"),
        "STEALS": _stat_value(row, "STEALS", "STL"),
        "BLOCKS": _stat_value(row, "BLOCKS", "BLK"),
        "TURNOVERS": _stat_value(row, "TURNOVERS", "TOV"),
        "PERSONAL_FOULS": _stat_value(row, "PERSONAL_FOULS", "PF"),
        "PLUS_MINUS": _serialize_value(row.get("PLUS_MINUS", "")).strip(),
        "DOUBLE_DOUBLES": _stat_value(row, "DOUBLE_DOUBLES"),
        "TRIPLE_DOUBLES": _stat_value(row, "TRIPLE_DOUBLES"),
        "FOULS_DRAWN": _stat_value(row, "FOULS_DRAWN"),
        "POINTS_OFF_TURNOVERS": _stat_value(row, "POINTS_OFF_TURNOVERS"),
        "POINTS_IN_PAINT": _stat_value(row, "POINTS_IN_PAINT"),
        "SECOND_CHANCE_POINTS": _stat_value(row, "SECOND_CHANCE_POINTS"),
    }


def _stat_value(row: Mapping[str, object], *columns: str) -> str:
    for column in columns:
        value = _serialize_value(row.get(column, "")).strip()
        if value:
            return value
    return ""


def _prepare_table(
    path: Path,
    key_columns: tuple[str, ...],
    incoming_rows: Sequence[Mapping[str, object]],
    fixed_columns: tuple[str, ...] | None,
    excluded_columns: frozenset[str] = frozenset(),
) -> PreparedTable | None:
    headers, existing_rows = _read_existing(path, key_columns)
    if excluded_columns:
        headers = [column for column in headers if column not in excluded_columns]
        existing_rows = {
            key: {
                column: value
                for column, value in row.items()
                if column not in excluded_columns
            }
            for key, row in existing_rows.items()
        }
    if fixed_columns is not None:
        headers = list(fixed_columns)
        existing_rows = {
            key: {column: row.get(column, "") for column in fixed_columns}
            for key, row in existing_rows.items()
        }

    for row in incoming_rows:
        _merge_row(
            existing_rows,
            headers,
            {
                column: value
                for column, value in row.items()
                if column not in excluded_columns
            },
            key_columns,
        )

    if not incoming_rows and not path.exists():
        return None
    if not headers:
        return None
    return path, headers, existing_rows


def _merge_row(
    rows_by_key: RowsByKey,
    headers: list[str],
    row: Mapping[str, object],
    key_columns: tuple[str, ...],
) -> None:
    key = _row_key(row, key_columns)
    for column in row:
        if column not in headers:
            headers.append(column)
    merged = dict(rows_by_key.get(key, {}))
    for column in headers:
        value = _serialize_value(row.get(column, ""))
        if value.strip():
            merged[column] = value
        else:
            merged.setdefault(column, "")
    rows_by_key[key] = merged


def _row_key(row: Mapping[str, object], key_columns: tuple[str, ...]) -> RowKey:
    key = tuple(_serialize_value(row.get(column, "")).strip() for column in key_columns)
    if any(not value for value in key):
        raise CSVStorageError(
            f"Las claves {', '.join(key_columns)} no pueden estar vacías."
        )
    return key


def _numeric_identifier(value: object, column: str) -> str:
    if isinstance(value, bool) or value is None:
        raise CSVStorageError(f"{column} debe ser un identificador numérico.")
    if isinstance(value, Integral):
        identifier = str(int(value))
    elif isinstance(value, Real):
        number = float(value)
        if not math.isfinite(number) or not number.is_integer():
            raise CSVStorageError(f"{column} debe ser un identificador numérico.")
        identifier = str(int(number))
    else:
        identifier = str(value).strip()
    if not identifier.isdigit():
        raise CSVStorageError(f"{column} debe ser un identificador numérico.")
    return identifier


def _read_existing(
    path: Path, key_columns: tuple[str, ...]
) -> tuple[list[str], RowsByKey]:
    if not path.exists():
        return [], {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            if reader.fieldnames is None:
                raise CSVStorageError(f"El CSV existente está vacío: {path}")
            if any(not column for column in reader.fieldnames):
                raise CSVStorageError(
                    f"El CSV existente {path} tiene una cabecera inválida."
                )
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise CSVStorageError(
                    f"El CSV existente {path} tiene columnas duplicadas."
                )
            missing = [
                column for column in key_columns if column not in reader.fieldnames
            ]
            if missing:
                raise CSVStorageError(
                    f"El CSV existente {path} no tiene las columnas: "
                    + ", ".join(missing)
                )
            rows: RowsByKey = {}
            for index, row in enumerate(reader, start=2):
                if None in row:
                    raise CSVStorageError(
                        f"El CSV existente {path} tiene columnas inesperadas "
                        f"en la línea {index}."
                    )
                normalized = {key: value or "" for key, value in row.items()}
                rows[_row_key(normalized, key_columns)] = normalized
            return list(reader.fieldnames), rows
    except (OSError, UnicodeError, csv.Error) as error:
        raise CSVStorageError(
            f"No se pudo leer el CSV existente {path}: {error}"
        ) from error


def _write_tables(tables: Sequence[PreparedTable]) -> None:
    staged_files: list[tuple[Path, Path]] = []
    try:
        for path, headers, rows_by_key in tables:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8-sig",
                newline="",
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                staged_files.append((temporary_path, path))
                writer = csv.DictWriter(temporary_file, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows_by_key.values())

        for temporary_path, path in staged_files:
            os.replace(temporary_path, path)
    except (OSError, UnicodeError, csv.Error, TypeError) as error:
        raise CSVStorageError(f"No se pudieron guardar los CSV: {error}") from error
    finally:
        for temporary_path, _ in staged_files:
            temporary_path.unlink(missing_ok=True)


def _serialize_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)
