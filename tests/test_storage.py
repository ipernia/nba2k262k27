import csv
from pathlib import Path

import pytest

from nba_stats.storage import CSVStorageError, save_game_logs

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
        "TEAM_ID": 1,
        "TEAM_ABBREVIATION": "TST",
        "TEAM_NAME": "Test Team",
        "PTS": 100,
    }
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def test_creates_only_four_csvs_with_image_urls_and_game_stats(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "data"

    counts = save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)

    assert counts == {"P": 1, "T": 1}
    expected_names = {
        "teams.csv",
        "players.csv",
        "team_game_stats.csv",
        "player_game_stats.csv",
    }
    assert {path.name for path in data_directory.glob("*.csv")} == expected_names
    assert all(
        path.read_bytes().startswith(b"\xef\xbb\xbf")
        for path in data_directory.glob("*.csv")
    )
    assert read_csv(data_directory / "players.csv") == [
        {
            "PLAYER_ID": "23",
            "PLAYER_NAME": "Player One",
            "PLAYER_FACE_URL": (
                "https://cdn.nba.com/headshots/nba/latest/1040x760/23.png"
            ),
            "HEIGHT": "",
            "WEIGHT": "",
            "SCHOOL": "",
            "INDIVIDUAL_ACHIEVEMENTS": "",
        }
    ]
    assert read_csv(data_directory / "teams.csv") == [
        {
            "TEAM_ID": "1",
            "TEAM_ABBREVIATION": "TST",
            "TEAM_NAME": "Test Team",
            "TEAM_LOGO_URL": "https://cdn.nba.com/logos/nba/1/primary/L/logo.svg",
            "PRIMARY_COLOR_RGB": "",
            "SECONDARY_COLOR_RGB": "",
            "COLOR_SOURCE_URL": "",
        }
    ]
    player_stats = read_csv(data_directory / "player_game_stats.csv")[0]
    team_stats = read_csv(data_directory / "team_game_stats.csv")[0]
    assert player_stats["PLAYER_ID"] == "23"
    assert player_stats["TEAM_ID"] == team_stats["TEAM_ID"] == "1"
    assert player_stats["GAME_ID"] == team_stats["GAME_ID"] == "001"
    assert "PLAYER_NAME" not in player_stats
    assert "TEAM_NAME" not in team_stats


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
        "TEAM_ID": 2,
        "TEAM_ABBREVIATION": "NEW",
        "TEAM_NAME": "New Team",
        "PTS": 98,
    }

    counts = save_game_logs(
        data_directory,
        [PLAYER_ROWS[0] | {"PTS": 12}, next_player_game],
        [TEAM_ROWS[0] | {"PTS": 102}, next_team_game],
    )

    players = read_csv(data_directory / "players.csv")
    teams = read_csv(data_directory / "teams.csv")
    player_stats = read_csv(data_directory / "player_game_stats.csv")
    team_stats = read_csv(data_directory / "team_game_stats.csv")
    assert counts == {"P": 2, "T": 2}
    assert len(players) == 1
    assert len(teams) == 2
    assert len(player_stats) == len(team_stats) == 2
    assert player_stats[0]["PTS"] == "12"
    assert [row["TEAM_ID"] for row in player_stats] == ["1", "2"]
    assert team_stats[0]["PTS"] == "102"


def test_existing_catalogs_are_reduced_to_the_core_columns(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    (data_directory / "players.csv").write_text(
        "PLAYER_ID,PLAYER_NAME,COUNTRY\n23,Player One,USA\n",
        encoding="utf-8",
    )
    (data_directory / "teams.csv").write_text(
        "TEAM_ID,TEAM_ABBREVIATION,TEAM_NAME,ARENA\n1,TST,Test Team,Old Arena\n",
        encoding="utf-8",
    )

    save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)

    assert read_csv(data_directory / "players.csv")[0] == {
        "PLAYER_ID": "23",
        "PLAYER_NAME": "Player One",
        "PLAYER_FACE_URL": ("https://cdn.nba.com/headshots/nba/latest/1040x760/23.png"),
        "HEIGHT": "",
        "WEIGHT": "",
        "SCHOOL": "",
        "INDIVIDUAL_ACHIEVEMENTS": "",
    }
    assert read_csv(data_directory / "teams.csv")[0] == {
        "TEAM_ID": "1",
        "TEAM_ABBREVIATION": "TST",
        "TEAM_NAME": "Test Team",
        "TEAM_LOGO_URL": "https://cdn.nba.com/logos/nba/1/primary/L/logo.svg",
        "PRIMARY_COLOR_RGB": "",
        "SECONDARY_COLOR_RGB": "",
        "COLOR_SOURCE_URL": "",
    }


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
    assert players[0] == {
        "PLAYER_ID": "23",
        "PLAYER_NAME": "Player One",
        "PLAYER_FACE_URL": ("https://cdn.nba.com/headshots/nba/latest/1040x760/23.png"),
        "HEIGHT": "6-4",
        "WEIGHT": "200",
        "SCHOOL": "Example University",
        "INDIVIDUAL_ACHIEVEMENTS": "All-Star",
    }
    assert players[1]["PLAYER_ID"] == "24"
    assert players[1]["INDIVIDUAL_ACHIEVEMENTS"] == ""
    assert teams[0]["PRIMARY_COLOR_RGB"] == "10"
    assert teams[0]["SECONDARY_COLOR_RGB"] == "20"
    assert teams[0]["COLOR_SOURCE_URL"] == "https://example.com/colors/1"
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


def test_empty_results_do_not_create_or_change_files(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)
    originals = {path.name: path.read_bytes() for path in data_directory.glob("*.csv")}

    counts = save_game_logs(data_directory, [], [])

    assert counts == {"P": 1, "T": 1}
    assert {
        path.name: path.read_bytes() for path in data_directory.glob("*.csv")
    } == originals


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
