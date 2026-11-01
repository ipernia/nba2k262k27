from pathlib import Path

import pytest

from nba_stats.catalog_client import NBAEnrichmentError, fetch_nba_catalogs


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


def _endpoint_rows(name: str, **kwargs: object) -> list[dict[str, object]]:
    if name == "LeagueDashPlayerBioStats":
        assert kwargs["season"] == "2025-26"
        return [
            {
                "PLAYER_ID": 10,
                "PLAYER_NAME": "Alpha Player",
                "PLAYER_HEIGHT": "6-7",
                "PLAYER_WEIGHT": "210",
                "COUNTRY": "USA",
                "COLLEGE": "Example University",
                "DRAFT_YEAR": "2020",
                "DRAFT_ROUND": "1",
                "DRAFT_NUMBER": "10",
                "AGE": float("nan"),
            }
        ]
    if name == "LeagueStandings":
        return [
            {
                "TeamID": 1,
                "Conference": "East",
                "Division": "Atlantic",
                "WINS": 20,
                "LOSSES": 10,
                "WinPCT": 0.667,
                "HOME": "10-5",
                "ROAD": "10-5",
                "L10": "6-4",
                "STRK": "W 1",
            }
        ]
    if name == "CommonTeamRoster":
        assert kwargs["team_id"] == "1"
        return [
            {
                "TeamID": 1,
                "PLAYER_ID": 10,
                "PLAYER": "Alpha Player",
                "NUM": "7",
                "POSITION": "Forward",
                "HEIGHT": "6-7",
                "WEIGHT": "210",
                "BIRTH_DATE": "JAN 01, 2000",
                "EXP": "5",
                "SCHOOL": "Example University",
            }
        ]
    if name == "TeamDetails":
        return [
            {
                "TEAM_ID": 1,
                "CITY": "Example City",
                "NICKNAME": "Wolves",
                "ABBREVIATION": "EXW",
                "ARENA": "Example Arena",
                "ARENACAPACITY": 18000,
                "OWNER": "Example Owner",
                "GENERALMANAGER": "Example GM",
                "HEADCOACH": "Example Coach",
                "DLEAGUEAFFILIATION": "Example Affiliate",
            }
        ]
    raise AssertionError(f"Unexpected endpoint: {name}")


def test_fetches_and_normalizes_player_and_team_catalogs() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def endpoint_factory(name: str, **kwargs: object) -> FakeEndpoint:
        calls.append((name, kwargs))
        return FakeEndpoint(_endpoint_rows(name, **kwargs))

    tables = fetch_nba_catalogs("2025-26", endpoint_factory=endpoint_factory)

    assert [name for name, _ in calls] == [
        "LeagueDashPlayerBioStats",
        "LeagueStandings",
        "CommonTeamRoster",
        "TeamDetails",
    ]
    assert tables["players.csv"][0] == ("PLAYER_ID",)
    assert tables["players.csv"][1][0] == {
        "PLAYER_ID": "10",
        "PLAYER_NAME": "Alpha Player",
        "BIRTHDATE": "JAN 01, 2000",
        "HEIGHT": "6-7",
        "WEIGHT": "210",
        "POSITION": "Forward",
        "COUNTRY": "USA",
        "SCHOOL": "Example University",
        "DRAFT_YEAR": "2020",
        "DRAFT_ROUND": "1",
        "DRAFT_NUMBER": "10",
    }
    assert tables["player_seasons.csv"][1][0]["TEAM_ID"] == "1"
    assert tables["player_seasons.csv"][1][0]["SEASON_ID"] == "2025-26"
    assert tables["player_seasons.csv"][1][0]["PLAYER_FACE_URL"] == ""
    assert tables["player_seasons.csv"][1][0]["INDIVIDUAL_ACHIEVEMENTS"] == ""
    assert tables["teams.csv"][1][0]["TEAM_NAME"] == "Example City Wolves"
    assert tables["teams.csv"][1][0]["TEAM_ABBREVIATION"] == "EXW"
    assert tables["team_seasons.csv"][1][0]["CONFERENCE"] == "East"
    assert tables["team_seasons.csv"][1][0]["WIN_PCT"] == "0.667"
    assert tables["team_seasons.csv"][1][0]["TEAM_LOGO_URL"] == ""
    assert tables["team_seasons.csv"][1][0]["PRIMARY_COLOR_RGB"] == ""
    assert tables["team_seasons.csv"][1][0]["SECONDARY_COLOR_RGB"] == ""


def test_uses_recent_local_endpoint_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    def endpoint_factory(name: str, **kwargs: object) -> FakeEndpoint:
        calls.append(name)
        return FakeEndpoint(_endpoint_rows(name, **kwargs))

    cache_directory = tmp_path / "cache"
    first = fetch_nba_catalogs(
        "2025-26",
        endpoint_factory=endpoint_factory,
        cache_directory=cache_directory,
    )
    call_count = len(calls)
    second = fetch_nba_catalogs(
        "2025-26",
        endpoint_factory=endpoint_factory,
        cache_directory=cache_directory,
    )

    assert first == second
    assert call_count == 4
    assert len(calls) == call_count


def test_force_refresh_bypasses_cache(tmp_path: Path) -> None:
    calls: list[str] = []

    def endpoint_factory(name: str, **kwargs: object) -> FakeEndpoint:
        calls.append(name)
        return FakeEndpoint(_endpoint_rows(name, **kwargs))

    common = {
        "endpoint_factory": endpoint_factory,
        "cache_directory": tmp_path / "cache",
    }
    fetch_nba_catalogs("2025-26", **common)
    fetch_nba_catalogs("2025-26", force_refresh=True, **common)

    assert len(calls) == 8


def test_retries_failed_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    delays: list[float] = []

    def endpoint_factory(name: str, **kwargs: object) -> FakeEndpoint:
        calls.append(name)
        if name == "LeagueStandings" and calls.count(name) == 1:
            raise TimeoutError("network timeout")
        return FakeEndpoint(_endpoint_rows(name, **kwargs))

    monkeypatch.setattr("nba_stats.catalog_client.time.sleep", delays.append)

    fetch_nba_catalogs(
        "2025-26",
        endpoint_factory=endpoint_factory,
        max_attempts=2,
        retry_delay_seconds=0.25,
    )

    assert calls.count("LeagueStandings") == 2
    assert delays == [0.25]


def test_does_not_create_catalog_tables_without_standings() -> None:
    def endpoint_factory(name: str, **kwargs: object) -> FakeEndpoint:
        assert kwargs["timeout"] == 30
        if name == "LeagueDashPlayerBioStats":
            return FakeEndpoint([])
        return FakeEndpoint([])

    with pytest.raises(NBAEnrichmentError, match="clasificaciones"):
        fetch_nba_catalogs("2025-26", endpoint_factory=endpoint_factory)


@pytest.mark.parametrize("season", ["2025", "2025-27", "not-a-season"])
def test_rejects_invalid_seasons(season: str) -> None:
    def endpoint_factory(name: str, **kwargs: object) -> FakeEndpoint:
        pytest.fail(f"Unexpected endpoint call: {name} {kwargs}")

    with pytest.raises(ValueError):
        fetch_nba_catalogs(season, endpoint_factory=endpoint_factory)
