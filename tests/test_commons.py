import json
from collections.abc import Mapping
from pathlib import Path
from urllib.request import Request

import pytest

from nba_stats.commons import (
    CommonsAssetError,
    CommonsRequestError,
    fetch_commons_asset,
    load_asset_manifest,
)

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"example-image-data"


class FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int | None = 200,
        url: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.body = body
        self.status = status
        self.url = url
        self.headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]

    def close(self) -> None:
        pass


def _commons_payload(
    *,
    license_name: str = "CC BY-SA 4.0",
    image_url: str = "https://upload.wikimedia.org/wikipedia/commons/a/a0/test.png",
    mime_type: str = "image/png",
) -> bytes:
    return json.dumps(
        {
            "query": {
                "pages": {
                    "1": {
                        "title": "File:Example uniform.png",
                        "imageinfo": [
                            {
                                "url": image_url,
                                "mime": mime_type,
                                "extmetadata": {
                                    "LicenseShortName": {"value": license_name},
                                    "Artist": {"value": "<a>Example Author</a>"},
                                },
                            }
                        ],
                    }
                }
            }
        }
    ).encode()


def test_fetches_licensed_asset_and_verifies_direct_image() -> None:
    requests: list[tuple[str, float]] = []

    def json_opener(request: Request, timeout: float) -> FakeResponse:
        requests.append((request.full_url, timeout))
        return FakeResponse(_commons_payload())

    def image_opener(request: Request, timeout: float) -> FakeResponse:
        requests.append((request.full_url, timeout))
        return FakeResponse(
            _PNG_BYTES,
            status=206,
            url=request.full_url,
            headers={"Content-Type": "image/png"},
        )

    asset = fetch_commons_asset(
        "Example_uniform.png",
        timeout_seconds=4,
        json_opener=json_opener,
        image_opener=image_opener,
    )

    assert asset.file_title == "File:Example uniform.png"
    assert asset.image_url.endswith("/test.png")
    assert asset.page_url.endswith("/File:Example_uniform.png")
    assert asset.license_name == "CC BY-SA 4.0"
    assert asset.attribution == "Example Author"
    assert len(requests) == 2
    assert all(timeout == 4 for _, timeout in requests)


def test_retries_transient_commons_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    json_attempts = 0
    image_attempts = 0
    delays: list[float] = []

    def json_opener(request: Request, timeout: float) -> FakeResponse:
        nonlocal json_attempts
        assert "Example.png" in request.full_url
        assert timeout > 0
        json_attempts += 1
        if json_attempts == 1:
            raise TimeoutError("temporary API timeout")
        return FakeResponse(_commons_payload())

    def image_opener(request: Request, timeout: float) -> FakeResponse:
        nonlocal image_attempts
        assert request.full_url.startswith("https://upload.wikimedia.org/")
        assert timeout > 0
        image_attempts += 1
        if image_attempts == 1:
            raise TimeoutError("temporary image timeout")
        return FakeResponse(
            _PNG_BYTES,
            url=request.full_url,
            headers={"Content-Type": "image/png"},
        )

    monkeypatch.setattr("nba_stats.commons.time.sleep", delays.append)

    fetch_commons_asset(
        "Example.png",
        max_attempts=2,
        retry_delay_seconds=0.25,
        json_opener=json_opener,
        image_opener=image_opener,
    )

    assert json_attempts == 2
    assert image_attempts == 2
    assert delays == [0.25, 0.25]


def test_reports_commons_request_error_after_retry_limit() -> None:
    attempts = 0

    def failing_json_opener(request: Request, timeout: float) -> FakeResponse:
        nonlocal attempts
        attempts += 1
        raise TimeoutError(
            f"network unavailable for {request.full_url} after {timeout} seconds"
        )

    with pytest.raises(CommonsRequestError, match="tras 2 intentos"):
        fetch_commons_asset(
            "Example.png",
            max_attempts=2,
            retry_delay_seconds=0,
            json_opener=failing_json_opener,
        )

    assert attempts == 2


