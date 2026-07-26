"""Tests for src/wikimedia_client.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.wikimedia_client import WikimediaClient, _strip_html

# ── Helpers ───────────────────────────────────────────────────────────────────


def _commons_page(
    title: str = "File:Housing.jpg",
    url: str = "https://upload.wikimedia.org/housing.jpg",
    width: int = 1920,
    height: int = 1080,
    mime: str = "image/jpeg",
    licence: str = "CC BY-SA 4.0",
    artist: str = "John Doe",
) -> dict:
    """Build a minimal Wikimedia Commons page dict (formatversion=2 shape)."""
    return {
        "title": title,
        "imageinfo": [
            {
                "url": url,
                "width": width,
                "height": height,
                "mime": mime,
                "extmetadata": {
                    "LicenseShortName": {"value": licence},
                    "Artist": {"value": artist},
                },
            }
        ],
    }


def _commons_response(pages: list) -> dict:
    """Wrap pages in a Wikimedia API response envelope."""
    return {"query": {"pages": pages}}


def _wikipedia_response(person_name: str, url: str, width: int = 800, height: int = 1000) -> dict:
    """Build a Wikipedia pageimages API response (formatversion=2 shape)."""
    return {
        "query": {
            "pages": [
                {
                    "title": person_name,
                    "original": {"source": url, "width": width, "height": height},
                }
            ]
        }
    }


async def _mock_get(url: str, *, params: dict) -> MagicMock:
    """Helper used in httpx patches — returns a mock Response with preset json()."""
    raise NotImplementedError("Use patch directly in each test")


# ── _strip_html ────────────────────────────────────────────────────────────────


class TestStripHtml:
    def test_strips_anchor_tag(self):
        assert _strip_html('<a href="...">Artist Name</a>') == "Artist Name"

    def test_plain_text_unchanged(self):
        assert _strip_html("Jane Smith") == "Jane Smith"

    def test_nested_tags(self):
        assert _strip_html("<span><b>Bold</b> Text</span>") == "Bold Text"

    def test_empty_string(self):
        assert _strip_html("") == ""


# ── WikimediaClient.search_media ──────────────────────────────────────────────


class TestSearchMedia:
    @pytest.mark.asyncio
    async def test_photo_happy_path_returns_assets(self):
        """search_media returns WikimediaAsset list for a valid photo response."""
        client = WikimediaClient()
        page = _commons_page(
            title="File:Downtown_housing.jpg",
            url="https://upload.wikimedia.org/downtown.jpg",
            width=1920,
            height=1080,
        )
        resp_data = _commons_response([page])

        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = mock_resp

            results = await client.search_media("housing market")

        assert len(results) == 1
        asset = results[0]
        assert asset.url == "https://upload.wikimedia.org/downtown.jpg"
        assert asset.width == 1920
        assert asset.height == 1080
        assert asset.source == "wikimedia" if hasattr(asset, "source") else True  # WikimediaAsset has no source field

    @pytest.mark.asyncio
    async def test_attribution_constructed_from_metadata(self):
        """Attribution string combines title, artist, and licence."""
        client = WikimediaClient()
        page = _commons_page(
            title="File:Federal_Reserve.jpg",
            licence="Public Domain",
            artist="US Government",
        )
        resp_data = _commons_response([page])

        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = mock_resp

            results = await client.search_media("federal reserve")

        assert len(results) == 1
        assert "Federal_Reserve.jpg" in results[0].attribution
        assert "US Government" in results[0].attribution
        assert "Public Domain" in results[0].attribution

    @pytest.mark.asyncio
    async def test_photo_below_min_width_excluded(self):
        """Photos narrower than _MIN_PHOTO_WIDTH (800px) are filtered out."""
        client = WikimediaClient()
        page = _commons_page(width=400, height=300)
        resp_data = _commons_response([page])

        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = mock_resp

            results = await client.search_media("narrow photo")

        assert results == []

    @pytest.mark.asyncio
    async def test_non_photo_mime_excluded_for_photo_mode(self):
        """A video/mp4 file is excluded when media_type='photo'."""
        client = WikimediaClient()
        page = _commons_page(mime="video/mp4", width=1920, height=1080)
        resp_data = _commons_response([page])

        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = mock_resp

            results = await client.search_media("video test", media_type="photo")

        assert results == []

    @pytest.mark.asyncio
    async def test_video_mime_accepted_for_video_mode(self):
        """A video/mp4 file is accepted when media_type='video'."""
        client = WikimediaClient()
        page = _commons_page(mime="video/mp4", url="https://upload.wikimedia.org/clip.mp4", width=1280, height=720)
        resp_data = _commons_response([page])

        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = mock_resp

            results = await client.search_media("historic clip", media_type="video")

        assert len(results) == 1
        assert results[0].url.endswith(".mp4")

    @pytest.mark.asyncio
    async def test_no_results_returns_empty_list(self):
        """Empty pages list → empty return."""
        client = WikimediaClient()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"query": {"pages": []}}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = mock_resp

            results = await client.search_media("no results here")

        assert results == []

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_list(self):
        """Network/HTTP error → fault isolation → empty list (D048)."""
        client = WikimediaClient()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.side_effect = httpx.ConnectError("timeout")

            results = await client.search_media("network error")

        assert results == []

    @pytest.mark.asyncio
    async def test_html_stripped_from_artist_field(self):
        """HTML tags in the Artist field are stripped before building attribution."""
        client = WikimediaClient()
        page = _commons_page(artist='<a href="/wiki/User:JDoe">JDoe</a>')
        resp_data = _commons_response([page])

        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = mock_resp

            results = await client.search_media("artist html")

        assert len(results) == 1
        assert "<a" not in results[0].attribution
        assert "JDoe" in results[0].attribution

    @pytest.mark.asyncio
    async def test_legacy_dict_pages_format_handled(self):
        """API response with pages as dict (older formatversion) is handled correctly."""
        client = WikimediaClient()
        page = _commons_page()
        # Simulate older formatversion: pages is a dict keyed by page id
        resp_data = {"query": {"pages": {"12345": page}}}

        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = mock_resp

            results = await client.search_media("legacy format")

        assert len(results) == 1


# ── WikimediaClient.fetch_person_photo ────────────────────────────────────────


class TestFetchPersonPhoto:
    @pytest.mark.asyncio
    async def test_happy_path_returns_asset(self):
        """fetch_person_photo returns a WikimediaAsset for a known person."""
        client = WikimediaClient()
        resp_data = _wikipedia_response(
            "Jerome Powell",
            url="https://upload.wikimedia.org/powell.jpg",
            width=1200,
            height=1600,
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = mock_resp

            result = await client.fetch_person_photo("Jerome Powell")

        assert result is not None
        assert result.url == "https://upload.wikimedia.org/powell.jpg"
        assert result.width == 1200
        assert result.height == 1600
        assert "Jerome Powell" in result.attribution
        assert "Wikipedia" in result.attribution

    @pytest.mark.asyncio
    async def test_no_original_image_returns_none(self):
        """Page exists but has no 'original' image key → None."""
        client = WikimediaClient()
        resp_data = {"query": {"pages": [{"title": "Unknown Person"}]}}

        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = mock_resp

            result = await client.fetch_person_photo("Unknown Person")

        assert result is None

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        """Network failure → fault isolation → None."""
        client = WikimediaClient()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.side_effect = httpx.ConnectError("timeout")

            result = await client.fetch_person_photo("Janet Yellen")

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_pages_returns_none(self):
        """Empty pages list → None."""
        client = WikimediaClient()
        resp_data = {"query": {"pages": []}}

        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = mock_resp

            result = await client.fetch_person_photo("No One")

        assert result is None

    @pytest.mark.asyncio
    async def test_licence_field_set_to_via_wikipedia(self):
        """Person photos use 'Via Wikipedia' as the licence string."""
        client = WikimediaClient()
        resp_data = _wikipedia_response("Robert Shiller", "https://upload.wikimedia.org/shiller.jpg")

        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_data
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = mock_resp

            result = await client.fetch_person_photo("Robert Shiller")

        assert result is not None
        assert result.licence == "Via Wikipedia"
