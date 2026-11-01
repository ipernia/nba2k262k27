"""Carga y valida tablas de datos revisadas manualmente."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from urllib.parse import urlsplit


class CuratedDataError(ValueError):
    """Error de formato o validación en un manifiesto curado."""


_SEASON_PATTERN = re.compile(r"^\d{4}-\d{2}$")
_COLOR_PATTERN = re.compile(r"^\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*$")


def load_team_branding_manifest(path: Path) -> dict[str, dict[str, str]]:
    """Lee RGB de equipos y fuente HTTPS desde un manifiesto curado."""
    required = {
        "TEAM_ID",
        "PRIMARY_COLOR_RGB",
        "SECONDARY_COLOR_RGB",
        "SOURCE_URL",
    }
    rows = _read_manifest(path, required)
    branding: dict[str, dict[str, str]] = {}
    for line_number, row in enumerate(rows, start=2):
        team_id = row["TEAM_ID"].strip()
        if not team_id.isdigit():
            raise CuratedDataError(f"TEAM_ID inválido en {path}, línea {line_number}.")
        if team_id in branding:
            raise CuratedDataError(
                f"TEAM_ID duplicado en {path}, línea {line_number}: {team_id}."
            )
        primary = _normalize_rgb(row["PRIMARY_COLOR_RGB"], path, line_number)
        secondary = _normalize_rgb(row["SECONDARY_COLOR_RGB"], path, line_number)
        source_url = row["SOURCE_URL"].strip()
        if primary or secondary:
            _validate_source_url(source_url, path, line_number)
        elif source_url:
            _validate_source_url(source_url, path, line_number)
        branding[team_id] = {
            "PRIMARY_COLOR_RGB": primary,
            "SECONDARY_COLOR_RGB": secondary,
            "COLOR_SOURCE_URL": source_url,
        }
    return branding


def load_player_awards_manifest(path: Path) -> list[dict[str, str]]:
    """Lee logros por jugador/temporada con enlace de procedencia."""
    required = {"PLAYER_ID", "SEASON_ID", "ACHIEVEMENT", "SOURCE_URL"}
    rows = _read_manifest(path, required)
    awards: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for line_number, row in enumerate(rows, start=2):
        player_id = row["PLAYER_ID"].strip()
        season = row["SEASON_ID"].strip()
        achievement = row["ACHIEVEMENT"].strip()
        if not player_id.isdigit():
            raise CuratedDataError(
                f"PLAYER_ID inválido en {path}, línea {line_number}."
            )
        if not _valid_season(season):
            raise CuratedDataError(
                f"SEASON_ID inválido en {path}, línea {line_number}."
            )
        if not achievement:
            raise CuratedDataError(f"ACHIEVEMENT vacío en {path}, línea {line_number}.")
        _validate_source_url(row["SOURCE_URL"].strip(), path, line_number)
        key = (player_id, season, achievement.casefold())
        if key in seen:
            raise CuratedDataError(
                f"Logro duplicado en {path}, línea {line_number}: {key}."
            )
        seen.add(key)
        awards.append(
            {
                "PLAYER_ID": player_id,
                "SEASON_ID": season,
                "ACHIEVEMENT": achievement,
                "SOURCE_URL": row["SOURCE_URL"].strip(),
            }
        )
    return awards


def apply_team_branding(
    catalogs: dict[str, tuple[tuple[str, ...], list[dict[str, object]]]],
    branding: dict[str, dict[str, str]],
) -> None:
    """Añade colores y su procedencia a las filas de temporada de equipo."""
    team_rows = catalogs["team_seasons.csv"][1]
    team_ids = {str(row["TEAM_ID"]) for row in team_rows}
    unknown_ids = sorted(set(branding) - team_ids)
    if unknown_ids:
        raise CuratedDataError(
            "El manifiesto de colores contiene equipos ausentes de la consulta: "
            + ", ".join(unknown_ids)
        )
    for row in team_rows:
        team_branding = branding.get(str(row["TEAM_ID"]))
        if team_branding is not None:
            row.update(team_branding)


def apply_player_awards(
    catalogs: dict[str, tuple[tuple[str, ...], list[dict[str, object]]]],
    awards: list[dict[str, str]],
) -> None:
    """Agrega los logros curados a la tabla por temporada de jugador."""
    achievements_by_player_season: dict[tuple[str, str], list[str]] = {}
    for award in awards:
        key = (award["PLAYER_ID"], award["SEASON_ID"])
        achievements = achievements_by_player_season.setdefault(key, [])
        if award["ACHIEVEMENT"] not in achievements:
            achievements.append(award["ACHIEVEMENT"])

    for player_season in catalogs["player_seasons.csv"][1]:
        key = (str(player_season["PLAYER_ID"]), str(player_season["SEASON_ID"]))
        achievements = achievements_by_player_season.get(key)
        if achievements:
            player_season["INDIVIDUAL_ACHIEVEMENTS"] = " | ".join(
                sorted(achievements, key=str.casefold)
            )


def _read_manifest(path: Path, required: set[str]) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            if (
                reader.fieldnames is None
                or not required.issubset(reader.fieldnames)
                or len(set(reader.fieldnames)) != len(reader.fieldnames)
            ):
                raise CuratedDataError(
                    f"El manifiesto {path} debe contener las columnas: "
                    + ", ".join(sorted(required))
                )
            result: list[dict[str, str]] = []
            for line_number, raw_row in enumerate(reader, start=2):
                if None in raw_row or any(
                    raw_row.get(column) is None for column in required
                ):
                    raise CuratedDataError(
                        f"Columnas o valores incompletos en {path}, "
                        f"línea {line_number}."
                    )
                result.append(
                    {key: (value or "").strip() for key, value in raw_row.items()}
                )
            return result
    except CuratedDataError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise CuratedDataError(
            f"No se pudo leer el manifiesto {path}: {error}"
        ) from error


def _normalize_rgb(value: str, path: Path, line_number: int) -> str:
    if not value.strip():
        return ""
    match = _COLOR_PATTERN.fullmatch(value)
    if match is None:
        raise CuratedDataError(
            f"Color RGB inválido en {path}, línea {line_number}; "
            "usa R,G,B con componentes de 0 a 255."
        )
    components = tuple(int(component) for component in match.groups())
    if any(component > 255 for component in components):
        raise CuratedDataError(
            f"Color RGB fuera de rango en {path}, línea {line_number}."
        )
    return ",".join(str(component) for component in components)


def _validate_source_url(value: str, path: Path, line_number: int) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise CuratedDataError(
            f"SOURCE_URL debe ser HTTPS en {path}, línea {line_number}."
        )


def _valid_season(season: str) -> bool:
    if not _SEASON_PATTERN.fullmatch(season):
        return False
    start_year = int(season[:4])
    return (start_year + 1) % 100 == int(season[-2:])
