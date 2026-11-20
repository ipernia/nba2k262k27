"""Consultas al endpoint LeagueGameLog de NBA.com."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Protocol, TypeGuard

import pycountry


class NBAStatsError(RuntimeError):
    """Error al solicitar o validar estadísticas de la NBA."""


class GameLogFrame(Protocol):
    """Interfaz mínima del resultado tabular entregado por nba_api."""

    def to_dict(self, orient: str) -> list[dict[str, object]]: ...


class GameLogEndpoint(Protocol):
    """Interfaz mínima del endpoint LeagueGameLog."""

    def get_data_frames(self) -> Sequence[object]: ...


EndpointFactory = Callable[..., GameLogEndpoint]

_REQUIRED_COLUMNS = {
    "P": (
        "GAME_ID",
        "PLAYER_ID",
        "PLAYER_NAME",
        "TEAM_ID",
        "TEAM_ABBREVIATION",
        "TEAM_NAME",
    ),
    "T": (
        "GAME_ID",
        "SEASON_ID",
        "GAME_DATE",
        "TEAM_ID",
        "TEAM_ABBREVIATION",
        "TEAM_NAME",
    ),
}
_SEASON_PATTERN = re.compile(r"^\d{4}-\d{2}$")
_STANDINGS_ALIASES = (
    ("TEAM_ID", "TeamID"),
    ("CONFERENCE_RANK", "ConferenceRank", "CONF_RANK", "PlayoffRank"),
    ("DIVISION_RANK", "DIV_RANK", "DivisionRank"),
    ("GAMES_BACK", "GB", "ConferenceGamesBack"),
)
_PLAYER_INFO_COLUMNS = (
    "PERSON_ID",
    "COUNTRY",
    "BIRTHDATE",
    "HEIGHT",
    "WEIGHT",
    "POSITION",
    "JERSEY",
)


def fetch_league_game_logs(
    season: str,
    *,
    season_type: str = "Regular Season",
    max_attempts: int = 3,
    retry_delay_seconds: float = 2,
    timeout_seconds: int = 30,
    endpoint_factory: EndpointFactory | None = None,
) -> dict[str, list[dict[str, object]]]:
    """Descarga los registros de jugador y equipo para una temporada regular.

    Reintenta cada consulta fallida hasta ``max_attempts`` veces. El parámetro
    ``endpoint_factory`` permite probar la función sin realizar solicitudes web.

    Raises:
        ValueError: Si la temporada o los parámetros de reintento no son válidos.
        NBAStatsError: Si falla una consulta o la respuesta no tiene el formato
            esperado.
    """
    _validate_request_options(
        season, max_attempts, retry_delay_seconds, timeout_seconds
    )
    if season_type not in ("Regular Season", "Playoffs"):
        raise ValueError("season_type debe ser Regular Season o Playoffs.")
    if endpoint_factory is None:
        try:
            from nba_api.stats.endpoints import LeagueGameLog
        except ImportError as error:
            raise NBAStatsError(
                "Falta nba_api. Instala las dependencias del proyecto con "
                "'python -m pip install -e \".[dev]\"'."
            ) from error
        endpoint_factory = LeagueGameLog

    results: dict[str, list[dict[str, object]]] = {}
    for player_or_team in ("P", "T"):
        results[player_or_team] = _fetch_one_game_log(
            season=season,
            season_type=season_type,
            player_or_team=player_or_team,
            endpoint_factory=endpoint_factory,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
            timeout_seconds=timeout_seconds,
        )
    return results


def fetch_league_standings(
    season: str,
    *,
    max_attempts: int = 3,
    retry_delay_seconds: float = 2,
    timeout_seconds: int = 30,
    endpoint_factory: EndpointFactory | None = None,
) -> list[dict[str, object]]:
    """Descarga la clasificación de temporada regular para una temporada."""
    _validate_request_options(
        season, max_attempts, retry_delay_seconds, timeout_seconds
    )
    if endpoint_factory is None:
        try:
            from nba_api.stats.endpoints import LeagueStandings
        except ImportError as error:
            raise NBAStatsError(
                "Falta nba_api. Instala las dependencias del proyecto con "
                "'python -m pip install -e \".[dev]\"'."
            ) from error
        endpoint_factory = LeagueStandings

    for attempt in range(1, max_attempts + 1):
        try:
            endpoint = endpoint_factory(
                league_id="00",
                season=season,
                season_type="Regular Season",
                timeout=timeout_seconds,
            )
            frames = endpoint.get_data_frames()
            if not frames:
                raise NBAStatsError("NBA.com devolvió una respuesta sin tablas.")
            rows = []
            for frame in frames:
                if not _is_game_log_frame(frame):
                    continue
                candidate_rows = frame.to_dict("records")
                if candidate_rows and _has_standings_columns(candidate_rows):
                    rows = candidate_rows
                    break
        except NBAStatsError:
            raise
        except Exception as error:
            status_code = _http_status(error)
            if not _is_retryable(error, status_code):
                raise NBAStatsError(
                    f"Falló la consulta de clasificación"
                    f"{f' (HTTP {status_code})' if status_code else ''}; "
                    "el error no admite reintento."
                ) from error
            if attempt == max_attempts:
                raise NBAStatsError(
                    "No se pudo descargar la clasificación tras "
                    f"{max_attempts} intentos."
                ) from error
            time.sleep(_retry_delay(error, retry_delay_seconds, attempt))
            continue

        if not isinstance(rows, list) or any(
            not isinstance(row, Mapping) for row in rows
        ):
            raise NBAStatsError("NBA.com devolvió registros con un formato inválido.")
        if not rows or not _has_standings_columns(rows):
            raise NBAStatsError("La clasificación no contiene las columnas requeridas.")
        return [
            {
                canonical: _first_value(row, aliases)
                for canonical, *aliases in _STANDINGS_ALIASES
            }
            for row in rows
        ]

    raise NBAStatsError("La consulta terminó sin un resultado válido.")


def fetch_player_info(
    player_ids: Sequence[object],
    *,
    max_attempts: int = 3,
    retry_delay_seconds: float = 2,
    timeout_seconds: int = 30,
    endpoint_factory: EndpointFactory | None = None,
) -> list[dict[str, object]]:
    """Descarga los campos de perfil requeridos de CommonPlayerInfo.

    CommonPlayerInfo devuelve el país como texto, no un código ISO; se conserva
    ese texto en ``NATIONALITY`` y se convierte a ISO 3166-1 alpha-2.
    """
    _validate_retry_options(max_attempts, retry_delay_seconds, timeout_seconds)
    if endpoint_factory is None:
        try:
            from nba_api.stats.endpoints import CommonPlayerInfo
        except ImportError as error:
            raise NBAStatsError(
                "Falta nba_api. Instala las dependencias del proyecto con "
                "'python -m pip install -e \".[dev]\"'."
            ) from error
        endpoint_factory = CommonPlayerInfo

    results = []
    seen_player_ids: set[str] = set()
    for raw_player_id in player_ids:
        if isinstance(raw_player_id, bool) or not str(raw_player_id).isdigit():
            raise ValueError("PLAYER_ID debe ser un identificador numérico.")
        player_id = str(raw_player_id)
        if player_id in seen_player_ids:
            continue
        seen_player_ids.add(player_id)
        results.append(
            _fetch_player_info(
                player_id=player_id,
                endpoint_factory=endpoint_factory,
                max_attempts=max_attempts,
                retry_delay_seconds=retry_delay_seconds,
                timeout_seconds=timeout_seconds,
            )
        )
    return results


def _fetch_player_info(
    *,
    player_id: str,
    endpoint_factory: EndpointFactory,
    max_attempts: int,
    retry_delay_seconds: float,
    timeout_seconds: int,
) -> dict[str, object]:
    for attempt in range(1, max_attempts + 1):
        try:
            endpoint = endpoint_factory(
                player_id=player_id,
                timeout=timeout_seconds,
            )
            frames = endpoint.get_data_frames()
            rows = []
            if frames:
                for frame in frames:
                    if not _is_game_log_frame(frame):
                        continue
                    candidate_rows = frame.to_dict("records")
                    if candidate_rows and all(
                        column in candidate_rows[0] for column in _PLAYER_INFO_COLUMNS
                    ):
                        rows = candidate_rows
                        break
            if not rows:
                raise NBAStatsError(
                    "CommonPlayerInfo no devolvió el perfil completo del jugador "
                    f"{player_id}."
                )
            returned_player_id = str(rows[0]["PERSON_ID"]).strip()
            if returned_player_id != player_id:
                raise NBAStatsError(
                    "CommonPlayerInfo devolvió un PLAYER_ID inesperado: "
                    f"{returned_player_id} (solicitado: {player_id})."
                )
            country_value = rows[0]["COUNTRY"]
            country = "" if country_value is None else str(country_value).strip()
            if country.casefold() in {"nan", "<na>"}:
                country = ""
            result: dict[str, object] = {
                "PLAYER_ID": player_id,
                "NATIONALITY": country,
            }
            result.update(
                {column: rows[0][column] for column in _PLAYER_INFO_COLUMNS[2:]}
            )
            if country:
                try:
                    result["COUNTRY_CODE"] = pycountry.countries.lookup(country).alpha_2
                except LookupError:
                    pass
            return result
        except NBAStatsError:
            raise
        except Exception as error:
            status_code = _http_status(error)
            if not _is_retryable(error, status_code):
                raise NBAStatsError(
                    f"Falló CommonPlayerInfo para el jugador {player_id}"
                    f"{f' (HTTP {status_code})' if status_code else ''}; "
                    "el error no admite reintento."
                ) from error
            if attempt == max_attempts:
                raise NBAStatsError(
                    "No se pudo descargar CommonPlayerInfo para el jugador "
                    f"{player_id} tras {max_attempts} intentos."
                ) from error
            time.sleep(_retry_delay(error, retry_delay_seconds, attempt))
    raise NBAStatsError(
        f"CommonPlayerInfo terminó sin un resultado válido para {player_id}."
    )


def _has_standings_columns(rows: Sequence[Mapping[str, object]]) -> bool:
    return all(
        any(alias in row for row in rows for alias in aliases)
        for aliases in _STANDINGS_ALIASES
    )


def _is_game_log_frame(value: object) -> TypeGuard[GameLogFrame]:
    return callable(getattr(value, "to_dict", None))


def _first_value(row: Mapping[str, object], aliases: Sequence[str]) -> object:
    for alias in aliases:
        if alias in row:
            return row[alias]
    return ""


def _validate_request_options(
    season: str,
    max_attempts: int,
    retry_delay_seconds: float,
    timeout_seconds: int,
) -> None:
    if not isinstance(season, str) or not _SEASON_PATTERN.fullmatch(season):
        raise ValueError(
            "La temporada debe tener el formato YYYY-YY, por ejemplo 2025-26."
        )
    start_year = int(season[:4])
    if start_year < 1 or (start_year + 1) % 100 != int(season[-2:]):
        raise ValueError(
            "El año final de la temporada debe ser el siguiente al inicial."
        )
    _validate_retry_options(max_attempts, retry_delay_seconds, timeout_seconds)


def _validate_retry_options(
    max_attempts: int,
    retry_delay_seconds: float,
    timeout_seconds: int,
) -> None:
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise ValueError("max_attempts debe ser un entero mayor que cero.")
    if max_attempts < 1:
        raise ValueError("max_attempts debe ser un entero mayor que cero.")
    if (
        isinstance(retry_delay_seconds, bool)
        or not isinstance(retry_delay_seconds, (int, float))
        or not math.isfinite(retry_delay_seconds)
    ):
        raise ValueError("retry_delay_seconds debe ser un número finito no negativo.")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds no puede ser negativo.")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise ValueError("timeout_seconds debe ser un entero mayor que cero.")
    if timeout_seconds < 1:
        raise ValueError("timeout_seconds debe ser un entero mayor que cero.")


def _fetch_one_game_log(
    *,
    season: str,
    season_type: str,
    player_or_team: str,
    endpoint_factory: EndpointFactory,
    max_attempts: int,
    retry_delay_seconds: float,
    timeout_seconds: int,
) -> list[dict[str, object]]:
    for attempt in range(1, max_attempts + 1):
        try:
            endpoint = endpoint_factory(
                player_or_team_abbreviation=player_or_team,
                season=season,
                season_type_all_star=season_type,
                timeout=timeout_seconds,
            )
            frames = endpoint.get_data_frames()
            if not frames:
                raise NBAStatsError("NBA.com devolvió una respuesta sin tablas.")
            frame = frames[0]
            if not _is_game_log_frame(frame):
                raise NBAStatsError(
                    "NBA.com devolvió una tabla con un formato no compatible."
                )
            rows = frame.to_dict("records")
        except NBAStatsError:
            raise
        except Exception as error:
            status_code = _http_status(error)
            if not _is_retryable(error, status_code):
                raise NBAStatsError(
                    f"Falló la consulta de "
                    f"{'jugadores' if player_or_team == 'P' else 'equipos'}"
                    f"{f' (HTTP {status_code})' if status_code else ''}; "
                    "el error no admite reintento."
                ) from error
            if attempt == max_attempts:
                raise NBAStatsError(
                    f"No se pudieron descargar los registros "
                    f"{'de jugadores' if player_or_team == 'P' else 'de equipos'} "
                    f"tras {max_attempts} intentos."
                ) from error
            time.sleep(_retry_delay(error, retry_delay_seconds, attempt))
            continue

        if not isinstance(rows, list) or any(
            not isinstance(row, Mapping) for row in rows
        ):
            raise NBAStatsError("NBA.com devolvió registros con un formato inválido.")
        required_columns = _REQUIRED_COLUMNS[player_or_team]
        for row in rows:
            missing = [column for column in required_columns if column not in row]
            if missing:
                raise NBAStatsError(
                    "La respuesta de NBA.com no contiene las columnas requeridas: "
                    + ", ".join(missing)
                )
        return [dict(row) for row in rows]

    raise NBAStatsError("La consulta terminó sin un resultado válido.")


def _http_status(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None) or getattr(
        error, "status_code", None
    )
    return status if isinstance(status, int) else None


def _is_retryable(error: Exception, status_code: int | None) -> bool:
    if status_code is not None:
        return status_code == 429 or 500 <= status_code <= 599
    retryable_names = {
        "ConnectTimeout",
        "ConnectionError",
        "ReadTimeout",
        "Timeout",
        "TimeoutError",
    }
    return any(base.__name__ in retryable_names for base in type(error).__mro__)


def _retry_delay(error: Exception, base_delay: float, attempt: int) -> float:
    headers = getattr(getattr(error, "response", None), "headers", None)
    if headers is None:
        headers = getattr(error, "headers", None)
    retry_after = headers.get("Retry-After") if headers else None
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(
                    0.0,
                    (retry_at - datetime.now(timezone.utc)).total_seconds(),
                )
            except (TypeError, ValueError, OverflowError):
                pass
    return base_delay * 2 ** (attempt - 1)
