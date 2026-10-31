"""Persistencia acumulativa de catálogos y estadísticas en CSV."""

from __future__ import annotations

import csv
import math
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TypeAlias

Row: TypeAlias = dict[str, object]
CSVRow: TypeAlias = dict[str, str]
RowKey: TypeAlias = tuple[str, ...]
RowsByKey: TypeAlias = dict[RowKey, CSVRow]
PreparedTable: TypeAlias = tuple[Path, list[str], RowsByKey]


class CSVStorageError(RuntimeError):
    """Error al validar o guardar un archivo CSV de estadísticas."""


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
    "TEAM_ID",
    "TEAM_ABBREVIATION",
    "TEAM_NAME",
)
_TEAM_DIMENSION_COLUMNS = ("TEAM_ID", "TEAM_ABBREVIATION", "TEAM_NAME")
_PLAYER_DIMENSION_COLUMNS = ("PLAYER_ID", "PLAYER_NAME")


def save_game_logs(
    data_directory: Path,
    player_rows: Sequence[Mapping[str, object]],
    team_rows: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    """Acumula cuatro CSV relacionados para el modelo de Power BI.

    Escribe los catálogos ``players.csv`` y ``teams.csv``, y las tablas de
    estadísticas ``player_game_stats.csv`` y ``team_game_stats.csv``. La clave
    de jugador por partido incluye ``TEAM_ID`` como relación histórica con el
    equipo para el que jugó. Los antiguos ``*_game_logs.csv`` se importan si
    todavía no existe su nuevo archivo correspondiente; nunca se eliminan.

    Returns:
        Número acumulado de filas de estadísticas de jugadores y equipos.

    Raises:
        CSVStorageError: Si los registros o CSV existentes no son válidos, o
            si no se pueden escribir los archivos.
    """
    players = _validate_rows(player_rows, _PLAYER_REQUIRED_COLUMNS, "jugadores")
    teams = _validate_rows(team_rows, _TEAM_REQUIRED_COLUMNS, "equipos")

    table_specs: tuple[
        tuple[
            str,
            tuple[str, ...],
            str,
            tuple[str, ...],
            str,
            str,
            tuple[str, ...],
        ],
        ...,
    ] = (
        (
            "teams.csv",
            ("TEAM_ID",),
            "team_game_logs.csv",
            ("GAME_ID", "TEAM_ID"),
            "T",
            "teams",
            _TEAM_DIMENSION_COLUMNS,
        ),
        (
            "players.csv",
            ("PLAYER_ID",),
            "player_game_logs.csv",
            ("GAME_ID", "PLAYER_ID"),
            "P",
            "players",
            _PLAYER_DIMENSION_COLUMNS,
        ),
        (
            "team_game_stats.csv",
            ("GAME_ID", "TEAM_ID"),
            "team_game_logs.csv",
            ("GAME_ID", "TEAM_ID"),
            "T",
            "team_stats",
            (),
        ),
        (
            "player_game_stats.csv",
            ("GAME_ID", "PLAYER_ID"),
            "player_game_logs.csv",
            ("GAME_ID", "PLAYER_ID"),
            "P",
            "player_stats",
            (),
        ),
    )

    def project(kind: str, row: Mapping[str, object], columns: tuple[str, ...]) -> Row:
        if columns:
            return {column: row[column] for column in columns}
        excluded = (
            {"TEAM_ABBREVIATION", "TEAM_NAME"}
            if kind == "T"
            else {"PLAYER_NAME", "TEAM_ABBREVIATION", "TEAM_NAME"}
        )
        return {
            column: value for column, value in row.items() if column not in excluded
        }

    inputs: dict[str, list[Row]] = {
        "P": players,
        "T": teams,
    }
    inputs["teams"] = [
        project("T", row, _TEAM_DIMENSION_COLUMNS) for row in [*players, *teams]
    ]
    inputs["players"] = [
        project("P", row, _PLAYER_DIMENSION_COLUMNS) for row in players
    ]
    inputs["team_stats"] = [project("T", row, ()) for row in teams]
    inputs["player_stats"] = [project("P", row, ()) for row in players]

    prepared: list[PreparedTable] = []
    accumulated_counts: dict[str, int] = {"P": 0, "T": 0}
    for (
        filename,
        key_columns,
        legacy_filename,
        legacy_keys,
        kind,
        table_name,
        projection,
    ) in table_specs:
        legacy_path = data_directory / legacy_filename
        prepared_table, row_count = _prepare_table(
            data_directory / filename,
            key_columns,
            inputs[table_name],
            legacy_path,
            legacy_keys,
            lambda row, table_kind=kind, table_projection=projection: project(
                table_kind, row, table_projection
            ),
        )
        if prepared_table is not None:
            prepared.append(prepared_table)
        if kind in accumulated_counts:
            accumulated_counts[kind] = row_count

    _write_tables(prepared)
    return accumulated_counts


def _validate_rows(
    rows: Sequence[Mapping[str, object]],
    required_columns: tuple[str, ...],
    kind: str,
) -> list[Row]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise CSVStorageError("Los registros deben ser una secuencia de filas.")
    validated: list[Row] = []
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
        _row_key(
            row, required_columns[:2] if kind == "jugadores" else ("GAME_ID", "TEAM_ID")
        )
        validated.append(dict(row))
    return validated


def _prepare_table(
    path: Path,
    key_columns: tuple[str, ...],
    incoming_rows: Sequence[Mapping[str, object]],
    legacy_path: Path,
    legacy_key_columns: tuple[str, ...],
    transform: Callable[[Mapping[str, object]], Row],
) -> tuple[PreparedTable | None, int]:
    migrate_legacy = not path.exists() and legacy_path.exists()
    if path.exists():
        headers, existing_rows = _read_existing(path, key_columns)
    elif migrate_legacy:
        _, legacy_rows = _read_existing(legacy_path, legacy_key_columns)
        headers = []
        existing_rows = {}
        for legacy_row in legacy_rows.values():
            transformed = transform(legacy_row)
            _merge_row(existing_rows, headers, transformed, key_columns)
    else:
        headers, existing_rows = [], {}

    for row in incoming_rows:
        if any(not isinstance(column, str) or not column for column in row):
            raise CSVStorageError("Las columnas deben tener nombres válidos.")
        _merge_row(existing_rows, headers, row, key_columns)

    if not incoming_rows and not migrate_legacy:
        return None, len(existing_rows)
    if not existing_rows:
        return None, 0
    return (path, headers, existing_rows), len(existing_rows)


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
    rows_by_key[key] = {
        column: _serialize_value(row.get(column, "")) for column in headers
    }


def _row_key(row: Mapping[str, object], key_columns: tuple[str, ...]) -> RowKey:
    key = tuple(_serialize_value(row.get(column, "")).strip() for column in key_columns)
    if any(not value for value in key):
        raise CSVStorageError(
            "Las claves GAME_ID y PLAYER_ID/TEAM_ID no pueden estar vacías."
        )
    return key


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
