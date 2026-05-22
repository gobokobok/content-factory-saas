"""Tests for src/pexels.py — Pexels API client."""

import pytest
from unittest.mock import MagicMock, patch, call

from src.pexels import (
    PexelsClient,
    _pick_best_video_file,
    _pick_best_photo,
    _ext_from_url,
    _content_type_from_ext,
    _ext_from_content_type,
)
from src.models import ManifestEntry, PexelsAcquireResult
from src.exceptions import PexelsError


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_video_file(height: int, width: int, file_type: str = "video/mp4") -> dict:
    return {
        "id": height,
        "quality": "hd" if height == 1080 else "sd",
        "file_type": file_type,
        "width": width,
        "height": height,
        "link": f"https://videos.pexels.com/clip_{height}.mp4",
    }


def _make_video(files: list[dict]) -> dict:
    return {"id": 1, "video_files": files}


def _make_photo(width: int, height: int, photo_id: int = 1) -> dict:
    return {
        "id": photo_id,
        "width": width,
        "height": height,
        "src": {
            "original": f"https://images.pexels.com/photos/{photo_id}/photo.jpeg",
        },
    }


def _make_entry(
    clip_type: str = "hard_cut",
    primary: str = "city skyline",
    fallback: str = "urban architecture",
) -> ManifestEntry:
    return ManifestEntry(
        scene_id="scene_01",
        clip_type=clip_type,
        primary_query=primary,
        fallback_query=fallback,
        ai_generate_prompt="aerial city at night",
    )


# ── _pick_best_video_file ─────────────────────────────────────────────────────

def test_pick_best_video_file_selects_highest_below_1080p() -> None:
    """4K file excluded; 1080p file selected over 720p."""
    files = [
        _make_video_file(2160, 3840),  # 4K — excluded
        _make_video_file(1080, 1920),  # HD — selected
        _make_video_file(720, 1280),   # SD
    ]
    result = _pick_best_video_file(_make_video(files))
    assert result is not None
    assert result["height"] == 1080
    assert result["width"] == 1920


def test_pick_best_video_file_prefers_wider_at_same_height() -> None:
    """Among two 1080p files, wider is preferred."""
    files = [
        _make_video_file(1080, 1280),
        _make_video_file(1080, 1920),
    ]
    result = _pick_best_video_file(_make_video(files))
    assert result is not None
    assert result["width"] == 1920


def test_pick_best_video_file_returns_none_when_all_exceed_1080p() -> None:
    """Returns None when every file is above 1080px height."""
    files = [_make_video_file(2160, 3840), _make_video_file(1440, 2560)]
    assert _pick_best_video_file(_make_video(files)) is None


def test_pick_best_video_file_returns_none_on_empty_files() -> None:
    assert _pick_best_video_file({"id": 1, "video_files": []}) is None


def test_pick_best_video_file_ignores_files_missing_dimensions() -> None:
    """Files without height/width are excluded."""
    files = [{"id": 1, "quality": "hd", "file_type": "video/mp4", "link": "https://..."}]
    assert _pick_best_video_file(_make_video(files)) is None


# ── _pick_best_photo ──────────────────────────────────────────────────────────

def test_pick_best_photo_selects_closest_without_going_under() -> None:
    """Picks smallest qualifying photo by excess area."""
    photos = [
        _make_photo(4000, 3000, 1),  # larger — more excess
        _make_photo(2000, 1500, 2),  # just over minimum — least excess
        _make_photo(1000, 700, 3),   # below minimum — excluded
    ]
    result = _pick_best_photo(photos)
    assert result is not None
    assert result["id"] == 2


def test_pick_best_photo_returns_none_when_all_too_small() -> None:
    photos = [_make_photo(800, 600), _make_photo(1280, 720)]
    assert _pick_best_photo(photos) is None


def test_pick_best_photo_returns_none_on_empty_list() -> None:
    assert _pick_best_photo([]) is None


def test_pick_best_photo_accepts_exact_minimum_dimensions() -> None:
    photo = _make_photo(1920, 1080)
    result = _pick_best_photo([photo])
    assert result is not None
    assert result["width"] == 1920


# ── Helper utilities ──────────────────────────────────────────────────────────

