"""Consultas al endpoint LeagueGameLog de NBA.com."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, runtime_checkable


class NBAStatsError(RuntimeError):
    """Error al solicitar o validar estadísticas de la NBA."""


@runtime_checkable
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
    "T": ("GAME_ID", "TEAM_ID", "TEAM_ABBREVIATION", "TEAM_NAME"),
}
_SEASON_PATTERN = re.compile(r"^\d{4}-\d{2}$")


def fetch_league_game_logs(
    season: str,
    *,
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
            player_or_team=player_or_team,
            endpoint_factory=endpoint_factory,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
            timeout_seconds=timeout_seconds,
        )
    return results


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
                season_type_all_star="Regular Season",
                timeout=timeout_seconds,
            )
            frames = endpoint.get_data_frames()
            if not frames:
                raise NBAStatsError("NBA.com devolvió una respuesta sin tablas.")
            frame = frames[0]
            if not isinstance(frame, GameLogFrame):
                raise NBAStatsError(
                    "NBA.com devolvió una tabla con un formato no compatible."
                )
            rows = frame.to_dict("records")
        except NBAStatsError:
            raise
        except Exception as error:
            if attempt == max_attempts:
                raise NBAStatsError(
                    f"No se pudieron descargar los registros "
                    f"{'de jugadores' if player_or_team == 'P' else 'de equipos'} "
                    f"tras {max_attempts} intentos."
                ) from error
            time.sleep(retry_delay_seconds)
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
