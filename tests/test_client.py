import csv
from datetime import date
from pathlib import Path

import pytest

from nba_stats.__main__ import current_season, main
from nba_stats.client import NBAStatsError, fetch_league_game_logs


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


def _game_rows(player_or_team: str) -> list[dict[str, object]]:
    if player_or_team == "P":
        return [
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
    return [
        {
            "GAME_ID": "001",
            "TEAM_ID": 1,
            "TEAM_ABBREVIATION": "TST",
            "TEAM_NAME": "Test Team",
            "PTS": 100,
        }
    ]


def test_fetches_player_and_team_logs_with_expected_parameters() -> None:
    calls: list[dict[str, object]] = []

    def endpoint_factory(**kwargs: object) -> FakeEndpoint:
        calls.append(kwargs)
        return FakeEndpoint(_game_rows(str(kwargs["player_or_team_abbreviation"])))

    result = fetch_league_game_logs("2026-27", endpoint_factory=endpoint_factory)

    assert result["P"][0]["PLAYER_ID"] == 23
    assert result["T"][0]["TEAM_ID"] == 1
    assert [call["player_or_team_abbreviation"] for call in calls] == ["P", "T"]
    assert all(call["season"] == "2026-27" for call in calls)
    assert all(call["season_type_all_star"] == "Regular Season" for call in calls)
    assert all(call["timeout"] == 30 for call in calls)


def test_retries_a_failed_request(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    delays: list[float] = []

    def endpoint_factory(**kwargs: object) -> FakeEndpoint:
        calls.append(kwargs)
        if len(calls) == 1:
            raise TimeoutError("network timeout")
        return FakeEndpoint(_game_rows(str(kwargs["player_or_team_abbreviation"])))

    monkeypatch.setattr("nba_stats.client.time.sleep", delays.append)

    fetch_league_game_logs(
        "2026-27",
        max_attempts=2,
        retry_delay_seconds=0.25,
        endpoint_factory=endpoint_factory,
    )

    assert len(calls) == 3
    assert delays == [0.25]


def test_raises_after_retry_limit() -> None:
    calls = 0

    def endpoint_factory(**kwargs: object) -> FakeEndpoint:
        nonlocal calls
        calls += 1
        assert kwargs["season"] == "2026-27"
        raise TimeoutError("network timeout")

    with pytest.raises(NBAStatsError, match="tras 2 intentos"):
        fetch_league_game_logs(
            "2026-27", max_attempts=2, endpoint_factory=endpoint_factory
        )
    assert calls == 2


@pytest.mark.parametrize("season", ["2026", "2026-28", "not-a-season"])
def test_rejects_invalid_seasons(season: str) -> None:
    with pytest.raises(ValueError):
        fetch_league_game_logs(
            season,
            endpoint_factory=lambda **kwargs: FakeEndpoint([]),
        )


def test_rejects_invalid_retry_options() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        fetch_league_game_logs("2026-27", max_attempts=0)
    with pytest.raises(ValueError, match="retry_delay_seconds"):
        fetch_league_game_logs("2026-27", retry_delay_seconds=-0.1)


def test_rejects_response_missing_identifier() -> None:
    with pytest.raises(NBAStatsError, match="PLAYER_ID"):
        fetch_league_game_logs(
            "2026-27",
            endpoint_factory=lambda **kwargs: FakeEndpoint(
                [{"GAME_ID": "001", "TEAM_ID": 1}]
            ),
        )


def test_rejects_response_without_data_frames() -> None:
    class EmptyEndpoint:
        def get_data_frames(self) -> list[FakeFrame]:
            return []

    with pytest.raises(NBAStatsError, match="sin tablas"):
        fetch_league_game_logs(
            "2026-27", endpoint_factory=lambda **kwargs: EmptyEndpoint()
        )


@pytest.mark.parametrize(
    ("month", "expected_season"),
    [(9, "2025-26"), (10, "2026-27"), (1, "2025-26")],
)
def test_current_season_changes_in_october(month: int, expected_season: str) -> None:
    assert current_season(date(2026, month, 1)) == expected_season


def test_main_updates_only_core_csvs_from_game_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[str] = []

    def fake_fetch_game_logs(
        season: str, **kwargs: object
    ) -> dict[str, list[dict[str, object]]]:
        calls.append(season)
        assert kwargs == {
            "max_attempts": 3,
            "retry_delay_seconds": 2,
            "timeout_seconds": 30,
        }
        return {"P": _game_rows("P"), "T": _game_rows("T")}

    monkeypatch.setattr(
        "nba_stats.__main__.fetch_league_game_logs", fake_fetch_game_logs
    )
    data_directory = tmp_path / "data"

    assert main(["--season", "2026-27", "--data-dir", str(data_directory)]) == 0

    assert calls == ["2026-27"]
    assert {path.name for path in data_directory.glob("*.csv")} == {
        "players.csv",
        "teams.csv",
        "player_game_stats.csv",
        "team_game_stats.csv",
    }
    with (data_directory / "players.csv").open(
        encoding="utf-8-sig", newline=""
    ) as csv_file:
        player = next(csv.DictReader(csv_file))
    with (data_directory / "teams.csv").open(
        encoding="utf-8-sig", newline=""
    ) as csv_file:
        team = next(csv.DictReader(csv_file))
    assert player["PLAYER_FACE_URL"] == (
        "https://cdn.nba.com/headshots/nba/latest/1040x760/23.png"
    )
    assert team["TEAM_LOGO_URL"] == (
        "https://cdn.nba.com/logos/nba/1/primary/L/logo.svg"
    )


def test_main_reports_game_log_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    def fail_game_logs(season: str, **kwargs: object) -> None:
        raise NBAStatsError("NBA unavailable")

    monkeypatch.setattr("nba_stats.__main__.fetch_league_game_logs", fail_game_logs)

    assert main(["--season", "2026-27"]) == 1
    assert "NBA unavailable" in capsys.readouterr().err
    assert not (tmp_path / "data").exists()


def test_main_reports_log_directory_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_mkdir(path: Path, *args: object, **kwargs: object) -> None:
        assert path == Path("logs")
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    assert main([]) == 1
    assert "no se pudo crear la carpeta de registros" in capsys.readouterr().err