def test_ext_from_url_extracts_jpeg() -> None:
    url = "https://images.pexels.com/photos/123/pexels-photo.jpeg?auto=compress"
    assert _ext_from_url(url) == ".jpeg"


def test_ext_from_url_extracts_jpg() -> None:
    url = "https://images.pexels.com/photos/123/pexels-photo.jpg"
    assert _ext_from_url(url) == ".jpg"


def test_ext_from_url_defaults_to_jpg_when_no_extension() -> None:
    assert _ext_from_url("https://images.pexels.com/photos/123/photo") == ".jpg"


def test_content_type_from_ext_jpeg() -> None:
    assert _content_type_from_ext(".jpg") == "image/jpeg"
    assert _content_type_from_ext(".jpeg") == "image/jpeg"


def test_ext_from_content_type_video_mp4() -> None:
    assert _ext_from_content_type("video/mp4") == ".mp4"


def test_ext_from_content_type_with_charset_ignored() -> None:
    assert _ext_from_content_type("video/mp4; codecs=avc1") == ".mp4"


# ── PexelsClient._get ─────────────────────────────────────────────────────────

@patch("src.pexels.requests.Session")
def test_get_returns_json_on_200(mock_session_cls: MagicMock) -> None:
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"videos": []}
    mock_session.get.return_value = mock_resp

    client = PexelsClient(api_key="key")
    result = client._get("https://example.com", {})
    assert result == {"videos": []}


@patch("src.pexels.time.sleep")
@patch("src.pexels.requests.Session")
def test_get_retries_on_429_then_succeeds(
    mock_session_cls: MagicMock, mock_sleep: MagicMock
) -> None:
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    rate_limit_resp = MagicMock(status_code=429)
    ok_resp = MagicMock(status_code=200)
    ok_resp.json.return_value = {"photos": []}
    mock_session.get.side_effect = [rate_limit_resp, ok_resp]

    client = PexelsClient(api_key="key")
    result = client._get("https://example.com", {})
    assert result == {"photos": []}
    assert mock_sleep.call_count == 1


@patch("src.pexels.time.sleep")
@patch("src.pexels.requests.Session")
def test_get_raises_pexels_error_after_max_retries(
    mock_session_cls: MagicMock, mock_sleep: MagicMock
) -> None:
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    mock_session.get.return_value = MagicMock(status_code=429)

    client = PexelsClient(api_key="key")
    with pytest.raises(PexelsError, match="rate limit exceeded"):
        client._get("https://example.com", {})


@patch("src.pexels.requests.Session")
def test_get_raises_pexels_error_on_non_200_non_429(
    mock_session_cls: MagicMock,
) -> None:
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    mock_session.get.return_value = MagicMock(status_code=403, text="Forbidden")

    client = PexelsClient(api_key="key")
    with pytest.raises(PexelsError, match="HTTP 403"):
        client._get("https://example.com", {})


@patch("src.pexels.requests.Session")
def test_download_bytes_raises_pexels_error_on_non_200(
    mock_session_cls: MagicMock,
) -> None:
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    mock_session.get.return_value = MagicMock(status_code=404)

    client = PexelsClient(api_key="key")
    with pytest.raises(PexelsError, match="download failed"):
        client._download_bytes("https://videos.pexels.com/clip.mp4")


# ── acquire_for_entry — video (hard_cut) ─────────────────────────────────────

@patch("src.pexels.requests.Session")
def test_acquire_for_entry_hard_cut_primary_success(
    mock_session_cls: MagicMock,
) -> None:
    """hard_cut → Videos API → video/ prefix, returns PexelsAcquireResult."""
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    storage = MagicMock()

    search_resp = MagicMock(status_code=200)
    search_resp.json.return_value = {
        "videos": [_make_video([_make_video_file(1080, 1920)])]
    }
    download_resp = MagicMock(status_code=200, content=b"videodata")
    mock_session.get.side_effect = [search_resp, download_resp]

    client = PexelsClient(api_key="key")
    result = client.acquire_for_entry(_make_entry("hard_cut"), "2026-01-01_test", storage)

    assert result is not None
    assert result.source == "pexels"
    assert result.file_key == "runs/2026-01-01_test/video/scene_01.mp4"
    assert result.status == "acquired"
    storage.upload_bytes.assert_called_once_with(
        "runs/2026-01-01_test/video/scene_01.mp4",
        b"videodata",
        content_type="video/mp4",
    )


