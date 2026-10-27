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


def make_fake_endpoint(rows: list[dict[str, object]], **kwargs: object) -> FakeEndpoint:
    assert "season" in kwargs
    return FakeEndpoint(rows)


def test_fetches_player_and_team_logs_with_expected_parameters() -> None:
    calls: list[dict[str, object]] = []

    def endpoint_factory(**kwargs: object) -> FakeEndpoint:
        calls.append(kwargs)
        if kwargs["player_or_team_abbreviation"] == "P":
            return FakeEndpoint([{"GAME_ID": "001", "PLAYER_ID": 23}])
        return FakeEndpoint([{"GAME_ID": "001", "TEAM_ID": 1610612738}])

    result = fetch_league_game_logs("2025-26", endpoint_factory=endpoint_factory)

    assert result["P"] == [{"GAME_ID": "001", "PLAYER_ID": 23}]
    assert result["T"] == [{"GAME_ID": "001", "TEAM_ID": 1610612738}]
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
            return FakeEndpoint([{"GAME_ID": "001", "PLAYER_ID": 23}])
        return FakeEndpoint([{"GAME_ID": "001", "TEAM_ID": 1}])

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
                [{"GAME_ID": "001"}], **kwargs
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
