import csv
from datetime import date
from pathlib import Path

import pytest

from nba_stats.__main__ import (
    _include_logged_player_teams,
    current_season,
    main,
)
from nba_stats.catalog_client import NBAEnrichmentError
from nba_stats.client import NBAStatsError, fetch_league_game_logs
from nba_stats.commons import CommonsAsset, CommonsAssetError


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self.rows


class FakeEndpoint:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def get_data_frames(self) -> list[FakeFrame]:
        return [FakeFrame(self.rows)]


def make_fake_endpoint(rows: list[dict[str, object]], **kwargs: object) -> FakeEndpoint:
    assert "season" in kwargs
    return FakeEndpoint(rows)


def test_fetches_player_and_team_logs_with_expected_parameters() -> None:
    calls: list[dict[str, object]] = []

    def endpoint_factory(**kwargs: object) -> FakeEndpoint:
        calls.append(kwargs)
        if kwargs["player_or_team_abbreviation"] == "P":
            return FakeEndpoint(
                [
                    {
                        "GAME_ID": "001",
                        "PLAYER_ID": 23,
                        "PLAYER_NAME": "Player One",
                        "TEAM_ID": 1,
                        "TEAM_ABBREVIATION": "TST",
                        "TEAM_NAME": "Test Team",
                    }
                ]
            )
        return FakeEndpoint(
            [
                {
                    "GAME_ID": "001",
                    "TEAM_ID": 1,
                    "TEAM_ABBREVIATION": "TST",
                    "TEAM_NAME": "Test Team",
                }
            ]
        )

    result = fetch_league_game_logs("2025-26", endpoint_factory=endpoint_factory)

    assert result["P"][0]["PLAYER_ID"] == 23
    assert result["T"][0]["TEAM_ID"] == 1
    assert [call["player_or_team_abbreviation"] for call in calls] == ["P", "T"]
    assert all(call["season_type_all_star"] == "Regular Season" for call in calls)
    assert all(call["timeout"] == 30 for call in calls)


