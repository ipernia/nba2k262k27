"""Consultas NBA para enriquecer catálogos y dimensiones de temporada."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from numbers import Integral, Real
from pathlib import Path
from typing import Protocol, runtime_checkable

from nba_stats.client import GameLogFrame

_LOGGER = logging.getLogger(__name__)
_CACHE_TTL_SECONDS = 20 * 60 * 60


class NBAEnrichmentError(RuntimeError):
    """Error al consultar o validar datos de catálogos NBA."""


@runtime_checkable
class CatalogEndpoint(Protocol):
    """Interfaz mínima de los endpoints tabulares de nba_api."""

    def get_data_frames(self) -> Sequence[object]: ...


EndpointFactory = Callable[..., CatalogEndpoint]

_SEASON_PATTERN = re.compile(r"^\d{4}-\d{2}$")
_ENDPOINT_NAMES = {
    "player_bios": "LeagueDashPlayerBioStats",
    "standings": "LeagueStandings",
    "team_details": "TeamDetails",
    "team_roster": "CommonTeamRoster",
}


def fetch_nba_catalogs(
    season: str,
    *,
    max_attempts: int = 3,
    retry_delay_seconds: float = 2,
    timeout_seconds: int = 30,
    endpoint_factory: EndpointFactory | None = None,
    cache_directory: Path | None = None,
    force_refresh: bool = False,
) -> dict[str, tuple[tuple[str, ...], list[dict[str, object]]]]:
    """Consulta datos biográficos, equipos, standings y plantillas de una temporada.

    Las respuestas se preparan en memoria; el llamador puede guardarlas solo
    cuando todas las consultas NBA se completan correctamente.
    """
    _validate_options(season, max_attempts, retry_delay_seconds, timeout_seconds)
    if endpoint_factory is None:
        endpoint_factory = _create_endpoint

    player_bios = _fetch_rows(
        endpoint_factory,
        _ENDPOINT_NAMES["player_bios"],
        {
            "season": season,
            "season_type_all_star": "Regular Season",
        },
        max_attempts,
        retry_delay_seconds,
        timeout_seconds,
        cache_directory,
        force_refresh,
    )
    standings = _fetch_rows(
        endpoint_factory,
        _ENDPOINT_NAMES["standings"],
        {"season": season, "season_type": "Regular Season"},
        max_attempts,
        retry_delay_seconds,
        timeout_seconds,
        cache_directory,
        force_refresh,
    )
    if not standings:
        raise NBAEnrichmentError(
            f"NBA.com no devolvió clasificaciones para la temporada {season}."
        )

    team_ids = sorted(
        {
            team_id
            for row in standings
            if (team_id := _identifier(_value(row, "TEAM_ID", "TeamID"))) is not None
        }
    )
    if not team_ids:
        raise NBAEnrichmentError(
            "NBA.com devolvió clasificaciones sin identificadores de equipo."
        )

    rosters: list[dict[str, object]] = []
    team_details: list[dict[str, object]] = []
    for team_id in team_ids:
        rosters.extend(
            _fetch_rows(
                endpoint_factory,
                _ENDPOINT_NAMES["team_roster"],
                {"team_id": team_id, "season": season},
                max_attempts,
                retry_delay_seconds,
                timeout_seconds,
                cache_directory,
                force_refresh,
            )
        )
        detail_rows = _fetch_rows(
            endpoint_factory,
            _ENDPOINT_NAMES["team_details"],
            {"team_id": team_id},
            max_attempts,
            retry_delay_seconds,
            timeout_seconds,
            cache_directory,
            force_refresh,
        )
        if detail_rows:
            team_details.append(detail_rows[0])

    bio_by_id = {
        player_id: row
        for row in player_bios
        if (player_id := _identifier(_value(row, "PLAYER_ID"))) is not None
    }
    team_by_id = {
        team_id: row
        for row in team_details
        if (team_id := _identifier(_value(row, "TEAM_ID"))) is not None
    }
    standings_by_id = {
        team_id: row
        for row in standings
        if (team_id := _identifier(_value(row, "TEAM_ID", "TeamID"))) is not None
    }

    player_rows: dict[str, dict[str, object]] = {}
    player_season_rows: dict[tuple[str, str], dict[str, object]] = {}
    team_rows: dict[str, dict[str, object]] = {}
    team_season_rows: dict[tuple[str, str], dict[str, object]] = {}

    for roster_row in rosters:
        player_id = _identifier(_value(roster_row, "PLAYER_ID"))
        team_id = _identifier(_value(roster_row, "TEAM_ID"))
        if player_id is None or team_id is None:
            continue
        bio = bio_by_id.get(player_id, {})
        player_name = _text(
            _value(roster_row, "PLAYER", "PLAYER_NAME") or _value(bio, "PLAYER_NAME")
        )
        player_catalog = _player_catalog_row(player_id, player_name, bio, roster_row)
        player_rows[player_id] = _merge_nonempty(
            player_rows.get(player_id, {}), player_catalog
        )
        player_season = _player_season_row(
            player_id, team_id, season, player_name, roster_row, bio
        )
        player_season_rows[(player_id, team_id)] = player_season

    for team_id in team_ids:
        standing = standings_by_id.get(team_id, {})
        details = team_by_id.get(team_id, {})
        team = _team_catalog_row(team_id, standing, details)
        team_rows[team_id] = team
        team_season_rows[(team_id, season)] = _team_season_row(
            team_id, season, standing
        )

    return {
        "players.csv": (("PLAYER_ID",), list(player_rows.values())),
        "teams.csv": (("TEAM_ID",), list(team_rows.values())),
        "player_seasons.csv": (
            ("PLAYER_ID", "TEAM_ID", "SEASON_ID"),
            list(player_season_rows.values()),
        ),
        "team_seasons.csv": (
            ("TEAM_ID", "SEASON_ID"),
            list(team_season_rows.values()),
        ),
    }


def _validate_options(
    season: str,
    max_attempts: int,
    retry_delay_seconds: float,
    timeout_seconds: int,
) -> None:
    if not isinstance(season, str) or not _SEASON_PATTERN.fullmatch(season):
        raise ValueError("La temporada debe tener el formato YYYY-YY.")
    start_year = int(season[:4])
    if (start_year + 1) % 100 != int(season[-2:]):
        raise ValueError("El año final de la temporada debe ser el siguiente.")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise ValueError("max_attempts debe ser un entero mayor que cero.")
    if max_attempts < 1:
        raise ValueError("max_attempts debe ser un entero mayor que cero.")
    if (
        isinstance(retry_delay_seconds, bool)
        or not isinstance(retry_delay_seconds, (int, float))
        or not math.isfinite(retry_delay_seconds)
        or retry_delay_seconds < 0
    ):
        raise ValueError("retry_delay_seconds debe ser un número finito no negativo.")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise ValueError("timeout_seconds debe ser un entero mayor que cero.")
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds debe ser un entero mayor que cero.")


def _create_endpoint(name: str, **kwargs: object) -> CatalogEndpoint:
    try:
        from nba_api.stats import endpoints
    except ImportError as error:
        raise NBAEnrichmentError(
            "Falta nba_api. Instala las dependencias del proyecto con "
            "'python -m pip install -e \".[dev]\"'."
        ) from error
    endpoint_class = getattr(endpoints, name, None)
    if endpoint_class is None:
        raise NBAEnrichmentError(f"El endpoint nba_api {name} no está disponible.")
    return endpoint_class(**kwargs)


def _fetch_rows(
    endpoint_factory: EndpointFactory,
    endpoint_name: str,
    parameters: Mapping[str, object],
    max_attempts: int,
    retry_delay_seconds: float,
    timeout_seconds: int,
    cache_directory: Path | None,
    force_refresh: bool,
) -> list[dict[str, object]]:
    cache_path = (
        _cache_path(cache_directory, endpoint_name, parameters)
        if cache_directory is not None
        else None
    )
    if cache_path is not None and not force_refresh:
        cached_rows = _read_cache(cache_path)
        if cached_rows is not None:
            return cached_rows

    for attempt in range(1, max_attempts + 1):
        try:
            endpoint = endpoint_factory(
                endpoint_name, timeout=timeout_seconds, **parameters
            )
            frames = endpoint.get_data_frames()
            if not frames:
                return []
            frame = frames[0]
            if not isinstance(frame, GameLogFrame):
                raise NBAEnrichmentError(
                    f"{endpoint_name} devolvió una tabla incompatible."
                )
            rows = frame.to_dict("records")
            if not isinstance(rows, list) or any(
                not isinstance(row, Mapping) for row in rows
            ):
                raise NBAEnrichmentError(
                    f"{endpoint_name} devolvió registros con formato inválido."
                )
            normalized_rows = [dict(row) for row in rows]
            if cache_path is not None:
                _write_cache(cache_path, normalized_rows)
            return normalized_rows
        except NBAEnrichmentError:
            raise
        except Exception as error:
            if attempt == max_attempts:
                raise NBAEnrichmentError(
                    f"No se pudo consultar {endpoint_name} tras {max_attempts} "
                    "intentos."
                ) from error
            time.sleep(retry_delay_seconds)
    raise NBAEnrichmentError(f"La consulta a {endpoint_name} terminó sin resultado.")


def _cache_path(
    cache_directory: Path,
    endpoint_name: str,
    parameters: Mapping[str, object],
) -> Path:
    cache_key = json.dumps(
        [endpoint_name, sorted(parameters.items())],
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    return cache_directory / f"{digest}.json"


def _read_cache(path: Path) -> list[dict[str, object]] | None:
    try:
        with path.open(encoding="utf-8") as cache_file:
            cached = json.load(cache_file)
        cached_at = cached.get("cached_at")
        rows = cached.get("rows")
        if (
            not isinstance(cached_at, (int, float))
            or time.time() - cached_at > _CACHE_TTL_SECONDS
            or not isinstance(rows, list)
            or any(not isinstance(row, dict) for row in rows)
        ):
            return None
        return rows
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as error:
        _LOGGER.warning("No se pudo leer la caché NBA %s: %s", path, error)
        return None


def _write_cache(path: Path, rows: list[dict[str, object]]) -> None:
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as cache_file:
            temporary_path = Path(cache_file.name)
            json.dump(
                {
                    "cached_at": time.time(),
                    "rows": _json_safe_value(rows),
                },
                cache_file,
                ensure_ascii=False,
                allow_nan=False,
            )
        os.replace(temporary_path, path)
    except (OSError, TypeError, ValueError) as error:
        _LOGGER.warning("No se pudo escribir la caché NBA %s: %s", path, error)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _json_safe_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_safe_value(item) for item in value]
    raise TypeError(f"Valor no compatible con JSON: {type(value).__name__}")


def _value(row: Mapping[str, object], *names: str) -> object:
    normalized = {
        str(key).replace("_", "").casefold(): value for key, value in row.items()
    }
    for name in names:
        value = normalized.get(name.replace("_", "").casefold())
        if value is not None:
            return value
    return None


def _identifier(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        value = int(value)
    identifier = str(value).strip()
    return None if identifier.casefold() in {"", "nan", "none", "<na>"} else identifier


def _text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.casefold() in {"nan", "none", "<na>"} else text


def _player_catalog_row(
    player_id: str,
    player_name: str,
    bio: Mapping[str, object],
    roster: Mapping[str, object],
) -> dict[str, object]:
    return {
        "PLAYER_ID": player_id,
        "PLAYER_NAME": player_name,
        "BIRTHDATE": _text(_value(roster, "BIRTH_DATE", "BIRTHDATE")),
        "HEIGHT": _text(_value(roster, "HEIGHT") or _value(bio, "PLAYER_HEIGHT")),
        "WEIGHT": _text(_value(roster, "WEIGHT") or _value(bio, "PLAYER_WEIGHT")),
        "POSITION": _text(_value(roster, "POSITION")),
        "COUNTRY": _text(_value(bio, "COUNTRY", "COUNTRY")),
        "SCHOOL": _text(_value(roster, "SCHOOL") or _value(bio, "COLLEGE")),
        "DRAFT_YEAR": _text(_value(bio, "DRAFT_YEAR")),
        "DRAFT_ROUND": _text(_value(bio, "DRAFT_ROUND")),
        "DRAFT_NUMBER": _text(_value(bio, "DRAFT_NUMBER")),
    }


def _player_season_row(
    player_id: str,
    team_id: str,
    season: str,
    player_name: str,
    roster: Mapping[str, object],
    bio: Mapping[str, object],
) -> dict[str, object]:
    return {
        "PLAYER_ID": player_id,
        "TEAM_ID": team_id,
        "SEASON_ID": season,
        "PLAYER_NAME": player_name,
        "JERSEY_NUM": _text(_value(roster, "NUM", "JERSEY_NUM")),
        "POSITION": _text(_value(roster, "POSITION")),
        "HEIGHT": _text(_value(roster, "HEIGHT") or _value(bio, "PLAYER_HEIGHT")),
        "WEIGHT": _text(_value(roster, "WEIGHT") or _value(bio, "PLAYER_WEIGHT")),
        "EXP": _text(_value(roster, "EXP")),
        "SCHOOL": _text(_value(roster, "SCHOOL") or _value(bio, "COLLEGE")),
    }


def _team_catalog_row(
    team_id: str,
    standing: Mapping[str, object],
    details: Mapping[str, object],
) -> dict[str, object]:
    city = _text(_value(details, "CITY"))
    nickname = _text(_value(details, "NICKNAME"))
    team_name = _text(_value(details, "TEAM_NAME")) or " ".join(
        part for part in (city, nickname) if part
    )
    return {
        "TEAM_ID": team_id,
        "TEAM_ABBREVIATION": _text(
            _value(standing, "TEAM_ABBREVIATION")
            or _value(details, "ABBREVIATION", "TEAM_ABBREVIATION")
        ),
        "TEAM_NAME": team_name,
        "CITY": city,
        "NICKNAME": nickname,
        "ARENA": _text(_value(details, "ARENA")),
        "ARENA_CAPACITY": _text(_value(details, "ARENACAPACITY")),
        "OWNER": _text(_value(details, "OWNER")),
        "GENERAL_MANAGER": _text(_value(details, "GENERALMANAGER")),
        "HEAD_COACH": _text(_value(details, "HEADCOACH")),
        "D_LEAGUE_AFFILIATION": _text(_value(details, "DLEAGUEAFFILIATION")),
    }


def _team_season_row(
    team_id: str,
    season: str,
    standing: Mapping[str, object],
) -> dict[str, object]:
    return {
        "TEAM_ID": team_id,
        "SEASON_ID": season,
        "CONFERENCE": _text(_value(standing, "CONFERENCE")),
        "DIVISION": _text(_value(standing, "DIVISION")),
        "WINS": _text(_value(standing, "WINS")),
        "LOSSES": _text(_value(standing, "LOSSES")),
        "WIN_PCT": _text(_value(standing, "WinPCT", "WIN_PCT")),
        "HOME_RECORD": _text(_value(standing, "HOME")),
        "ROAD_RECORD": _text(_value(standing, "ROAD")),
        "L10": _text(_value(standing, "L10")),
        "STREAK": _text(_value(standing, "STRK", "STREAK")),
    }


def _merge_nonempty(
    existing: Mapping[str, object], incoming: Mapping[str, object]
) -> dict[str, object]:
    merged = dict(existing)
    for key, value in incoming.items():
        if _text(value):
            merged[key] = value
    return merged
