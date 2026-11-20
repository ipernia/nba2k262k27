import csv
from datetime import date
from pathlib import Path

import pytest

from nba_stats.__main__ import current_season, main
from nba_stats.client import (
    NBAStatsError,
    fetch_league_game_logs,
    fetch_league_standings,
    fetch_player_info,
)


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
                "SEASON_ID": "2026-27",
                "GAME_DATE": "2026-10-20",
                "MATCHUP": "TST vs. OPP",
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


def _player_info_row(
    player_id: object, country: object = "France"
) -> dict[str, object]:
    return {
        "PERSON_ID": player_id,
        "COUNTRY": country,
        "BIRTHDATE": "2000-01-02T00:00:00",
        "HEIGHT": "6-8",
        "WEIGHT": "215",
        "POSITION": "G-F",
        "JERSEY": "00",
    }


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


def test_fetches_and_normalizes_regular_season_standings() -> None:
    calls: list[dict[str, object]] = []

    def endpoint_factory(**kwargs: object) -> FakeEndpoint:
        calls.append(kwargs)
        return FakeEndpoint(
            [
                {
                    "TeamID": 1,
                    "PlayoffRank": 3,
                    "DivisionRank": 2,
                    "ConferenceGamesBack": 1.5,
                }
            ]
        )

    result = fetch_league_standings(
        "2026-27", endpoint_factory=endpoint_factory, max_attempts=1
    )

    assert result == [
        {
            "TEAM_ID": 1,
            "CONFERENCE_RANK": 3,
            "DIVISION_RANK": 2,
            "GAMES_BACK": 1.5,
        }
    ]
    assert calls == [
        {
            "league_id": "00",
            "season": "2026-27",
            "season_type": "Regular Season",
            "timeout": 30,
        }
    ]


def test_fetches_unique_player_profiles_and_maps_iso_codes() -> None:
    calls: list[dict[str, object]] = []

    class PlayerInfoEndpoint:
        def __init__(self, player_id: str) -> None:
            self.player_id = player_id

        def get_data_frames(self) -> list[FakeFrame]:
            return [
                FakeFrame([{"SEASON_ID": "2026-27"}]),
                FakeFrame([_player_info_row(self.player_id)]),
            ]

    def endpoint_factory(**kwargs: object) -> PlayerInfoEndpoint:
        calls.append(kwargs)
        return PlayerInfoEndpoint(str(kwargs["player_id"]))

    result = fetch_player_info(
        [23, "23", 24],
        endpoint_factory=endpoint_factory,
    )

    assert result == [
        {
            "PLAYER_ID": "23",
            "NATIONALITY": "France",
            "COUNTRY_CODE": "FR",
            "BIRTHDATE": "2000-01-02T00:00:00",
            "HEIGHT": "6-8",
            "WEIGHT": "215",
            "POSITION": "G-F",
            "JERSEY": "00",
        },
        {
            "PLAYER_ID": "24",
            "NATIONALITY": "France",
            "COUNTRY_CODE": "FR",
            "BIRTHDATE": "2000-01-02T00:00:00",
            "HEIGHT": "6-8",
            "WEIGHT": "215",
            "POSITION": "G-F",
            "JERSEY": "00",
        },
    ]
    assert calls == [
        {"player_id": "23", "timeout": 30},
        {"player_id": "24", "timeout": 30},
    ]


def test_retries_common_player_info_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    delays: list[float] = []

    class PlayerInfoEndpoint:
        def get_data_frames(self) -> list[FakeFrame]:
            return [FakeFrame([_player_info_row(23, "USA")])]

    def endpoint_factory(**kwargs: object) -> PlayerInfoEndpoint:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("network timeout")
        return PlayerInfoEndpoint()

    monkeypatch.setattr("nba_stats.client.time.sleep", delays.append)

    result = fetch_player_info(
        [23],
        max_attempts=2,
        retry_delay_seconds=0.25,
        endpoint_factory=endpoint_factory,
    )

    assert result[0]["COUNTRY_CODE"] == "US"
    assert calls == 2
    assert delays == [0.25]


def test_keeps_nationality_when_country_code_cannot_be_resolved() -> None:
    result = fetch_player_info(
        [23],
        endpoint_factory=lambda **kwargs: FakeEndpoint(
            [_player_info_row(23, "Unknown country")]
        ),
    )

    assert result == [
        {
            "PLAYER_ID": "23",
            "NATIONALITY": "Unknown country",
            "BIRTHDATE": "2000-01-02T00:00:00",
            "HEIGHT": "6-8",
            "WEIGHT": "215",
            "POSITION": "G-F",
            "JERSEY": "00",
        }
    ]


def test_treats_missing_country_as_empty() -> None:
    result = fetch_player_info(
        [23],
        endpoint_factory=lambda **kwargs: FakeEndpoint(
            [_player_info_row(23, float("nan"))]
        ),
    )

    assert result == [
        {
            "PLAYER_ID": "23",
            "NATIONALITY": "",
            "BIRTHDATE": "2000-01-02T00:00:00",
            "HEIGHT": "6-8",
            "WEIGHT": "215",
            "POSITION": "G-F",
            "JERSEY": "00",
        }
    ]


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