def test_retries_a_failed_request(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def endpoint_factory(**kwargs: object) -> FakeEndpoint:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("network timeout")
        if kwargs["player_or_team_abbreviation"] == "P":
            return FakeEndpoint(
                [
                    {
                        "GAME_ID": "001",
                        "PLAYER_ID": 23,
                        "PLAYER_NAME": "Player One",
                        "TEAM_ID": 1,
                        "TEAM_ABBREVIATION": "TST",
                        "TEAM_NAME": "Test Team",
                    }
                ]
            )
        return FakeEndpoint(
            [
                {
                    "GAME_ID": "001",
                    "TEAM_ID": 1,
                    "TEAM_ABBREVIATION": "TST",
                    "TEAM_NAME": "Test Team",
                }
            ]
        )

    delays: list[float] = []
    monkeypatch.setattr("nba_stats.client.time.sleep", delays.append)

    fetch_league_game_logs(
        "2025-26",
        max_attempts=2,
        retry_delay_seconds=0.25,
        endpoint_factory=endpoint_factory,
    )

    assert attempts == 3
    assert delays == [0.25]


def test_raises_after_retry_limit() -> None:
    calls = 0

    def endpoint_factory(**kwargs: object) -> FakeEndpoint:
        nonlocal calls
        calls += 1
        assert kwargs["season"] == "2025-26"
        raise TimeoutError("network timeout")

    with pytest.raises(NBAStatsError, match="tras 2 intentos"):
        fetch_league_game_logs(
            "2025-26", max_attempts=2, endpoint_factory=endpoint_factory
        )
    assert calls == 2


@pytest.mark.parametrize(
    "season",
    ["2025", "2025-27", "not-a-season"],
)
def test_rejects_invalid_seasons(season: str) -> None:
    with pytest.raises(ValueError):
        fetch_league_game_logs(
            season,
            endpoint_factory=lambda **kwargs: make_fake_endpoint([], **kwargs),
        )


def test_rejects_invalid_retry_options() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        fetch_league_game_logs(
            "2025-26",
            max_attempts=0,
            endpoint_factory=lambda **kwargs: make_fake_endpoint([], **kwargs),
        )
    with pytest.raises(ValueError, match="retry_delay_seconds"):
        fetch_league_game_logs(
            "2025-26",
            retry_delay_seconds=-0.1,
            endpoint_factory=lambda **kwargs: make_fake_endpoint([], **kwargs),
        )
    with pytest.raises(ValueError, match="max_attempts"):
        fetch_league_game_logs(
            "2025-26",
            max_attempts=True,
            endpoint_factory=lambda **kwargs: make_fake_endpoint([], **kwargs),
        )


def test_rejects_response_missing_identifier() -> None:
    with pytest.raises(NBAStatsError, match="PLAYER_ID"):
        fetch_league_game_logs(
            "2025-26",
            endpoint_factory=lambda **kwargs: make_fake_endpoint(
                [{"GAME_ID": "001", "TEAM_ID": 1}], **kwargs
            ),
        )


def test_rejects_response_without_data_frames() -> None:
    class EmptyEndpoint:
        def get_data_frames(self) -> list[FakeFrame]:
            return []

    def endpoint_factory(**kwargs: object) -> EmptyEndpoint:
        assert "season" in kwargs
        return EmptyEndpoint()

    with pytest.raises(NBAStatsError, match="sin tablas"):
        fetch_league_game_logs("2025-26", endpoint_factory=endpoint_factory)


@pytest.mark.parametrize(
    ("month", "expected_season"),
    [(9, "2025-26"), (10, "2026-27"), (1, "2025-26")],
)
def test_current_season_changes_in_october(month: int, expected_season: str) -> None:
    assert current_season(date(2026, month, 1)) == expected_season


def test_main_reports_log_directory_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_mkdir(path: Path, *args: object, **kwargs: object) -> None:
        assert path == Path("logs")
        assert not args
        assert kwargs == {"parents": True, "exist_ok": True}
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    assert main([]) == 1
    assert "no se pudo crear la carpeta de registros" in capsys.readouterr().err


def test_main_keeps_updated_game_stats_when_catalog_refresh_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    def fake_fetch_game_logs(
        season: str, **kwargs: object
    ) -> dict[str, list[dict[str, object]]]:
        assert season == "2026-27"
        assert kwargs["max_attempts"] == 3
        return {
            "P": [
                {
                    "GAME_ID": "001",
                    "PLAYER_ID": 23,
                    "PLAYER_NAME": "Player One",
                    "TEAM_ID": 1,
                    "TEAM_ABBREVIATION": "TST",
                    "TEAM_NAME": "Test Team",
                    "PTS": 10,
                }
            ],
            "T": [
                {
                    "GAME_ID": "001",
                    "TEAM_ID": 1,
                    "TEAM_ABBREVIATION": "TST",
                    "TEAM_NAME": "Test Team",
                    "PTS": 100,
                }
            ],
        }

    monkeypatch.setattr(
        "nba_stats.__main__.fetch_league_game_logs",
        fake_fetch_game_logs,
    )

    def fail_catalogs(season: str, **kwargs: object) -> None:
        assert season == "2026-27"
        assert kwargs["timeout_seconds"] == 30
        raise NBAEnrichmentError("catalog service unavailable")

    monkeypatch.setattr("nba_stats.__main__.fetch_nba_catalogs", fail_catalogs)

    data_directory = tmp_path / "data"
    assert main(["--season", "2026-27", "--data-dir", str(data_directory)]) == 1

    assert (data_directory / "player_game_stats.csv").exists()
    assert "catalog service unavailable" in capsys.readouterr().err


def test_logged_teams_add_player_trade_history() -> None:
    catalogs: dict[str, tuple[tuple[str, ...], list[dict[str, object]]]] = {
        "player_seasons.csv": (
            ("PLAYER_ID", "TEAM_ID", "SEASON_ID"),
            [
                {
                    "PLAYER_ID": "23",
                    "TEAM_ID": "1",
                    "SEASON_ID": "2025-26",
                    "PLAYER_NAME": "Player One",
                }
            ],
        )
    }

    _include_logged_player_teams(
        catalogs,
        [
            {
                "PLAYER_ID": 23,
                "TEAM_ID": 2.0,
                "PLAYER_NAME": "Player One",
            }
        ],
        "2025-26",
    )

    rows = catalogs["player_seasons.csv"][1]
    assert {(row["PLAYER_ID"], row["TEAM_ID"]) for row in rows} == {
        ("23", "1"),
        ("23", "2"),
    }


def test_catalogs_only_updates_catalog_csvs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_game_log_request(season: str, **kwargs: object) -> None:
        raise AssertionError(f"Unexpected game-log request: {season} {kwargs}")

    def fake_catalog_fetch(
        season: str, **kwargs: object
    ) -> dict[str, tuple[tuple[str, ...], list[dict[str, object]]]]:
        assert season == "2025-26"
        assert kwargs["force_refresh"] is False
        return {
            "players.csv": (
                ("PLAYER_ID",),
                [{"PLAYER_ID": "23", "PLAYER_NAME": "Player One"}],
            ),
            "teams.csv": (
                ("TEAM_ID",),
                [{"TEAM_ID": "1", "TEAM_NAME": "Test Team"}],
            ),
            "player_seasons.csv": (
                ("PLAYER_ID", "TEAM_ID", "SEASON_ID"),
                [
                    {
                        "PLAYER_ID": "23",
                        "TEAM_ID": "1",
                        "SEASON_ID": "2025-26",
                    }
                ],
            ),
            "team_seasons.csv": (
                ("TEAM_ID", "SEASON_ID"),
                [{"TEAM_ID": "1", "SEASON_ID": "2025-26"}],
            ),
        }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "nba_stats.__main__.fetch_league_game_logs", unexpected_game_log_request
    )
    monkeypatch.setattr("nba_stats.__main__.fetch_nba_catalogs", fake_catalog_fetch)
    manifest_path = tmp_path / "manifest.csv"
    manifest_path.write_text(
        "ASSET_TYPE,ENTITY_ID,SEASON_ID,EDITION,FILE_TITLE\n",
        encoding="utf-8",
    )
    branding_path = tmp_path / "branding.csv"
    branding_path.write_text(
        "TEAM_ID,PRIMARY_COLOR_RGB,SECONDARY_COLOR_RGB,SOURCE_URL\n",
        encoding="utf-8",
    )
    awards_path = tmp_path / "awards.csv"
    awards_path.write_text(
        "PLAYER_ID,SEASON_ID,ACHIEVEMENT,SOURCE_URL\n",
        encoding="utf-8",
    )
    data_directory = tmp_path / "data"

    assert (
        main(
            [
                "--catalogs-only",
                "--season",
                "2025-26",
                "--data-dir",
                str(data_directory),
                "--asset-manifest",
                str(manifest_path),
                "--team-branding-manifest",
                str(branding_path),
                "--awards-manifest",
                str(awards_path),
            ]
        )
        == 0
    )

    assert (data_directory / "players.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    assert (data_directory / "team_seasons.csv").exists()
    assert not (data_directory / "player_game_stats.csv").exists()


def test_catalogs_only_applies_media_colors_and_curated_awards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogs = {
        "players.csv": (
            ("PLAYER_ID",),
            [{"PLAYER_ID": "23", "PLAYER_NAME": "Player One"}],
        ),
        "teams.csv": (
            ("TEAM_ID",),
            [{"TEAM_ID": "1", "TEAM_NAME": "Test Team"}],
        ),
        "player_seasons.csv": (
            ("PLAYER_ID", "TEAM_ID", "SEASON_ID"),
            [
                {
                    "PLAYER_ID": "23",
                    "TEAM_ID": "1",
                    "SEASON_ID": "2025-26",
                }
            ],
        ),
        "team_seasons.csv": (
            ("TEAM_ID", "SEASON_ID"),
            [{"TEAM_ID": "1", "SEASON_ID": "2025-26"}],
        ),
    }

    def fake_catalog_fetch(
        season: str, **kwargs: object
    ) -> dict[str, tuple[tuple[str, ...], list[dict[str, object]]]]:
        assert season == "2025-26"
        assert kwargs["max_attempts"] == 3
        return catalogs

    calls: list[str] = []

    def fake_commons_fetch(file_title: str, **kwargs: object) -> CommonsAsset:
        calls.append(file_title)
        assert kwargs["max_attempts"] == 3
        image_url = (
            "https://upload.wikimedia.org/example/player.jpg"
            if "Player" in file_title
            else "https://upload.wikimedia.org/example/team.png"
        )
        return CommonsAsset(
            file_title=f"File:{file_title}",
            image_url=image_url,
            page_url=f"https://commons.wikimedia.org/wiki/File:{file_title}",
            mime_type="image/jpeg" if "Player" in file_title else "image/png",
            license_name="CC BY-SA 4.0",
            attribution="Example Author",
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("nba_stats.__main__.fetch_nba_catalogs", fake_catalog_fetch)
    monkeypatch.setattr("nba_stats.__main__.fetch_commons_asset", fake_commons_fetch)
    manifest_path = tmp_path / "assets.csv"
    manifest_path.write_text(
        "ASSET_TYPE,ENTITY_ID,SEASON_ID,EDITION,FILE_TITLE\n"
        "PLAYER_FACE,23,,,Player_face.jpg\n"
        "TEAM_LOGO,1,,,Team_logo.png\n",
        encoding="utf-8",
    )
    branding_path = tmp_path / "branding.csv"
    branding_path.write_text(
        "TEAM_ID,PRIMARY_COLOR_RGB,SECONDARY_COLOR_RGB,SOURCE_URL\n"
        '1,"1,2,3","4,5,6",https://example.com/brand\n',
        encoding="utf-8",
    )
    awards_path = tmp_path / "awards.csv"
    awards_path.write_text(
        "PLAYER_ID,SEASON_ID,ACHIEVEMENT,SOURCE_URL\n"
        "23,2025-26,MVP,https://example.com/mvp\n"
        "23,2025-26,All-NBA First Team,https://example.com/all-nba\n",
        encoding="utf-8",
    )
    data_directory = tmp_path / "data"

    result = main(
        [
            "--catalogs-only",
            "--season",
            "2025-26",
            "--data-dir",
            str(data_directory),
            "--asset-manifest",
            str(manifest_path),
            "--team-branding-manifest",
            str(branding_path),
            "--awards-manifest",
            str(awards_path),
        ]
    )

    assert result == 0
    assert len(calls) == 2
    with (data_directory / "player_seasons.csv").open(
        encoding="utf-8-sig", newline=""
    ) as csv_file:
        player_season = next(csv.DictReader(csv_file))
    with (data_directory / "team_seasons.csv").open(
        encoding="utf-8-sig", newline=""
    ) as csv_file:
        team_season = next(csv.DictReader(csv_file))
    with (data_directory / "player_awards.csv").open(
        encoding="utf-8-sig", newline=""
    ) as csv_file:
        award_rows = list(csv.DictReader(csv_file))
    with (data_directory / "media_assets.csv").open(
        encoding="utf-8-sig", newline=""
    ) as csv_file:
        media_rows = list(csv.DictReader(csv_file))

    assert player_season["PLAYER_FACE_URL"].endswith("player.jpg")
    assert player_season["INDIVIDUAL_ACHIEVEMENTS"] == ("All-NBA First Team | MVP")
    assert team_season["TEAM_LOGO_URL"].endswith("team.png")
    assert team_season["PRIMARY_COLOR_RGB"] == "1,2,3"
    assert team_season["SECONDARY_COLOR_RGB"] == "4,5,6"
    assert team_season["COLOR_SOURCE_URL"] == "https://example.com/brand"
    assert len(award_rows) == len(media_rows) == 2


def test_failed_commons_asset_does_not_clear_saved_image_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    catalogs = {
        "players.csv": (
            ("PLAYER_ID",),
            [{"PLAYER_ID": "23", "PLAYER_NAME": "Player One"}],
        ),
        "teams.csv": (
            ("TEAM_ID",),
            [{"TEAM_ID": "1", "TEAM_NAME": "Test Team"}],
        ),
        "player_seasons.csv": (
            ("PLAYER_ID", "TEAM_ID", "SEASON_ID"),
            [
                {
                    "PLAYER_ID": "23",
                    "TEAM_ID": "1",
                    "SEASON_ID": "2025-26",
                    "PLAYER_FACE_URL": "",
                }
            ],
        ),
        "team_seasons.csv": (
            ("TEAM_ID", "SEASON_ID"),
            [{"TEAM_ID": "1", "SEASON_ID": "2025-26"}],
        ),
    }

    def fake_catalog_fetch(
        season: str, **kwargs: object
    ) -> dict[str, tuple[tuple[str, ...], list[dict[str, object]]]]:
        assert season == "2025-26"
        assert kwargs["timeout_seconds"] == 30
        return catalogs

    def fail_commons_fetch(file_title: str, **kwargs: object) -> CommonsAsset:
        raise CommonsAssetError(
            f"direct image URL unavailable for {file_title} ({kwargs})."
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("nba_stats.__main__.fetch_nba_catalogs", fake_catalog_fetch)
    monkeypatch.setattr("nba_stats.__main__.fetch_commons_asset", fail_commons_fetch)
    manifest_path = tmp_path / "assets.csv"
    manifest_path.write_text(
        "ASSET_TYPE,ENTITY_ID,SEASON_ID,EDITION,FILE_TITLE\n"
        "PLAYER_FACE,23,,,Player_face.jpg\n",
        encoding="utf-8",
    )
    branding_path = tmp_path / "branding.csv"
    branding_path.write_text(
        "TEAM_ID,PRIMARY_COLOR_RGB,SECONDARY_COLOR_RGB,SOURCE_URL\n",
        encoding="utf-8",
    )
    awards_path = tmp_path / "awards.csv"
    awards_path.write_text(
        "PLAYER_ID,SEASON_ID,ACHIEVEMENT,SOURCE_URL\n",
        encoding="utf-8",
    )
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    existing_player_path = data_directory / "player_seasons.csv"
    with existing_player_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=(
                "PLAYER_ID",
                "TEAM_ID",
                "SEASON_ID",
                "PLAYER_FACE_URL",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "PLAYER_ID": "23",
                "TEAM_ID": "1",
                "SEASON_ID": "2025-26",
                "PLAYER_FACE_URL": "https://upload.wikimedia.org/previous.jpg",
            }
        )

    result = main(
        [
            "--catalogs-only",
            "--season",
            "2025-26",
            "--data-dir",
            str(data_directory),
            "--asset-manifest",
            str(manifest_path),
            "--team-branding-manifest",
            str(branding_path),
            "--awards-manifest",
            str(awards_path),
        ]
    )

    assert result == 1
    with existing_player_path.open(encoding="utf-8-sig", newline="") as csv_file:
        saved_player = next(csv.DictReader(csv_file))
    assert saved_player["PLAYER_FACE_URL"] == (
        "https://upload.wikimedia.org/previous.jpg"
    )
    assert "direct image URL unavailable" in capsys.readouterr().err
    assert "No se pudo validar el asset Commons" in caplog.text