# ── acquire_for_entry — photo (still_with_motion / animated) ─────────────────

@patch("src.pexels.requests.Session")
def test_acquire_for_entry_still_with_motion_primary_success(
    mock_session_cls: MagicMock,
) -> None:
    """still_with_motion → Photos API → images/ prefix."""
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    storage = MagicMock()

    search_resp = MagicMock(status_code=200)
    search_resp.json.return_value = {"photos": [_make_photo(2000, 1500)]}
    download_resp = MagicMock(status_code=200, content=b"imgdata")
    mock_session.get.side_effect = [search_resp, download_resp]

    client = PexelsClient(api_key="key")
    result = client.acquire_for_entry(
        _make_entry("still_with_motion"), "2026-01-01_test", storage
    )

    assert result is not None
    assert result.file_key.startswith("runs/2026-01-01_test/images/")
    assert result.file_key.endswith(".jpeg")


@patch("src.pexels.requests.Session")
def test_acquire_for_entry_animated_uses_photo_api(
    mock_session_cls: MagicMock,
) -> None:
    """animated scenes use Photos API (same as still_with_motion)."""
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    storage = MagicMock()

    search_resp = MagicMock(status_code=200)
    search_resp.json.return_value = {"photos": [_make_photo(2000, 1200)]}
    download_resp = MagicMock(status_code=200, content=b"imgdata")
    mock_session.get.side_effect = [search_resp, download_resp]

    client = PexelsClient(api_key="key")
    result = client.acquire_for_entry(
        _make_entry("animated"), "2026-01-01_test", storage
    )

    assert result is not None
    assert "images" in result.file_key


# ── acquire_for_entry — fallback behaviour ────────────────────────────────────

@patch("src.pexels.requests.Session")
def test_acquire_for_entry_falls_back_to_fallback_query(
    mock_session_cls: MagicMock,
) -> None:
    """primary_query returns empty → fallback_query is tried and succeeds."""
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    storage = MagicMock()

    empty_resp = MagicMock(status_code=200)
    empty_resp.json.return_value = {"videos": []}
    fallback_resp = MagicMock(status_code=200)
    fallback_resp.json.return_value = {
        "videos": [_make_video([_make_video_file(1080, 1920)])]
    }
    download_resp = MagicMock(status_code=200, content=b"fallbackvideo")
    mock_session.get.side_effect = [empty_resp, fallback_resp, download_resp]

    client = PexelsClient(api_key="key")
    result = client.acquire_for_entry(
        _make_entry("hard_cut", primary="no match here", fallback="city skyline"),
        "2026-01-01_test",
        storage,
    )

    assert result is not None
    assert result.file_key == "runs/2026-01-01_test/video/scene_01.mp4"
    # Two search calls: one for primary, one for fallback
    assert mock_session.get.call_count == 3


@patch("src.pexels.requests.Session")
def test_acquire_for_entry_returns_none_when_both_queries_empty(
    mock_session_cls: MagicMock,
) -> None:
    """Returns None when both primary and fallback yield no results."""
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    storage = MagicMock()

    empty_resp = MagicMock(status_code=200)
    empty_resp.json.return_value = {"videos": []}
    mock_session.get.side_effect = [empty_resp, empty_resp]

    client = PexelsClient(api_key="key")
    result = client.acquire_for_entry(_make_entry("hard_cut"), "2026-01-01_test", storage)

    assert result is None
    storage.upload_bytes.assert_not_called()


@patch("src.pexels.requests.Session")
def test_acquire_for_entry_returns_none_when_resolution_never_qualifies(
    mock_session_cls: MagicMock,
) -> None:
    """Returns None when both queries return videos but all files exceed 1080p."""
    mock_session = MagicMock()
    mock_session_cls.return_value = mock_session
    storage = MagicMock()

    uhd_only = _make_video([_make_video_file(2160, 3840)])
    uhd_resp = MagicMock(status_code=200)
    uhd_resp.json.return_value = {"videos": [uhd_only]}
    mock_session.get.side_effect = [uhd_resp, uhd_resp]

    client = PexelsClient(api_key="key")
    result = client.acquire_for_entry(_make_entry("hard_cut"), "2026-01-01_test", storage)

    assert result is None
