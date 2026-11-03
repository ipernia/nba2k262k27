"""Persistencia acumulativa de catálogos y estadísticas en CSV."""

from __future__ import annotations

import csv
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
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
_GAME_COLUMNS = frozenset({"SEASON_ID", "GAME_DATE", "MATCHUP", "VIDEO_AVAILABLE"})
_GAME_CATALOG_COLUMNS = (
    "GAME_ID",
    "SEASON_ID",
    "GAME_DATE",
    "TEAM_ID_1",
    "TEAM_ID_2",
    "VIDEO_AVAILABLE",
)
_DEFAULT_PLAYER_FACE_URL = "assets/player_silhouette.png"
_PLAYER_CATALOG_COLUMNS = (
    "PLAYER_ID",
    "PLAYER_NAME",
    "PLAYER_FACE_URL",
    "HEIGHT",
    "WEIGHT",
    "SCHOOL",
    "INDIVIDUAL_ACHIEVEMENTS",
)
_TEAM_CATALOG_COLUMNS = (
    "TEAM_ID",
    "TEAM_ABBREVIATION",
    "TEAM_NAME",
    "TEAM_LOGO_URL",
    "PRIMARY_COLOR_RGB",
    "SECONDARY_COLOR_RGB",
    "COLOR_SOURCE_URL",
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
) -> dict[str, int]:
    """Acumula catálogos y estadísticas, normalizando temporadas existentes."""
    players = _validate_rows(player_rows, _PLAYER_REQUIRED_COLUMNS, "jugadores")
    teams = _validate_rows(team_rows, _TEAM_REQUIRED_COLUMNS, "equipos")

    player_season_entities, team_season_entities, season_tables = (
        _prepare_existing_seasons(data_directory)
    )
    player_catalog: RowsByKey = {}
    existing_player_path = data_directory / "players.csv"
    if existing_player_path.exists():
        _, existing_players = _read_existing(existing_player_path, ("PLAYER_ID",))
        for row in existing_players.values():
            if not row.get("PLAYER_FACE_URL", "").strip():
                row["PLAYER_FACE_URL"] = _DEFAULT_PLAYER_FACE_URL
            _merge_row(
                player_catalog,
                list(_PLAYER_CATALOG_COLUMNS),
                {column: row.get(column, "") for column in _PLAYER_CATALOG_COLUMNS},
                ("PLAYER_ID",),
            )
    for row in player_season_entities:
        _merge_row(
            player_catalog,
            list(_PLAYER_CATALOG_COLUMNS),
            row,
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
                "PLAYER_FACE_URL": (
                    f"https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"
                ),
            },
            ("PLAYER_ID",),
        )

    team_catalog: RowsByKey = {}
    for row in team_season_entities:
        _merge_row(
            team_catalog,
            list(_TEAM_CATALOG_COLUMNS),
            row,
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
            },
            ("TEAM_ID",),
        )

    player_stats = [
        {
            column: value
            for column, value in row.items()
            if column not in {"PLAYER_NAME", "TEAM_ABBREVIATION", "TEAM_NAME"}
        }
        for row in players
    ]
    team_stats = [
        {
            column: value
            for column, value in row.items()
            if column not in {"TEAM_ABBREVIATION", "TEAM_NAME"}
        }
        for row in teams
    ]
    existing_team_stats: list[CSVRow] = []
    team_stats_path = data_directory / "team_game_stats.csv"
    if team_stats_path.exists():
        _, existing_team_stats_by_key = _read_existing(
            team_stats_path, ("GAME_ID", "TEAM_ID")
        )
        existing_team_stats = list(existing_team_stats_by_key.values())
    if teams:
        incoming_game_ids = {_row_key(row, ("GAME_ID",))[0] for row in teams}
        existing_team_stats = [
            row
            for row in existing_team_stats
            if _row_key(row, ("GAME_ID",))[0] in incoming_game_ids
        ]
        games = _build_games(teams, existing_team_stats)
    elif not (data_directory / "games.csv").exists():
        games = _build_games([], existing_team_stats)
    else:
        games = []

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
            None,
            _GAME_COLUMNS,
        ),
        (
            "team_game_stats.csv",
            ("GAME_ID", "TEAM_ID"),
            team_stats,
            None,
            _GAME_COLUMNS,
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
) -> tuple[list[Row], list[Row], list[PreparedTable]]:
    player_entities: RowsByKey = {}
    team_entities: RowsByKey = {}
    season_tables: list[PreparedTable] = []

    player_season_path = data_directory / "player_seasons.csv"
    if player_season_path.exists():
        _, rows = _read_existing(player_season_path, _PLAYER_SEASON_KEY)
        for row in rows.values():
            player_id = _numeric_identifier(row["PLAYER_ID"], "PLAYER_ID")
            player = {
                column: row.get(column, "")
                for column in _PLAYER_CATALOG_COLUMNS
                if column not in {"PLAYER_ID", "PLAYER_FACE_URL"}
            }
            player["PLAYER_ID"] = player_id
            player["PLAYER_FACE_URL"] = (
                f"https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"
            )
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
            team = {
                "TEAM_ID": team_id,
                "TEAM_LOGO_URL": row.get("TEAM_LOGO_URL", "")
                or f"https://cdn.nba.com/logos/nba/{team_id}/primary/L/logo.svg",
                "PRIMARY_COLOR_RGB": row.get("PRIMARY_COLOR_RGB", ""),
                "SECONDARY_COLOR_RGB": row.get("SECONDARY_COLOR_RGB", ""),
                "COLOR_SOURCE_URL": row.get("COLOR_SOURCE_URL", ""),
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

        matchups: list[tuple[str, str]] = []
        metadata: tuple[str, str, str] | None = None
        for row in rows:
            matchup = _serialize_value(row["MATCHUP"]).strip()
            if " vs. " in matchup:
                first, second = matchup.split(" vs. ", maxsplit=1)
            elif " @ " in matchup:
                first, second = matchup.split(" @ ", maxsplit=1)
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
            matchups.append((first, second))
            row_metadata = tuple(
                _serialize_value(row.get(column, "")).strip()
                for column in ("SEASON_ID", "GAME_DATE", "VIDEO_AVAILABLE")
            )
            if metadata is not None and row_metadata != metadata:
                raise CSVStorageError(
                    f"El partido {game_id} tiene metadatos inconsistentes."
                )
            metadata = row_metadata

        if matchups[0] != (matchups[1][1], matchups[1][0]):
            raise CSVStorageError(
                f"El partido {game_id} tiene datos de MATCHUP inconsistentes."
            )
        team_id_1, team_id_2 = sorted(team_ids, key=int)
        season_id, game_date, video_available = metadata or ("", "", "")
        games.append(
            {
                "GAME_ID": game_id,
                "SEASON_ID": season_id,
                "GAME_DATE": game_date,
                "TEAM_ID_1": team_id_1,
                "TEAM_ID_2": team_id_2,
                "VIDEO_AVAILABLE": video_available,
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