@pytest.mark.parametrize("license_name", ["CC BY-NC 4.0", "Unknown"])
def test_rejects_non_free_or_unknown_license(license_name: str) -> None:
    def json_opener(request: Request, timeout: float) -> FakeResponse:
        assert "Example.png" in request.full_url
        assert timeout > 0
        return FakeResponse(_commons_payload(license_name=license_name))

    def unexpected_image_request(request: Request, timeout: float) -> FakeResponse:
        raise AssertionError(
            f"Unexpected image request: {request.full_url} ({timeout} seconds)."
        )

    with pytest.raises(CommonsAssetError, match="Licencia no aprobada"):
        fetch_commons_asset(
            "Example.png",
            json_opener=json_opener,
            image_opener=unexpected_image_request,
        )


def test_rejects_image_redirecting_outside_wikimedia() -> None:
    def json_opener(request: Request, timeout: float) -> FakeResponse:
        assert "Example.png" in request.full_url
        assert timeout > 0
        return FakeResponse(_commons_payload())

    def image_opener(request: Request, timeout: float) -> FakeResponse:
        assert request.full_url.startswith("https://upload.wikimedia.org/")
        assert timeout > 0
        return FakeResponse(
            _PNG_BYTES,
            url="https://example.com/image.png",
            headers={"Content-Type": "image/png"},
        )

    with pytest.raises(CommonsAssetError, match="redirige fuera"):
        fetch_commons_asset(
            "Example.png",
            json_opener=json_opener,
            image_opener=image_opener,
        )


def test_rejects_content_that_does_not_match_declared_mime() -> None:
    def json_opener(request: Request, timeout: float) -> FakeResponse:
        assert "Example.png" in request.full_url
        assert timeout > 0
        return FakeResponse(_commons_payload())

    def image_opener(request: Request, timeout: float) -> FakeResponse:
        assert request.full_url.startswith("https://upload.wikimedia.org/")
        assert timeout > 0
        return FakeResponse(
            b"not a png",
            url=request.full_url,
            headers={"Content-Type": "image/png"},
        )

    with pytest.raises(CommonsAssetError, match="no coincide"):
        fetch_commons_asset(
            "Example.png",
            json_opener=json_opener,
            image_opener=image_opener,
        )


def test_loads_curated_jersey_manifest(tmp_path: Path) -> None:
    path = tmp_path / "manifest.csv"
    path.write_text(
        "ASSET_TYPE,ENTITY_ID,SEASON_ID,EDITION,FILE_TITLE\n"
        "JERSEY,1610612747,2025-26,home,Example_uniform.png\n",
        encoding="utf-8",
    )

    rows = load_asset_manifest(path)

    assert rows == [
        {
            "ASSET_TYPE": "JERSEY",
            "ENTITY_ID": "1610612747",
            "SEASON_ID": "2025-26",
            "EDITION": "HOME",
            "FILE_TITLE": "File:Example uniform.png",
        }
    ]


def test_loads_player_face_and_team_logo_entries(tmp_path: Path) -> None:
    path = tmp_path / "manifest.csv"
    path.write_text(
        "ASSET_TYPE,ENTITY_ID,SEASON_ID,EDITION,FILE_TITLE\n"
        "PLAYER_FACE,23,,,Player_face.jpg\n"
        "TEAM_LOGO,1610612747,,,Team_logo.png\n",
        encoding="utf-8",
    )

    rows = load_asset_manifest(path)

    assert [row["ASSET_TYPE"] for row in rows] == ["PLAYER_FACE", "TEAM_LOGO"]
    assert rows[0]["FILE_TITLE"] == "File:Player face.jpg"
    assert rows[1]["FILE_TITLE"] == "File:Team logo.png"


@pytest.mark.parametrize(
    "manifest_row",
    [
        "PLAYER,23,, ,Player.png",
        "PLAYER_FACE,23,2025-26,,Player.png",
        "JERSEY,team,2025-26,HOME,Uniform.png",
        "JERSEY,1,2025-27,HOME,Uniform.png",
    ],
)
def test_rejects_invalid_manifest_rows(tmp_path: Path, manifest_row: str) -> None:
    path = tmp_path / "manifest.csv"
    path.write_text(
        f"ASSET_TYPE,ENTITY_ID,SEASON_ID,EDITION,FILE_TITLE\n{manifest_row}\n",
        encoding="utf-8",
    )

    with pytest.raises(CommonsAssetError):
        load_asset_manifest(path)


def test_rejects_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(CommonsAssetError, match="No existe"):
        load_asset_manifest(tmp_path / "missing.csv")
