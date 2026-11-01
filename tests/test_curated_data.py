from pathlib import Path

import pytest

from nba_stats.curated_data import (
    CuratedDataError,
    apply_player_awards,
    apply_team_branding,
    load_player_awards_manifest,
    load_team_branding_manifest,
)


def test_loads_valid_branding_and_normalizes_rgb(tmp_path: Path) -> None:
    path = tmp_path / "branding.csv"
    path.write_text(
        "TEAM_ID,PRIMARY_COLOR_RGB,SECONDARY_COLOR_RGB,SOURCE_URL\n"
        '1,"001, 12, 255","0,0,0",https://example.com/brand\n',
        encoding="utf-8",
    )

    branding = load_team_branding_manifest(path)

    assert branding == {
        "1": {
            "PRIMARY_COLOR_RGB": "1,12,255",
            "SECONDARY_COLOR_RGB": "0,0,0",
            "COLOR_SOURCE_URL": "https://example.com/brand",
        }
    }


@pytest.mark.parametrize(
    ("primary", "source"),
    [
        ("256,0,0", "https://example.com"),
        ("#ff0000", "https://example.com"),
        ("255,0,0", "http://example.com"),
    ],
)
def test_rejects_unverified_or_invalid_colors(
    tmp_path: Path, primary: str, source: str
) -> None:
    path = tmp_path / "branding.csv"
    path.write_text(
        "TEAM_ID,PRIMARY_COLOR_RGB,SECONDARY_COLOR_RGB,SOURCE_URL\n"
        f'1,"{primary}",,"{source}"\n',
        encoding="utf-8",
    )

    with pytest.raises(CuratedDataError):
        load_team_branding_manifest(path)


def test_applies_colors_only_to_matching_team(tmp_path: Path) -> None:
    path = tmp_path / "branding.csv"
    path.write_text(
        "TEAM_ID,PRIMARY_COLOR_RGB,SECONDARY_COLOR_RGB,SOURCE_URL\n"
        '1,"1,2,3",,"https://example.com/source"\n',
        encoding="utf-8",
    )
    catalogs: dict[str, tuple[tuple[str, ...], list[dict[str, object]]]] = {
        "team_seasons.csv": (
            ("TEAM_ID", "SEASON_ID"),
            [{"TEAM_ID": "1", "SEASON_ID": "2025-26"}],
        )
    }

    apply_team_branding(catalogs, load_team_branding_manifest(path))

    assert catalogs["team_seasons.csv"][1][0]["PRIMARY_COLOR_RGB"] == "1,2,3"
    assert (
        catalogs["team_seasons.csv"][1][0]["COLOR_SOURCE_URL"]
        == "https://example.com/source"
    )


def test_loads_awards_with_https_sources_and_aggregates_by_player_season(
    tmp_path: Path,
) -> None:
    path = tmp_path / "awards.csv"
    path.write_text(
        "PLAYER_ID,SEASON_ID,ACHIEVEMENT,SOURCE_URL\n"
        "23,2025-26,MVP,https://example.com/mvp\n"
        "23,2025-26,All-NBA First Team,https://example.com/all-nba\n"
        "23,2024-25,Defensive Player of the Year,https://example.com/dpoy\n",
        encoding="utf-8",
    )
    awards = load_player_awards_manifest(path)
    catalogs: dict[str, tuple[tuple[str, ...], list[dict[str, object]]]] = {
        "player_seasons.csv": (
            ("PLAYER_ID", "TEAM_ID", "SEASON_ID"),
            [
                {
                    "PLAYER_ID": "23",
                    "TEAM_ID": "1",
                    "SEASON_ID": "2025-26",
                    "INDIVIDUAL_ACHIEVEMENTS": "",
                }
            ],
        )
    }

    apply_player_awards(catalogs, awards)

    assert catalogs["player_seasons.csv"][1][0]["INDIVIDUAL_ACHIEVEMENTS"] == (
        "All-NBA First Team | MVP"
    )


@pytest.mark.parametrize(
    "row",
    [
        "23,2025-27,MVP,https://example.com/mvp",
        "abc,2025-26,MVP,https://example.com/mvp",
        "23,2025-26,,https://example.com/mvp",
        "23,2025-26,MVP,http://example.com/mvp",
    ],
)
def test_rejects_invalid_award_rows(tmp_path: Path, row: str) -> None:
    path = tmp_path / "awards.csv"
    path.write_text(
        f"PLAYER_ID,SEASON_ID,ACHIEVEMENT,SOURCE_URL\n{row}\n",
        encoding="utf-8",
    )

    with pytest.raises(CuratedDataError):
        load_player_awards_manifest(path)


def test_rejects_color_for_unknown_team() -> None:
    catalogs: dict[str, tuple[tuple[str, ...], list[dict[str, object]]]] = {
        "team_seasons.csv": (
            ("TEAM_ID", "SEASON_ID"),
            [{"TEAM_ID": "1", "SEASON_ID": "2025-26"}],
        )
    }

    with pytest.raises(CuratedDataError, match="equipos ausentes"):
        apply_team_branding(
            catalogs,
            {
                "2": {
                    "PRIMARY_COLOR_RGB": "1,2,3",
                    "SECONDARY_COLOR_RGB": "",
                    "COLOR_SOURCE_URL": "https://example.com",
                }
            },
        )