def test_retry_delay_uses_exponential_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    delays: list[float] = []

    def endpoint_factory(**kwargs: object) -> FakeEndpoint:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TimeoutError("network timeout")
        return FakeEndpoint(_game_rows(str(kwargs["player_or_team_abbreviation"])))

    monkeypatch.setattr("nba_stats.client.time.sleep", delays.append)

    fetch_league_game_logs(
        "2026-27",
        max_attempts=3,
        retry_delay_seconds=0.1,
        endpoint_factory=endpoint_factory,
    )

    assert delays == [0.1, 0.2]


def test_respects_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    class TooManyRequestsError(Exception):
        response = type(
            "Response", (), {"status_code": 429, "headers": {"Retry-After": "4"}}
        )()

    calls = 0
    delays: list[float] = []

    def endpoint_factory(**kwargs: object) -> FakeEndpoint:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TooManyRequestsError("rate limited")
        return FakeEndpoint(_game_rows(str(kwargs["player_or_team_abbreviation"])))

    monkeypatch.setattr("nba_stats.client.time.sleep", delays.append)

    fetch_league_game_logs(
        "2026-27",
        max_attempts=2,
        retry_delay_seconds=0.1,
        endpoint_factory=endpoint_factory,
    )

    assert delays == [4.0]


def test_does_not_retry_forbidden_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ForbiddenError(Exception):
        response = type("Response", (), {"status_code": 403, "headers": {}})()

    calls = 0
    delays: list[float] = []

    def endpoint_factory(**kwargs: object) -> FakeEndpoint:
        nonlocal calls
        calls += 1
        raise ForbiddenError("forbidden")

    monkeypatch.setattr("nba_stats.client.time.sleep", delays.append)

    with pytest.raises(NBAStatsError, match="HTTP 403"):
        fetch_league_game_logs(
            "2026-27",
            max_attempts=3,
            endpoint_factory=endpoint_factory,
        )

    assert calls == 1
    assert delays == []


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


def test_accepts_team_response_missing_matchup() -> None:
    rows = [
        {key: value for key, value in row.items() if key != "MATCHUP"}
        for row in _game_rows("T")
    ]

    result = fetch_league_game_logs(
        "2026-27",
        endpoint_factory=lambda **kwargs: FakeEndpoint(
            rows if kwargs["player_or_team_abbreviation"] == "T" else _game_rows("P")
        ),
    )

    assert len(result["T"]) == 2
    assert "MATCHUP" not in result["T"][0]


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
            "season_type": "Regular Season",
            "max_attempts": 3,
            "retry_delay_seconds": 2,
            "timeout_seconds": 30,
        }
        return {"P": _game_rows("P"), "T": _game_rows("T")}

    monkeypatch.setattr(
        "nba_stats.__main__.fetch_league_game_logs", fake_fetch_game_logs
    )
    monkeypatch.setattr(
        "nba_stats.__main__.fetch_league_standings", lambda *args, **kwargs: []
    )
    player_info_calls: list[list[str]] = []

    def fake_fetch_player_info(
        player_ids: list[str], **kwargs: object
    ) -> list[dict[str, object]]:
        player_info_calls.append(player_ids)
        assert kwargs == {
            "max_attempts": 3,
            "retry_delay_seconds": 2,
            "timeout_seconds": 30,
        }
        return [
            {
                "PLAYER_ID": "23",
                "NATIONALITY": "United States",
                "COUNTRY_CODE": "US",
                "BIRTHDATE": "2000-01-02T00:00:00",
                "HEIGHT": "6-8",
                "WEIGHT": "215",
                "POSITION": "G-F",
                "JERSEY": "00",
            }
        ]

    monkeypatch.setattr(
        "nba_stats.__main__.fetch_player_info",
        fake_fetch_player_info,
    )
    data_directory = tmp_path / "data"

    assert main(["--season", "2026-27", "--data-dir", str(data_directory)]) == 0

    assert calls == ["2026-27"]
    assert player_info_calls == [["23"]]
    assert {path.name for path in data_directory.glob("*.csv")} == {
        "players.csv",
        "teams.csv",
        "games.csv",
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
    assert player["PLAYER_HEADSHOT_URL"] == (
        "https://cdn.nba.com/headshots/nba/latest/1040x760/23.png"
    )
    assert player["NATIONALITY"] == "United States"
    assert player["COUNTRY_CODE"] == "US"
    assert player["FLAG_URL"] == "https://flagcdn.com/w80/us.png"
    assert player["BIRTH_DATE"] == "2000-01-02"
    assert player["HEIGHT_METERS"] == "2.03"
    assert player["WEIGHT_KG"] == "97.52"
    assert player["POSITION"] == "G-F"
    assert player["JERSEY_NUMBER"] == "00"
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
