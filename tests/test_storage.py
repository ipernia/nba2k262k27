import csv
from pathlib import Path

import pytest

from nba_stats.storage import (
    CSVStorageError,
    player_ids_missing_profile_info,
    save_game_logs,
)
from nba_stats.team_catalog import TEAM_STATIC_DATA

PLAYER_ROWS = [
    {
        "GAME_ID": "001",
        "PLAYER_ID": 23,
        "PLAYER_NAME": "Player One",
        "TEAM_ID": 1,
        "TEAM_ABBREVIATION": "TST",
        "TEAM_NAME": "Test Team",
        "PTS": 10,
    }
]
TEAM_ROWS = [
    {
        "GAME_ID": "001",
        "SEASON_ID": "2026-27",
        "GAME_DATE": "2026-10-20",
        "MATCHUP": "TST vs. OPP",
        "TEAM_ID": 1,
        "TEAM_ABBREVIATION": "TST",
        "TEAM_NAME": "Test Team",
        "PTS": 100,
        "VIDEO_AVAILABLE": 1,
    },
    {
        "GAME_ID": "001",
        "SEASON_ID": "2026-27",
        "GAME_DATE": "2026-10-20",
        "MATCHUP": "OPP @ TST",
        "TEAM_ID": 2,
        "TEAM_ABBREVIATION": "OPP",
        "TEAM_NAME": "Opponent Team",
        "PTS": 98,
        "VIDEO_AVAILABLE": 1,
    },
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def test_creates_csvs_with_image_urls_games_and_game_stats(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "data"

    counts = save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)

    assert counts == {"P": 1, "T": 2}
    expected_names = {
        "teams.csv",
        "players.csv",
        "games.csv",
        "team_game_stats.csv",
        "player_game_stats.csv",
    }
    assert {path.name for path in data_directory.glob("*.csv")} == expected_names
    assert all(
        path.read_bytes().startswith(b"\xef\xbb\xbf")
        for path in data_directory.glob("*.csv")
    )
    players = read_csv(data_directory / "players.csv")
    assert len(players) == 1
    assert players[0]["PLAYER_ID"] == "23"
    assert players[0]["PLAYER_NAME"] == "Player One"
    assert players[0]["PLAYER_HEADSHOT_URL"] == (
        "https://cdn.nba.com/headshots/nba/latest/1040x760/23.png"
    )
    assert "PLAYER_FACE_URL" not in players[0]
    teams = read_csv(data_directory / "teams.csv")
    assert len(teams) == 2
    assert teams[0]["TEAM_ID"] == "1"
    assert teams[0]["TEAM_ABBREVIATION"] == "TST"
    assert teams[0]["TEAM_NAME"] == "Test Team"
    assert teams[0]["TEAM_LOGO_URL"] == (
        "https://cdn.nba.com/logos/nba/1/primary/L/logo.svg"
    )
    games = read_csv(data_directory / "games.csv")
    assert games[0]["GAME_ID"] == "001"
    assert games[0]["SEASON"] == "2026-27"
    assert games[0]["HOME_TEAM_ID"] == "1"
    assert games[0]["AWAY_TEAM_ID"] == "2"
    assert games[0]["HOME_TEAM_SCORE"] == "100"
    player_stats = read_csv(data_directory / "player_game_stats.csv")[0]
    team_stats = read_csv(data_directory / "team_game_stats.csv")[0]
    assert player_stats["PLAYER_ID"] == "23"
    assert player_stats["TEAM_ID"] == team_stats["TEAM_ID"] == "1"
    assert player_stats["GAME_ID"] == team_stats["GAME_ID"] == "001"
    assert "PLAYER_NAME" not in player_stats
    assert "TEAM_NAME" not in team_stats
    for stats in (player_stats, team_stats):
        assert not {"SEASON_ID", "GAME_DATE", "MATCHUP", "VIDEO_AVAILABLE"} & set(stats)
    assert "TEAM_NICKNAME" not in teams[0]


def test_preserves_percentage_ratios_and_win_pct(
    tmp_path: Path,
) -> None:
    player_rows = [
        PLAYER_ROWS[0]
        | {
            "FG_PCT": 0.427,
            "FG3_PCT": 0.355,
            "FT_PCT": 1.0,
        }
    ]
    team_rows = [
        TEAM_ROWS[0] | {"FG_PCT": 0.427, "FG3_PCT": 0.355, "FT_PCT": 0.0},
        TEAM_ROWS[1] | {"FG_PCT": 0.355, "FG3_PCT": 0.427, "FT_PCT": None},
    ]

    save_game_logs(
        tmp_path / "data",
        player_rows,
        team_rows,
        season="2026-27",
    )
    save_game_logs(
        tmp_path / "data",
        player_rows,
        team_rows,
        season="2026-27",
    )

    player_stats = read_csv(tmp_path / "data" / "player_game_stats.csv")[0]
    team_stats = {
        row["TEAM_ID"]: row
        for row in read_csv(tmp_path / "data" / "team_game_stats.csv")
    }
    teams = {row["TEAM_ID"]: row for row in read_csv(tmp_path / "data" / "teams.csv")}
    assert player_stats["FIELD_GOAL_PCT"] == "0.427"
    assert player_stats["THREE_POINT_PCT"] == "0.355"
    assert player_stats["FREE_THROW_PCT"] == "1.0"
    assert player_stats["POINTS"] == "10"
    assert team_stats["1"]["FIELD_GOAL_PCT"] == "0.427"
    assert team_stats["1"]["THREE_POINT_PCT"] == "0.355"
    assert team_stats["1"]["FREE_THROW_PCT"] == "0.0"
    assert team_stats["2"]["FIELD_GOAL_PCT"] == "0.355"
    assert team_stats["2"]["THREE_POINT_PCT"] == "0.427"
    assert team_stats["2"]["FREE_THROW_PCT"] == ""
    assert team_stats["1"]["TEAM_POINTS"] == "100"
    assert teams["1"]["WIN_PCT"] == "1.000"
    assert teams["2"]["WIN_PCT"] == "0.000"


def test_preserves_percentages_already_present_in_csv(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    (data_directory / "player_game_stats.csv").write_text(
        "GAME_ID,PLAYER_ID,FIELD_GOAL_PCT,THREE_POINT_PCT,FREE_THROW_PCT\n"
        "001,23,0.427,0.355,1.0\n",
        encoding="utf-8",
    )

    save_game_logs(data_directory, [], [])

    player_stats = read_csv(data_directory / "player_game_stats.csv")[0]
    assert player_stats["FIELD_GOAL_PCT"] == "0.427"
    assert player_stats["THREE_POINT_PCT"] == "0.355"
    assert player_stats["FREE_THROW_PCT"] == "1.0"


@pytest.mark.parametrize(
    ("percentage", "message"),
    [(427, "no se corrige automáticamente"), ("not-a-number", "no es numérico")],
)
def test_rejects_invalid_percentage_without_overwriting_csv(
    tmp_path: Path,
    percentage: int | str,
    message: str,
) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    player_stats_path = data_directory / "player_game_stats.csv"
    player_stats_path.write_text(
        "GAME_ID,PLAYER_ID,FIELD_GOAL_PCT\n001,23,0.427\n",
        encoding="utf-8",
    )
    original_contents = player_stats_path.read_bytes()
    player_rows = [PLAYER_ROWS[0] | {"FG_PCT": percentage}]

    with pytest.raises(CSVStorageError, match=message):
        save_game_logs(data_directory, player_rows, TEAM_ROWS)

    assert player_stats_path.read_bytes() == original_contents


def test_static_catalog_contains_all_nba_franchises() -> None:
    assert len(TEAM_STATIC_DATA) == 30
    assert len(set(TEAM_STATIC_DATA)) == 30
    for fields in TEAM_STATIC_DATA.values():
        assert fields["TEAM_CITY"]
        assert fields["CONFERENCE"] in {"East", "West"}
        assert fields["DIVISION"]
        assert fields["TEAM_PRIMARY_COLOR"].startswith("#")
        assert fields["TEAM_SECONDARY_COLOR"].startswith("#")
        assert len(fields["TEAM_PRIMARY_COLOR"]) == 7
        assert len(fields["TEAM_SECONDARY_COLOR"]) == 7
        assert fields["NBA_CHAMPIONSHIPS"].isdigit()
        assert fields["ARENA_NAME"]
        assert fields["ARENA_CAPACITY"].isdigit()


def test_standings_are_written_only_for_regular_season(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    standings = [
        {"TEAM_ID": 1, "CONF_RANK": 3, "DIV_RANK": 2, "GB": 1.5},
    ]

    save_game_logs(
        data_directory,
        PLAYER_ROWS,
        TEAM_ROWS,
        season="2026-27",
        standings_rows=standings,
    )

    team = read_csv(data_directory / "teams.csv")[0]
    assert team["CONFERENCE_RANK"] == "3"
    assert team["DIVISION_RANK"] == "2"
    assert team["GAMES_BACK"] == "1.5"


def test_accumulates_games_and_updates_catalog_rows(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)
    next_player_game = {
        **PLAYER_ROWS[0],
        "GAME_ID": "002",
        "TEAM_ID": 2,
        "TEAM_ABBREVIATION": "NEW",
        "TEAM_NAME": "New Team",
        "PTS": 8,
    }
    next_team_game = {
        **TEAM_ROWS[0],
        "GAME_ID": "002",
        "TEAM_ID": 3,
        "TEAM_ABBREVIATION": "NEW",
        "TEAM_NAME": "New Team",
        "MATCHUP": "NEW vs. ALT",
        "PTS": 98,
    }
    next_opponent_game = {
        **TEAM_ROWS[1],
        "GAME_ID": "002",
        "TEAM_ID": 4,
        "TEAM_ABBREVIATION": "ALT",
        "TEAM_NAME": "Alt Team",
        "MATCHUP": "ALT @ NEW",
        "PTS": 90,
    }

    counts = save_game_logs(
        data_directory,
        [PLAYER_ROWS[0] | {"PTS": 12}, next_player_game],
        [TEAM_ROWS[0] | {"PTS": 102}, TEAM_ROWS[1], next_team_game, next_opponent_game],
    )

    players = read_csv(data_directory / "players.csv")
    teams = read_csv(data_directory / "teams.csv")
    player_stats = read_csv(data_directory / "player_game_stats.csv")
    team_stats = read_csv(data_directory / "team_game_stats.csv")
    assert counts == {"P": 2, "T": 4}
    assert len(players) == 1
    assert len(teams) == 4
    assert len(player_stats) == 2
    assert len(team_stats) == 4
    assert player_stats[0]["POINTS"] == "12"
    assert [row["TEAM_ID"] for row in player_stats] == ["1", "2"]
    assert team_stats[0]["TEAM_POINTS"] == "102"
    games = read_csv(data_directory / "games.csv")
    assert [row["GAME_ID"] for row in games] == ["001", "002"]
    assert games[1]["HOME_TEAM_ID"] == "3"
    assert games[1]["AWAY_TEAM_ID"] == "4"


def test_existing_catalogs_are_reduced_to_the_core_columns(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    (data_directory / "players.csv").write_text(
        "PLAYER_ID,PLAYER_NAME,COUNTRY\n23,Player One,USA\n24,Legacy Player,USA\n",
        encoding="utf-8",
    )
    (data_directory / "teams.csv").write_text(
        "TEAM_ID,TEAM_ABBREVIATION,TEAM_NAME,ARENA\n1,TST,Test Team,Old Arena\n",
        encoding="utf-8",
    )

    save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)

    players = read_csv(data_directory / "players.csv")
    teams = read_csv(data_directory / "teams.csv")
    assert players[0]["PLAYER_ID"] == "23"
    assert players[0]["PLAYER_HEADSHOT_URL"] == (
        "https://cdn.nba.com/headshots/nba/latest/1040x760/23.png"
    )
    assert teams[0]["TEAM_ID"] == "1"
    assert teams[0]["TEAM_LOGO_URL"] == (
        "https://cdn.nba.com/logos/nba/1/primary/L/logo.svg"
    )
    assert players[1]["PLAYER_ID"] == "24"
    assert players[1]["PLAYER_HEADSHOT_URL"] == "assets/player_silhouette.png"


def test_player_catalog_removes_redundant_names_and_derives_flag_url(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    (data_directory / "players.csv").write_text(
        "PLAYER_ID,PLAYER_NAME,FIRST_NAME,LAST_NAME,COUNTRY_CODE\n"
        "23,Player One,Player,One,us\n",
        encoding="utf-8",
    )

    save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)

    player = read_csv(data_directory / "players.csv")[0]
    assert "FIRST_NAME" not in player
    assert "LAST_NAME" not in player
    assert player["COUNTRY_CODE"] == "US"
    assert player["FLAG_URL"] == "https://flagcdn.com/w80/us.png"


def test_player_catalog_rejects_invalid_country_code(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    (data_directory / "players.csv").write_text(
        "PLAYER_ID,PLAYER_NAME,COUNTRY_CODE,FLAG_URL\n"
        "23,Player One,USA,https://example.com/old.png\n",
        encoding="utf-8",
    )

    save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)

    player = read_csv(data_directory / "players.csv")[0]
    assert player["COUNTRY_CODE"] == ""
    assert player["FLAG_URL"] == ""
    image = Path(__file__).parents[1] / "assets" / "player_silhouette.png"
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_saves_player_profile_fields_and_derives_country_flag(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"

    save_game_logs(
        data_directory,
        PLAYER_ROWS,
        TEAM_ROWS,
        player_info_rows=[
            {
                "PLAYER_ID": "23",
                "NATIONALITY": "France",
                "COUNTRY_CODE": "FR",
                "BIRTHDATE": "1998-07-14T00:00:00",
                "HEIGHT": "6-8",
                "WEIGHT": "215",
                "POSITION": "G-F",
                "JERSEY": "00",
            }
        ],
    )

    player = read_csv(data_directory / "players.csv")[0]
    assert player["NATIONALITY"] == "France"
    assert player["COUNTRY_CODE"] == "FR"
    assert player["FLAG_URL"] == "https://flagcdn.com/w80/fr.png"
    assert player["BIRTH_DATE"] == "1998-07-14"
    assert player["HEIGHT_METERS"] == "2.03"
    assert player["WEIGHT_KG"] == "97.52"
    assert player["POSITION"] == "G-F"
    assert player["JERSEY_NUMBER"] == "00"


def test_only_returns_player_ids_with_incomplete_profile_info(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    (data_directory / "players.csv").write_text(
        "PLAYER_ID,COUNTRY_CODE,BIRTH_DATE,HEIGHT_METERS,WEIGHT_KG,POSITION,"
        "JERSEY_NUMBER\n"
        "23,US,2000-01-02,2.03,97.52,G-F,00\n"
        "24,US,2001-02-03,,102.06,F,4\n",
        encoding="utf-8",
    )

    player_ids = player_ids_missing_profile_info(
        data_directory,
        [{"PLAYER_ID": 23}, {"PLAYER_ID": 25}],
    )

    assert player_ids == ["24", "25"]


def test_moves_entity_fields_out_of_existing_season_csvs(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    (data_directory / "player_seasons.csv").write_text(
        "PLAYER_ID,TEAM_ID,SEASON_ID,PLAYER_NAME,JERSEY_NUM,POSITION,HEIGHT,"
        "WEIGHT,EXP,SCHOOL,PLAYER_FACE_URL,INDIVIDUAL_ACHIEVEMENTS\n"
        "23,1,2026-27,Season Player,00,G,6-4,200,2,Example University,"
        ",All-Star\n"
        "24,2,2026-27,Other Player,5,F,6-8,215,3,Example College,,\n",
        encoding="utf-8",
    )
    (data_directory / "team_seasons.csv").write_text(
        "TEAM_ID,SEASON_ID,CONFERENCE,DIVISION,WINS,LOSSES,WIN_PCT,"
        "HOME_RECORD,ROAD_RECORD,L10,STREAK,TEAM_LOGO_URL,PRIMARY_COLOR_RGB,"
        "SECONDARY_COLOR_RGB,COLOR_SOURCE_URL\n"
        "1,2026-27,East,Test,3,4,0.429,1-2,2-2,3-4,,,"
        "10,20,https://example.com/colors/1\n"
        "2,2026-27,West,Other,4,3,0.571,2-1,2-2,4-3,,,"
        "30,40,https://example.com/colors/2\n",
        encoding="utf-8",
    )

    save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)

    players = read_csv(data_directory / "players.csv")
    teams = read_csv(data_directory / "teams.csv")
    player_seasons = read_csv(data_directory / "player_seasons.csv")
    team_seasons = read_csv(data_directory / "team_seasons.csv")
    assert players[0]["PLAYER_ID"] == "23"
    assert players[0]["PLAYER_HEADSHOT_URL"] == (
        "https://cdn.nba.com/headshots/nba/latest/1040x760/23.png"
    )
    assert players[0]["COLLEGE"] == "Example University"
    assert players[0]["POSITION"] == "G"
    assert players[0]["JERSEY_NUMBER"] == "00"
    assert players[0]["HEIGHT_METERS"] == "1.93"
    assert players[0]["WEIGHT_KG"] == "90.72"
    assert players[1]["PLAYER_ID"] == "24"
    assert teams[0]["WINS"] == "3"
    assert teams[0]["LOSSES"] == "4"
    assert teams[0]["GAMES_PLAYED"] == "7"
    assert teams[0]["WIN_PCT"] == "0.429"
    assert teams[0]["HOME_WINS"] == ""
    assert teams[0]["HOME_LOSSES"] == ""
    assert teams[0]["AWAY_WINS"] == ""
    assert teams[0]["AWAY_LOSSES"] == ""
    assert teams[1]["TEAM_ID"] == "2"
    assert teams[1]["TEAM_LOGO_URL"] == (
        "https://cdn.nba.com/logos/nba/2/primary/L/logo.svg"
    )
    assert list(player_seasons[0]) == [
        "PLAYER_ID",
        "TEAM_ID",
        "SEASON_ID",
        "JERSEY_NUM",
        "POSITION",
        "EXP",
    ]
    assert player_seasons[0] == {
        "PLAYER_ID": "23",
        "TEAM_ID": "1",
        "SEASON_ID": "2026-27",
        "JERSEY_NUM": "00",
        "POSITION": "G",
        "EXP": "2",
    }
    assert list(team_seasons[0]) == [
        "TEAM_ID",
        "SEASON_ID",
        "CONFERENCE",
        "DIVISION",
        "WINS",
        "LOSSES",
        "WIN_PCT",
        "HOME_RECORD",
        "ROAD_RECORD",
        "L10",
        "STREAK",
    ]
    assert team_seasons[0]["TEAM_ID"] == "1"
    assert team_seasons[0]["DIVISION"] == "Test"
    assert team_seasons[0]["WIN_PCT"] == "0.429"


def test_empty_results_do_not_create_or_change_files(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)
    originals = {path.name: path.read_bytes() for path in data_directory.glob("*.csv")}

    counts = save_game_logs(data_directory, [], [])

    assert counts == {"P": 1, "T": 2}
    assert {
        path.name: path.read_bytes() for path in data_directory.glob("*.csv")
    } == originals


def test_empty_update_preserves_migrated_games(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS, season="2026-27")
    games_path = data_directory / "games.csv"
    original = games_path.read_bytes()

    save_game_logs(data_directory, [], [])

    assert games_path.read_bytes() == original


def test_regular_standings_are_not_changed_by_playoff_results(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "data"
    save_game_logs(
        data_directory,
        PLAYER_ROWS,
        TEAM_ROWS,
        season="2026-27",
        season_type="Regular Season",
    )
    playoff_teams = [
        {
            **TEAM_ROWS[0],
            "GAME_ID": "002",
            "SEASON_ID": "42026",
            "PTS": 105,
        },
        {
            **TEAM_ROWS[1],
            "GAME_ID": "002",
            "SEASON_ID": "42026",
            "PTS": 100,
        },
    ]

    save_game_logs(
        data_directory,
        [],
        playoff_teams,
        season="2026-27",
        season_type="Playoffs",
    )

    games = read_csv(data_directory / "games.csv")
    teams = {row["TEAM_ID"]: row for row in read_csv(data_directory / "teams.csv")}
    assert {row["GAME_ID"]: row["SEASON_TYPE"] for row in games} == {
        "001": "Regular Season",
        "002": "Playoffs",
    }
    assert teams["1"]["WINS"] == "1"
    assert teams["1"]["LOSSES"] == "0"
    assert teams["1"]["GAMES_PLAYED"] == "1"


@pytest.mark.parametrize(
    ("player_rows", "team_rows", "missing"),
    [
        ([{**PLAYER_ROWS[0]} | {"PLAYER_ID": ""}], TEAM_ROWS, "no pueden estar vacías"),
        (
            [
                {
                    key: value
                    for key, value in PLAYER_ROWS[0].items()
                    if key != "PLAYER_NAME"
                }
            ],
            TEAM_ROWS,
            "PLAYER_NAME",
        ),
        (
            PLAYER_ROWS,
            [{key: value for key, value in TEAM_ROWS[0].items() if key != "TEAM_ID"}],
            "TEAM_ID",
        ),
        ([PLAYER_ROWS[0] | {"PLAYER_ID": "23/../bad"}], TEAM_ROWS, "PLAYER_ID"),
    ],
)
def test_rejects_invalid_input_without_creating_data(
    tmp_path: Path,
    player_rows: list[dict[str, object]],
    team_rows: list[dict[str, object]],
    missing: str,
) -> None:
    data_directory = tmp_path / "data"

    with pytest.raises(CSVStorageError, match=missing):
        save_game_logs(data_directory, player_rows, team_rows)

    assert not data_directory.exists()


def test_invalid_existing_csv_is_not_overwritten(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    player_path = data_directory / "player_game_stats.csv"
    player_path.write_text("invalid,csv\nvalue,here\n", encoding="utf-8")
    original = player_path.read_bytes()

    with pytest.raises(CSVStorageError, match="PLAYER_ID"):
        save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)

    assert player_path.read_bytes() == original
    assert not (data_directory / "teams.csv").exists()


def test_empty_store_does_not_create_csvs(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"

    assert save_game_logs(data_directory, [], []) == {"P": 0, "T": 0}
    assert not data_directory.exists()


def test_migrates_existing_game_metadata_to_games_csv(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    (data_directory / "player_game_stats.csv").write_text(
        "SEASON_ID,PLAYER_ID,TEAM_ID,GAME_ID,GAME_DATE,MATCHUP,WL,PTS,"
        "VIDEO_AVAILABLE\n"
        "2026-27,23,1,001,2026-10-20,TST vs. OPP,W,10,1\n",
        encoding="utf-8",
    )
    (data_directory / "team_game_stats.csv").write_text(
        "SEASON_ID,TEAM_ID,GAME_ID,GAME_DATE,MATCHUP,WL,PTS,VIDEO_AVAILABLE\n"
        "2026-27,1,001,2026-10-20,TST vs. OPP,W,100,1\n"
        "2026-27,2,001,2026-10-20,OPP @ TST,L,98,1\n",
        encoding="utf-8",
    )

    counts = save_game_logs(data_directory, [], [])

    assert counts == {"P": 1, "T": 2}
    games = read_csv(data_directory / "games.csv")
    assert games[0]["GAME_ID"] == "001"
    assert games[0]["SEASON"] == "2026-27"
    assert games[0]["GAME_DATE"] == "2026-10-20"
    assert games[0]["HOME_TEAM_ID"] == "1"
    assert games[0]["AWAY_TEAM_ID"] == "2"
    assert games[0]["WINNER_TEAM_ID"] == "1"
    player_stats = read_csv(data_directory / "player_game_stats.csv")[0]
    team_stats = read_csv(data_directory / "team_game_stats.csv")
    assert player_stats["PLAYER_ID"] == "23"
    assert player_stats["POINTS"] == "10"
    assert len(team_stats) == 2
    assert team_stats[0]["TEAM_POINTS"] == "100"


def test_preserves_game_stats_when_matchup_is_inconsistent(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    inconsistent_rows = [
        TEAM_ROWS[0],
        TEAM_ROWS[1] | {"MATCHUP": "OPP vs. BAD"},
    ]

    counts = save_game_logs(data_directory, PLAYER_ROWS, inconsistent_rows)

    games = read_csv(data_directory / "games.csv")
    team_stats = read_csv(data_directory / "team_game_stats.csv")
    assert counts == {"P": 1, "T": 2}
    assert games[0]["HOME_TEAM_ID"] == "1"
    assert games[0]["AWAY_TEAM_ID"] == "2"
    assert games[0]["IS_NEUTRAL_SITE"] == "True"
    assert [row["IS_HOME"] for row in team_stats] == ["", ""]
    assert [row["TEAM_POINTS"] for row in team_stats] == ["100", "98"]


def test_keeps_official_home_team_for_neutral_game(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    neutral_rows = [
        TEAM_ROWS[0] | {"IS_NEUTRAL_SITE": True},
        TEAM_ROWS[1] | {"IS_NEUTRAL_SITE": True},
    ]

    save_game_logs(data_directory, PLAYER_ROWS, neutral_rows, season="2026-27")

    game = read_csv(data_directory / "games.csv")[0]
    team_stats = read_csv(data_directory / "team_game_stats.csv")
    teams = read_csv(data_directory / "teams.csv")
    assert game["HOME_TEAM_ID"] == "1"
    assert game["AWAY_TEAM_ID"] == "2"
    assert game["IS_NEUTRAL_SITE"] == "True"
    assert [row["IS_HOME"] for row in team_stats] == ["", ""]
    assert all(
        not row["HOME_WINS"]
        and not row["HOME_LOSSES"]
        and not row["AWAY_WINS"]
        and not row["AWAY_LOSSES"]
        for row in teams
    )


def test_uses_source_order_for_neutral_game_without_official_home(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "data"
    neutral_rows = [
        TEAM_ROWS[1]
        | {
            "TEAM_ID": 2,
            "TEAM_ABBREVIATION": "OPP",
            "MATCHUP": "OPP vs. TST",
            "IS_NEUTRAL_SITE": True,
        },
        TEAM_ROWS[0]
        | {
            "TEAM_ID": 1,
            "TEAM_ABBREVIATION": "TST",
            "MATCHUP": "TST vs. OPP",
            "IS_NEUTRAL_SITE": True,
        },
    ]

    save_game_logs(data_directory, PLAYER_ROWS, neutral_rows)

    game = read_csv(data_directory / "games.csv")[0]
    team_stats = read_csv(data_directory / "team_game_stats.csv")
    assert game["HOME_TEAM_ID"] == "2"
    assert game["AWAY_TEAM_ID"] == "1"
    assert game["IS_NEUTRAL_SITE"] == "True"
    assert all(row["IS_HOME"] == "" for row in team_stats)


def test_infers_neutral_site_when_both_team_localities_are_unknown(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "data"
    unknown_rows = [
        {key: value for key, value in TEAM_ROWS[1].items() if key != "MATCHUP"},
        {key: value for key, value in TEAM_ROWS[0].items() if key != "MATCHUP"},
    ]

    counts = save_game_logs(data_directory, PLAYER_ROWS, unknown_rows)

    game = read_csv(data_directory / "games.csv")[0]
    team_stats = read_csv(data_directory / "team_game_stats.csv")
    assert counts == {"P": 1, "T": 2}
    assert game["HOME_TEAM_ID"] == "1"
    assert game["AWAY_TEAM_ID"] == "2"
    assert game["IS_NEUTRAL_SITE"] == "True"
    assert all(row["IS_HOME"] == "" for row in team_stats)


def test_processes_game_0022600189_with_ambiguous_matchup(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    ambiguous_rows = [
        {
            key: value
            for key, value in (TEAM_ROWS[0] | {"GAME_ID": "0022600189"}).items()
            if key != "MATCHUP"
        },
        {
            key: value
            for key, value in (TEAM_ROWS[1] | {"GAME_ID": "0022600189"}).items()
            if key != "MATCHUP"
        },
    ]

    counts = save_game_logs(data_directory, PLAYER_ROWS, ambiguous_rows)

    game = read_csv(data_directory / "games.csv")[0]
    team_stats = read_csv(data_directory / "team_game_stats.csv")
    assert counts == {"P": 1, "T": 2}
    assert game["GAME_ID"] == "0022600189"
    assert game["IS_NEUTRAL_SITE"] == "True"
    assert len(team_stats) == 2


def test_does_not_infer_neutrality_over_an_explicit_false_signal(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "data"
    non_neutral_rows = [
        {
            key: value
            for key, value in (TEAM_ROWS[0] | {"IS_NEUTRAL_SITE": False}).items()
            if key != "MATCHUP"
        },
        {
            key: value
            for key, value in (TEAM_ROWS[1] | {"IS_NEUTRAL_SITE": False}).items()
            if key != "MATCHUP"
        },
    ]

    save_game_logs(data_directory, PLAYER_ROWS, non_neutral_rows)

    game = read_csv(data_directory / "games.csv")[0]
    assert game["IS_NEUTRAL_SITE"] == "False"


def test_keeps_known_locality_when_another_game_is_ambiguous(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    ambiguous_rows = [
        {
            key: value
            for key, value in (TEAM_ROWS[0] | {"GAME_ID": "0022600189"}).items()
            if key != "MATCHUP"
        },
        {
            key: value
            for key, value in (TEAM_ROWS[1] | {"GAME_ID": "0022600189"}).items()
            if key != "MATCHUP"
        },
    ]

    save_game_logs(
        data_directory,
        PLAYER_ROWS,
        TEAM_ROWS + ambiguous_rows,
        season="2026-27",
    )

    teams = {row["TEAM_ID"]: row for row in read_csv(data_directory / "teams.csv")}
    assert teams["1"]["HOME_WINS"] == "1"
    assert teams["1"]["HOME_LOSSES"] == "0"
    assert teams["1"]["AWAY_WINS"] == "0"
    assert teams["1"]["AWAY_LOSSES"] == "0"
    assert teams["2"]["HOME_WINS"] == "0"
    assert teams["2"]["HOME_LOSSES"] == "0"
    assert teams["2"]["AWAY_WINS"] == "0"
    assert teams["2"]["AWAY_LOSSES"] == "1"
