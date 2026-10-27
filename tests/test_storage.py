import csv
from pathlib import Path

import pytest

from nba_stats.storage import CSVStorageError, save_game_logs

PLAYER_ROWS = [{"GAME_ID": "001", "PLAYER_ID": 23, "PTS": 10}]
TEAM_ROWS = [{"GAME_ID": "001", "TEAM_ID": 1, "PTS": 100}]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def test_creates_utf8_bom_csvs(tmp_path: Path) -> None:
    counts = save_game_logs(tmp_path / "data", PLAYER_ROWS, TEAM_ROWS)

    assert counts == {"P": 1, "T": 1}
    assert (
        (tmp_path / "data" / "player_game_logs.csv")
        .read_bytes()
        .startswith(b"\xef\xbb\xbf")
    )
    assert read_csv(tmp_path / "data" / "player_game_logs.csv") == [
        {"GAME_ID": "001", "PLAYER_ID": "23", "PTS": "10"}
    ]


def test_accumulates_and_updates_existing_games(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)
    counts = save_game_logs(
        data_directory,
        [
            {"GAME_ID": "001", "PLAYER_ID": 23, "PTS": 12},
            {"GAME_ID": "002", "PLAYER_ID": 23, "PTS": 8},
        ],
        [
            {"GAME_ID": "001", "TEAM_ID": 1, "PTS": 102},
            {"GAME_ID": "002", "TEAM_ID": 1, "PTS": 98},
        ],
    )

    players = read_csv(data_directory / "player_game_logs.csv")
    teams = read_csv(data_directory / "team_game_logs.csv")
    assert counts == {"P": 2, "T": 2}
    assert len(players) == len(teams) == 2
    assert players[0]["PTS"] == "12"
    assert teams[0]["PTS"] == "102"


def test_empty_results_do_not_create_or_change_files(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)
    player_path = data_directory / "player_game_logs.csv"
    original = player_path.read_bytes()

    counts = save_game_logs(data_directory, [], [])

    assert counts == {"P": 1, "T": 1}
    assert player_path.read_bytes() == original


@pytest.mark.parametrize(
    ("player_rows", "team_rows", "missing"),
    [
        ([{"GAME_ID": "001"}], TEAM_ROWS, "PLAYER_ID"),
        (PLAYER_ROWS, [{"GAME_ID": "001"}], "TEAM_ID"),
        ([{"GAME_ID": "", "PLAYER_ID": 23}], TEAM_ROWS, "no pueden estar vacías"),
    ],
)
def test_rejects_missing_or_empty_keys(
    tmp_path: Path,
    player_rows: list[dict[str, object]],
    team_rows: list[dict[str, object]],
    missing: str,
) -> None:
    with pytest.raises(CSVStorageError, match=missing):
        save_game_logs(tmp_path / "data", player_rows, team_rows)
    assert not (tmp_path / "data").exists()


def test_invalid_existing_csv_is_not_overwritten(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    player_path = data_directory / "player_game_logs.csv"
    player_path.write_text("invalid,csv\nvalue,here\n", encoding="utf-8")
    original = player_path.read_bytes()

    with pytest.raises(CSVStorageError, match="PLAYER_ID"):
        save_game_logs(data_directory, PLAYER_ROWS, TEAM_ROWS)

    assert player_path.read_bytes() == original
    assert not (data_directory / "team_game_logs.csv").exists()
