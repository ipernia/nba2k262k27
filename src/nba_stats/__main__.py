"""Punto de entrada para descargar y actualizar los CSV de estadísticas."""

from __future__ import annotations

import argparse
import logging
import math
import sys
from datetime import date
from pathlib import Path

from nba_stats.catalog_client import NBAEnrichmentError, fetch_nba_catalogs
from nba_stats.client import NBAStatsError, fetch_league_game_logs
from nba_stats.commons import (
    CommonsAssetError,
    fetch_commons_asset,
    load_asset_manifest,
)
from nba_stats.curated_data import (
    CuratedDataError,
    apply_player_awards,
    apply_team_branding,
    load_player_awards_manifest,
    load_team_branding_manifest,
)
from nba_stats.storage import CSVStorageError, save_catalog_tables, save_game_logs


def current_season(today: date | None = None) -> str:
    """Devuelve la temporada regular que corresponde a la fecha local."""
    current_date = today or date.today()
    start_year = (
        current_date.year if current_date.month >= 10 else current_date.year - 1
    )
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def _include_logged_player_teams(
    catalogs: dict[str, tuple[tuple[str, ...], list[dict[str, object]]]],
    player_game_rows: list[dict[str, object]],
    season: str,
) -> None:
    """Incluye traspasos observados en los registros de partidos de la temporada."""
    key_columns, roster_rows = catalogs["player_seasons.csv"]
    merged = {
        (
            str(row["PLAYER_ID"]),
            str(row["TEAM_ID"]),
            str(row["SEASON_ID"]),
        ): row
        for row in roster_rows
    }
    for game_row in player_game_rows:
        player_id = _normalize_identifier(game_row.get("PLAYER_ID"))
        team_id = _normalize_identifier(game_row.get("TEAM_ID"))
        if not player_id or not team_id:
            continue
        key = (player_id, team_id, season)
        if key not in merged:
            merged[key] = {
                "PLAYER_ID": player_id,
                "TEAM_ID": team_id,
                "SEASON_ID": season,
                "PLAYER_NAME": game_row.get("PLAYER_NAME", ""),
            }
    catalogs["player_seasons.csv"] = (key_columns, list(merged.values()))


