"""Persistencia acumulativa de registros de partidos en CSV."""

from __future__ import annotations

import csv
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path


class CSVStorageError(RuntimeError):
    """Error al validar o guardar un archivo CSV de estadísticas."""


_CSV_DEFINITIONS = {
    "P": ("player_game_logs.csv", ("GAME_ID", "PLAYER_ID")),
    "T": ("team_game_logs.csv", ("GAME_ID", "TEAM_ID")),
}


def save_game_logs(
    data_directory: Path,
    player_rows: Sequence[Mapping[str, object]],
    team_rows: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    """Acumula y guarda los registros de jugadores y equipos en CSV UTF-8-BOM.

    Las filas se actualizan por clave compuesta de partido y jugador/equipo.
    Una respuesta vacía no crea ni sobrescribe archivos existentes.

    Raises:
        CSVStorageError: Si los registros o CSV existentes no son válidos, o
            si no se pueden escribir los archivos.
    """
    incoming = {"P": player_rows, "T": team_rows}
    prepared: dict[
        str, tuple[Path, list[str], dict[tuple[str, ...], dict[str, str]]]
    ] = {}
    row_counts: dict[str, int] = {"P": 0, "T": 0}

    for kind, (filename, key_columns) in _CSV_DEFINITIONS.items():
        rows = _validate_rows(incoming[kind], key_columns, kind)
        path = data_directory / filename
        existing_headers, existing_rows = _read_existing(path, key_columns)
        if not rows:
            row_counts[kind] = len(existing_rows)
            continue
        headers = list(existing_headers)
        for row in rows:
            for column in row:
                if not isinstance(column, str) or not column:
                    raise CSVStorageError(
                        f"Las columnas del registro {kind} deben tener nombres válidos."
                    )
                if column not in headers:
                    headers.append(column)
        merged = dict(existing_rows)
        for row in rows:
            key = _row_key(row, key_columns)
            merged[key] = {
                column: _serialize_value(row.get(column, "")) for column in headers
            }
        prepared[kind] = (path, headers, merged)
        row_counts[kind] = len(merged)

    staged_files: list[tuple[Path, Path, str]] = []
    try:
        for kind, (path, headers, rows_by_key) in prepared.items():
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
                staged_files.append((temporary_path, path, kind))
                writer = csv.DictWriter(temporary_file, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows_by_key.values())

        for temporary_path, path, _ in staged_files:
            os.replace(temporary_path, path)
    except (OSError, UnicodeError, csv.Error, TypeError) as error:
        raise CSVStorageError(f"No se pudieron guardar los CSV: {error}") from error
    finally:
        for temporary_path, _, _ in staged_files:
            temporary_path.unlink(missing_ok=True)
    return row_counts


def _validate_rows(
    rows: Sequence[Mapping[str, object]],
    key_columns: tuple[str, ...],
    kind: str,
) -> list[dict[str, object]]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise CSVStorageError("Los registros deben ser una secuencia de filas.")
    validated: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise CSVStorageError(f"El registro {index} de {kind} no es un mapa.")
        if any(not isinstance(column, str) or not column for column in row):
            raise CSVStorageError(
                f"Las columnas del registro {kind} deben tener nombres válidos."
            )
        missing = [column for column in key_columns if column not in row]
        if missing:
            raise CSVStorageError(
                f"El registro {index} de {kind} no tiene las claves requeridas: "
                + ", ".join(missing)
            )
        _row_key(row, key_columns)
        validated.append(dict(row))
    return validated


def _row_key(
    row: Mapping[str, object], key_columns: tuple[str, ...]
) -> tuple[str, ...]:
    key = tuple(_serialize_value(row.get(column, "")).strip() for column in key_columns)
    if any(not value for value in key):
        raise CSVStorageError(
            "Las columnas de clave GAME_ID y PLAYER_ID/TEAM_ID no pueden estar vacías."
        )
    return key


def _read_existing(
    path: Path, key_columns: tuple[str, ...]
) -> tuple[list[str], dict[tuple[str, ...], dict[str, str]]]:
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
            rows: dict[tuple[str, ...], dict[str, str]] = {}
            for index, row in enumerate(reader, start=2):
                if None in row:
                    raise CSVStorageError(
                        f"El CSV existente {path} tiene columnas inesperadas "
                        f"en la línea {index}."
                    )
                normalized = {key: value or "" for key, value in row.items()}
                if any(
                    not isinstance(column, str) or not column for column in normalized
                ):
                    raise CSVStorageError(
                        f"El CSV existente {path} tiene una cabecera inválida."
                    )
                rows[_row_key(normalized, key_columns)] = normalized
            return list(reader.fieldnames), rows
    except (OSError, UnicodeError, csv.Error) as error:
        raise CSVStorageError(
            f"No se pudo leer el CSV existente {path}: {error}"
        ) from error


def _serialize_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)
