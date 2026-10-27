"""Punto de entrada para descargar y actualizar los CSV de estadísticas."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from nba_stats.client import NBAStatsError, fetch_league_game_logs
from nba_stats.storage import CSVStorageError, save_game_logs


def current_season(today: date | None = None) -> str:
    """Devuelve la temporada regular que corresponde a la fecha local."""
    current_date = today or date.today()
    start_year = (
        current_date.year if current_date.month >= 10 else current_date.year - 1
    )
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def main(argv: list[str] | None = None) -> int:
    """Descarga registros de la temporada y actualiza los CSV locales."""
    parser = argparse.ArgumentParser(
        description="Descarga registros de partidos NBA a archivos CSV locales."
    )
    parser.add_argument(
        "--season",
        default=current_season(),
        help="Temporada regular con formato YYYY-YY (por defecto, la actual).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Carpeta para los CSV (por defecto: data).",
    )
    parser.add_argument(
        "--attempts", type=int, default=3, help="Intentos por consulta."
    )
    parser.add_argument("--timeout", type=int, default=30, help="Timeout en segundos.")
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=2,
        help="Espera entre reintentos, en segundos.",
    )
    args = parser.parse_args(argv)
    log_directory = Path("logs")
    try:
        log_directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(
            f"Error: no se pudo crear la carpeta de registros: {error}", file=sys.stderr
        )
        return 1
    logging.basicConfig(
        filename=log_directory / "nba_stats.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )

    try:
        game_logs = fetch_league_game_logs(
            args.season,
            max_attempts=args.attempts,
            retry_delay_seconds=args.retry_delay,
            timeout_seconds=args.timeout,
        )
        counts = save_game_logs(
            args.data_dir,
            game_logs["P"],
            game_logs["T"],
        )
    except (NBAStatsError, CSVStorageError, ValueError, OSError) as error:
        logging.exception("No se pudo actualizar la temporada %s.", args.season)
        print(f"Error: {error}", file=sys.stderr)
        return 1

    logging.info(
        "Temporada %s actualizada. Filas acumuladas: jugadores=%d, equipos=%d.",
        args.season,
        counts["P"],
        counts["T"],
    )
    print(
        f"Temporada {args.season} actualizada. Filas acumuladas: "
        f"jugadores={counts['P']}, equipos={counts['T']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