def _normalize_identifier(value: object) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return ""
        value = int(value)
    identifier = str(value).strip()
    return "" if identifier.casefold() in {"", "nan", "none", "<na>"} else identifier


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
    parser.add_argument(
        "--skip-catalogs",
        action="store_true",
        help="Actualiza solo las estadísticas por partido.",
    )
    parser.add_argument(
        "--catalogs-only",
        action="store_true",
        help="Actualiza catálogos y camisetas sin descargar estadísticas por partido.",
    )
    parser.add_argument(
        "--refresh-catalogs",
        action="store_true",
        help="Ignora la caché local de catálogos y consulta NBA.com de nuevo.",
    )
    parser.add_argument(
        "--asset-manifest",
        type=Path,
        default=Path("config") / "team_uniform_manifest.csv",
        help="Manifiesto de camisetas, caras y escudos Commons.",
    )
    parser.add_argument(
        "--team-branding-manifest",
        type=Path,
        default=Path("config") / "team_branding_manifest.csv",
        help="Manifiesto curado de colores RGB y sus fuentes.",
    )
    parser.add_argument(
        "--awards-manifest",
        type=Path,
        default=Path("config") / "player_awards_manifest.csv",
        help="Manifiesto curado de premios y logros individuales.",
    )
    args = parser.parse_args(argv)
    if args.skip_catalogs and args.catalogs_only:
        parser.error("--skip-catalogs y --catalogs-only no se pueden combinar.")
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

    stats_counts: dict[str, int] | None = None
    game_logs: dict[str, list[dict[str, object]]] | None = None
    if not args.catalogs_only:
        try:
            game_logs = fetch_league_game_logs(
                args.season,
                max_attempts=args.attempts,
                retry_delay_seconds=args.retry_delay,
                timeout_seconds=args.timeout,
            )
            stats_counts = save_game_logs(
                args.data_dir,
                game_logs["P"],
                game_logs["T"],
            )
        except (NBAStatsError, CSVStorageError, ValueError, OSError) as error:
            logging.exception("No se pudieron actualizar las estadísticas.")
            print(f"Error en estadísticas: {error}", file=sys.stderr)
            return 1

    catalog_error: Exception | None = None
    catalog_counts: dict[str, int] = {}
    asset_errors: list[str] = []
    if not args.skip_catalogs:
        try:
            catalogs = fetch_nba_catalogs(
                args.season,
                max_attempts=args.attempts,
                retry_delay_seconds=args.retry_delay,
                timeout_seconds=args.timeout,
                cache_directory=args.data_dir / ".cache" / "nba_catalogs",
                force_refresh=args.refresh_catalogs,
            )
            if game_logs is not None:
                _include_logged_player_teams(catalogs, game_logs["P"], args.season)
            asset_manifest_rows = load_asset_manifest(args.asset_manifest)
            branding = load_team_branding_manifest(args.team_branding_manifest)
            award_rows = load_player_awards_manifest(args.awards_manifest)
            apply_team_branding(catalogs, branding)
            apply_player_awards(catalogs, award_rows)
            if award_rows:
                catalogs["player_awards.csv"] = (
                    ("PLAYER_ID", "SEASON_ID", "ACHIEVEMENT"),
                    [
                        {
                            "PLAYER_ID": award["PLAYER_ID"],
                            "SEASON_ID": award["SEASON_ID"],
                            "ACHIEVEMENT": award["ACHIEVEMENT"],
                            "SOURCE_URL": award["SOURCE_URL"],
                        }
                        for award in award_rows
                    ],
                )
            catalog_counts = save_catalog_tables(args.data_dir, catalogs)

            known_team_ids = {str(row["TEAM_ID"]) for row in catalogs["teams.csv"][1]}
            known_player_ids = {
                str(row["PLAYER_ID"]) for row in catalogs["players.csv"][1]
            }
            verified_asset_rows: list[dict[str, object]] = []
            jersey_rows: list[dict[str, object]] = []
            updated_player_seasons = catalogs["player_seasons.csv"][1]
            updated_team_seasons = catalogs["team_seasons.csv"][1]
            for manifest_row in asset_manifest_rows:
                asset_type = manifest_row["ASSET_TYPE"]
                entity_id = manifest_row["ENTITY_ID"]
                if asset_type == "JERSEY" and manifest_row["SEASON_ID"] != args.season:
                    continue
                known_ids = (
                    known_player_ids if asset_type == "PLAYER_FACE" else known_team_ids
                )
                if entity_id not in known_ids:
                    message = (
                        f"{asset_type} para ENTITY_ID {entity_id} no corresponde "
                        f"a una entidad consultada para {args.season}."
                    )
                    logging.error(message)
                    print(f"Error en asset Commons: {message}", file=sys.stderr)
                    asset_errors.append(message)
                    continue
                try:
                    asset = fetch_commons_asset(
                        manifest_row["FILE_TITLE"],
                        timeout_seconds=args.timeout,
                        max_attempts=args.attempts,
                        retry_delay_seconds=args.retry_delay,
                    )
                except CommonsAssetError as error:
                    message = (
                        f"{asset_type} {entity_id} "
                        f"({manifest_row['FILE_TITLE']}): {error}"
                    )
                    logging.error("No se pudo validar el asset Commons: %s", message)
                    print(f"Error en asset Commons: {message}", file=sys.stderr)
                    asset_errors.append(message)
                    continue

                if asset_type == "PLAYER_FACE":
                    verified_asset_rows.append(
                        {
                            "ASSET_TYPE": asset_type,
                            "ENTITY_ID": entity_id,
                            "FILE_TITLE": asset.file_title,
                            "IMAGE_URL": asset.image_url,
                            "PAGE_URL": asset.page_url,
                            "MIME_TYPE": asset.mime_type,
                            "LICENSE": asset.license_name,
                            "ATTRIBUTION": asset.attribution,
                            "SOURCE": "Wikimedia Commons",
                        }
                    )
                    for player_season in updated_player_seasons:
                        if player_season["PLAYER_ID"] == entity_id:
                            player_season["PLAYER_FACE_URL"] = asset.image_url
                elif asset_type == "TEAM_LOGO":
                    verified_asset_rows.append(
                        {
                            "ASSET_TYPE": asset_type,
                            "ENTITY_ID": entity_id,
                            "FILE_TITLE": asset.file_title,
                            "IMAGE_URL": asset.image_url,
                            "PAGE_URL": asset.page_url,
                            "MIME_TYPE": asset.mime_type,
                            "LICENSE": asset.license_name,
                            "ATTRIBUTION": asset.attribution,
                            "SOURCE": "Wikimedia Commons",
                        }
                    )
                    for team_season in updated_team_seasons:
                        if team_season["TEAM_ID"] == entity_id:
                            team_season["TEAM_LOGO_URL"] = asset.image_url
                else:
                    jersey_rows.append(
                        {
                            "TEAM_ID": entity_id,
                            "SEASON_ID": manifest_row["SEASON_ID"],
                            "EDITION": manifest_row["EDITION"],
                            "FILE_TITLE": asset.file_title,
                            "IMAGE_URL": asset.image_url,
                            "PAGE_URL": asset.page_url,
                            "MIME_TYPE": asset.mime_type,
                            "LICENSE": asset.license_name,
                            "ATTRIBUTION": asset.attribution,
                            "SOURCE": "Wikimedia Commons",
                        }
                    )

            supplementary_tables: dict[
                str, tuple[tuple[str, ...], list[dict[str, object]]]
            ] = {}
            if verified_asset_rows:
                supplementary_tables["media_assets.csv"] = (
                    ("ASSET_TYPE", "ENTITY_ID"),
                    verified_asset_rows,
                )
            if jersey_rows:
                supplementary_tables["team_uniform_assets.csv"] = (
                    ("TEAM_ID", "SEASON_ID", "EDITION"),
                    jersey_rows,
                )
            if supplementary_tables:
                catalog_counts.update(
                    save_catalog_tables(args.data_dir, supplementary_tables)
                )
            catalog_counts.update(
                save_catalog_tables(
                    args.data_dir,
                    {
                        "player_seasons.csv": (
                            ("PLAYER_ID", "TEAM_ID", "SEASON_ID"),
                            updated_player_seasons,
                        ),
                        "team_seasons.csv": (
                            ("TEAM_ID", "SEASON_ID"),
                            updated_team_seasons,
                        ),
                    },
                )
            )
        except (
            CommonsAssetError,
            NBAEnrichmentError,
            CSVStorageError,
            CuratedDataError,
            ValueError,
            OSError,
        ) as error:
            catalog_error = error
            logging.exception("No se pudieron actualizar todos los catálogos.")
            print(f"Error en catálogos: {error}", file=sys.stderr)
    if stats_counts is not None:
        logging.info(
            "Estadísticas de %s guardadas: jugadores=%d, equipos=%d.",
            args.season,
            stats_counts["P"],
            stats_counts["T"],
        )
        print(
            f"Estadísticas de {args.season} guardadas: "
            f"jugadores={stats_counts['P']}, equipos={stats_counts['T']}."
        )
    if catalog_counts:
        logging.info("Catálogos actualizados: %s.", catalog_counts)
        print(f"Catálogos actualizados: {catalog_counts}.")
    return 1 if catalog_error is not None or asset_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
