"""Tests for P8-S3 — real-person detection and Wikimedia person photo routing."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.acquisition import _try_person_photo, acquire_scene
from src.models import ManifestEntry
from src.wikimedia_client import WikimediaAsset

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_person_entry(**kwargs) -> ManifestEntry:
    """Return a ManifestEntry for a person scene (still_with_motion, person_name set)."""
    defaults = dict(
        scene_id="5",
        clip_type="still_with_motion",
        primary_query="Jerome Powell Federal Reserve",
        fallback_query="Federal Reserve chair",
        ai_generate_prompt="portrait of Jerome Powell",
        person_name="Jerome Powell",
        person_title="Chair, Federal Reserve",
    )
    defaults.update(kwargs)
    return ManifestEntry(**defaults)


def _make_generic_entry(**kwargs) -> ManifestEntry:
    """Return a ManifestEntry for a non-person scene."""
    defaults = dict(
        scene_id="3",
        clip_type="still_with_motion",
        primary_query="mortgage document",
        fallback_query="mortgage",
        ai_generate_prompt="bank document on desk",
    )
    defaults.update(kwargs)
    return ManifestEntry(**defaults)


def _wikipedia_asset(person_name: str = "Jerome Powell") -> WikimediaAsset:
    return WikimediaAsset(
        url="https://upload.wikimedia.org/wikipedia/commons/powell.jpg",
        width=1200,
        height=1500,
        title=person_name,
        licence="Via Wikipedia",
        attribution=f"Photo of {person_name} via Wikipedia",
    )


def _mock_storage() -> MagicMock:
    s = MagicMock()
    s.upload_bytes = MagicMock()
    return s


def _mock_pexels() -> MagicMock:
    p = MagicMock()
    p.search_videos.return_value = []
    p.search_photos.return_value = []
    return p


def _mock_pixabay() -> AsyncMock:
    px = AsyncMock()
    px.search_videos = AsyncMock(return_value=[])
    px.search_photos = AsyncMock(return_value=[])
    return px


def _mock_wikimedia(person_asset=None) -> AsyncMock:
    wm = AsyncMock()
    wm.fetch_person_photo = AsyncMock(return_value=person_asset)
    wm.search_media = AsyncMock(return_value=[])
    return wm


# ── _try_person_photo ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_try_person_photo_success():
    """Person photo found: entry updated, returns True."""
    entry = _make_person_entry()
    asset = _wikipedia_asset("Jerome Powell")
    wikimedia = _mock_wikimedia(person_asset=asset)
    storage = _mock_storage()

    with patch("src.acquisition._download_bytes", AsyncMock(return_value=b"imgdata")):
        result = await _try_person_photo(entry, "run-1", wikimedia, storage)

    assert result is True
    assert entry.status == "acquired"
    assert entry.source == "wikimedia_person"
    assert "jerome powell" in entry.file_key.lower() or "5" in entry.file_key
    assert entry.attribution == "Photo of Jerome Powell via Wikipedia"
    wikimedia.fetch_person_photo.assert_called_once_with("Jerome Powell")


@pytest.mark.asyncio
async def test_try_person_photo_no_image_returns_false():
    """Wikipedia returns no image: returns False, entry unchanged."""
    entry = _make_person_entry()
    wikimedia = _mock_wikimedia(person_asset=None)
    storage = _mock_storage()

    result = await _try_person_photo(entry, "run-1", wikimedia, storage)

    assert result is False
    assert entry.status == "pending"
    assert entry.source is None
    storage.upload_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_try_person_photo_download_failure_returns_false():
    """Download fails after Wikipedia returns a URL: returns False, entry unchanged."""
    entry = _make_person_entry()
    asset = _wikipedia_asset()
    wikimedia = _mock_wikimedia(person_asset=asset)
    storage = _mock_storage()

    with patch("src.acquisition._download_bytes", AsyncMock(side_effect=Exception("timeout"))):
        result = await _try_person_photo(entry, "run-1", wikimedia, storage)

    assert result is False
    assert entry.status == "pending"


# ── acquire_scene — person routing ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_acquire_scene_person_wikipedia_first():
    """Person scene: Wikipedia is called first; on success no stock search happens."""
    entry = _make_person_entry()
    wikimedia = _mock_wikimedia(person_asset=_wikipedia_asset())
    pexels = _mock_pexels()
    pixabay = _mock_pixabay()
    storage = _mock_storage()

    with patch("src.acquisition._download_bytes", AsyncMock(return_value=b"img")):
        result = await acquire_scene(entry, "run-1", pexels, pixabay, storage, wikimedia)

    assert result is True
    assert entry.source == "wikimedia_person"
    wikimedia.fetch_person_photo.assert_called_once_with("Jerome Powell")
    # Stock sources should not have been queried
    pexels.search_photos.assert_not_called()
    pexels.search_videos.assert_not_called()
    pixabay.search_photos.assert_not_called()


@pytest.mark.asyncio
async def test_acquire_scene_person_wikipedia_miss_falls_back_to_stock():
    """Person scene: Wikipedia miss → falls back to Pexels/Pixabay generic search."""
    entry = _make_person_entry()
    wikimedia = _mock_wikimedia(person_asset=None)
    pexels = _mock_pexels()
    pixabay = _mock_pixabay()

    # Pexels returns a photo candidate
    pexels.search_photos.return_value = [
        {"width": 2000, "height": 1500, "src": {"original": "https://pexels.com/photo.jpg"}}
    ]
    storage = _mock_storage()

    with patch("src.acquisition._download_bytes", AsyncMock(return_value=b"img")):
        result = await acquire_scene(entry, "run-1", pexels, pixabay, storage, wikimedia)

    assert result is True
    assert entry.source == "pexels"
    wikimedia.fetch_person_photo.assert_called_once()
    # Wikimedia general search must NOT be called on person fallback
    wikimedia.search_media.assert_not_called()


@pytest.mark.asyncio
async def test_acquire_scene_person_no_wikimedia_client_skips_to_stock():
    """Person scene with wikimedia=None: skips person lookup, uses generic stock path."""
    entry = _make_person_entry()
    pexels = _mock_pexels()
    pexels.search_photos.return_value = [
        {"width": 2000, "height": 1500, "src": {"original": "https://pexels.com/photo.jpg"}}
    ]
    pixabay = _mock_pixabay()
    storage = _mock_storage()

    with patch("src.acquisition._download_bytes", AsyncMock(return_value=b"img")):
        result = await acquire_scene(entry, "run-1", pexels, pixabay, storage, wikimedia=None)

    assert result is True
    assert entry.source == "pexels"


@pytest.mark.asyncio
async def test_acquire_scene_non_person_does_not_call_fetch_person_photo():
    """Non-person scene: fetch_person_photo is never called."""
    entry = _make_generic_entry()
    wikimedia = _mock_wikimedia(person_asset=None)
    pexels = _mock_pexels()
    pexels.search_photos.return_value = [
        {"width": 2000, "height": 1500, "src": {"original": "https://pexels.com/photo.jpg"}}
    ]
    pixabay = _mock_pixabay()
    storage = _mock_storage()

    with patch("src.acquisition._download_bytes", AsyncMock(return_value=b"img")):
        await acquire_scene(entry, "run-1", pexels, pixabay, storage, wikimedia)

    wikimedia.fetch_person_photo.assert_not_called()


# ── Manifest fields ───────────────────────────────────────────────────────────

def test_manifest_entry_person_fields_default_none():
    """ManifestEntry person fields default to None."""
    entry = _make_generic_entry()
    assert entry.person_name is None
    assert entry.person_title is None


def test_manifest_entry_person_fields_set():
    """ManifestEntry accepts and stores person_name and person_title."""
    entry = _make_person_entry()
    assert entry.person_name == "Jerome Powell"
    assert entry.person_title == "Chair, Federal Reserve"


def test_acquired_person_source_is_wikimedia_person():
    """After a successful person acquisition, source is 'wikimedia_person'."""
    entry = _make_person_entry()
    entry.source = "wikimedia_person"
    entry.status = "acquired"
    assert entry.source == "wikimedia_person"
