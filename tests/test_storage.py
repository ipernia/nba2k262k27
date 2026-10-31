import csv
from pathlib import Path

import pytest

from nba_stats.storage import (
    CSVStorageError,
    save_catalog_tables,
    save_game_logs,
)

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


def test_creates_four_utf8_bom_csvs_with_power_bi_keys(tmp_path: Path) -> None:
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
    for path in data_directory.glob("*.csv"):
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")

    players = read_csv(data_directory / "players.csv")
    teams = read_csv(data_directory / "teams.csv")
    player_stats = read_csv(data_directory / "player_game_stats.csv")
    team_stats = read_csv(data_directory / "team_game_stats.csv")
    assert players == [{"PLAYER_ID": "23", "PLAYER_NAME": "Player One"}]
    assert teams == [
        {
            "TEAM_ID": "1",
            "TEAM_ABBREVIATION": "TST",
            "TEAM_NAME": "Test Team",
        }
    ]
    assert player_stats[0]["PLAYER_ID"] == players[0]["PLAYER_ID"]
    assert player_stats[0]["TEAM_ID"] == teams[0]["TEAM_ID"]
    assert player_stats[0]["GAME_ID"] == "001"
    assert "PLAYER_NAME" not in player_stats[0]
    assert "TEAM_NAME" not in team_stats[0]


def test_accumulates_games_and_keeps_player_team_history(tmp_path: Path) -> None:
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


def test_migrates_old_logs_without_deleting_them(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    old_player_path = data_directory / "player_game_logs.csv"
    old_team_path = data_directory / "team_game_logs.csv"
    for path, rows in (
        (old_player_path, PLAYER_ROWS),
        (old_team_path, TEAM_ROWS),
    ):
        with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    old_player_bytes = old_player_path.read_bytes()
    old_team_bytes = old_team_path.read_bytes()

    counts = save_game_logs(data_directory, [], [])

    assert counts == {"P": 1, "T": 1}
    assert (data_directory / "players.csv").exists()
    assert (data_directory / "teams.csv").exists()
    assert len(read_csv(data_directory / "player_game_stats.csv")) == 1
    assert len(read_csv(data_directory / "team_game_stats.csv")) == 1
    assert old_player_path.read_bytes() == old_player_bytes
    assert old_team_path.read_bytes() == old_team_bytes


def test_empty_store_does_not_create_csvs(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"

    assert save_game_logs(data_directory, [], []) == {"P": 0, "T": 0}
    assert not data_directory.exists()


def test_catalog_updates_are_idempotent_and_preserve_existing_values(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "data"
    initial_tables = {
        "players.csv": (
            ("PLAYER_ID",),
            [
                {
                    "PLAYER_ID": 23,
                    "PLAYER_NAME": "Player One",
                    "COUNTRY": "USA",
                }
            ],
        ),
        "player_seasons.csv": (
            ("PLAYER_ID", "TEAM_ID", "SEASON_ID"),
            [
                {
                    "PLAYER_ID": 23,
                    "TEAM_ID": 1,
                    "SEASON_ID": "2025-26",
                    "POSITION": "Guard",
                }
            ],
        ),
    }

    assert save_catalog_tables(data_directory, initial_tables) == {
        "players.csv": 1,
        "player_seasons.csv": 1,
    }
    counts = save_catalog_tables(
        data_directory,
        {
            "players.csv": (
                ("PLAYER_ID",),
                [{"PLAYER_ID": 23, "PLAYER_NAME": "", "COUNTRY": None}],
            ),
            "player_seasons.csv": (
                ("PLAYER_ID", "TEAM_ID", "SEASON_ID"),
                [
                    {
                        "PLAYER_ID": 23,
                        "TEAM_ID": 1,
                        "SEASON_ID": "2025-26",
                        "POSITION": "Forward",
                    },
                    {
                        "PLAYER_ID": 23,
                        "TEAM_ID": 2,
                        "SEASON_ID": "2025-26",
                        "POSITION": "Center",
                    },
                ],
            ),
        },
    )

    assert counts == {"players.csv": 1, "player_seasons.csv": 2}
    players = read_csv(data_directory / "players.csv")
    seasons = read_csv(data_directory / "player_seasons.csv")
    assert players == [
        {"PLAYER_ID": "23", "PLAYER_NAME": "Player One", "COUNTRY": "USA"}
    ]
    assert [row["TEAM_ID"] for row in seasons] == ["1", "2"]
    assert seasons[0]["POSITION"] == "Forward"


def test_catalog_validation_does_not_write_any_file(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"

    with pytest.raises(CSVStorageError, match="claves"):
        save_catalog_tables(
            data_directory,
            {
                "players.csv": (
                    ("PLAYER_ID",),
                    [{"PLAYER_NAME": "Player One"}],
                ),
                "teams.csv": (
                    ("TEAM_ID",),
                    [{"TEAM_ID": 1, "TEAM_NAME": "Team"}],
                ),
            },
        )

    assert not data_directory.exists()


def test_catalog_rejects_empty_primary_key(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"

    with pytest.raises(CSVStorageError, match="PLAYER_ID"):
        save_catalog_tables(
            data_directory,
            {
                "players.csv": (
                    ("PLAYER_ID",),
                    [{"PLAYER_ID": "", "PLAYER_NAME": "Player One"}],
                )
            },
        )

    assert not data_directory.exists()
