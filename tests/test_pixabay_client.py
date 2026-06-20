"""Tests for src/pixabay_client.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.pixabay_client import PixabayClient, PixabayPhoto, PixabayVideo

# ── Fixtures ──────────────────────────────────────────────────────────────────

_VIDEO_HIT = {
    "id": 1,
    "pageURL": "https://pixabay.com/videos/1",
    "duration": 30,
    "videos": {
        "large": {"url": "https://cdn.pixabay.com/video/large.mp4", "width": 1920, "height": 1080},
        "medium": {"url": "https://cdn.pixabay.com/video/medium.mp4", "width": 1280, "height": 720},
        "small": {"url": "https://cdn.pixabay.com/video/small.mp4", "width": 960, "height": 540},
    },
}

_VIDEO_HIT_MEDIUM_ONLY = {
    "id": 2,
    "pageURL": "https://pixabay.com/videos/2",
    "duration": 15,
    "videos": {
        "medium": {"url": "https://cdn.pixabay.com/video/medium2.mp4", "width": 1280, "height": 720},
        "small": {"url": "https://cdn.pixabay.com/video/small2.mp4", "width": 960, "height": 540},
    },
}

_PHOTO_HIT = {
    "id": 10,
    "pageURL": "https://pixabay.com/photos/10",
    "largeImageURL": "https://cdn.pixabay.com/photo/large.jpg",
    "imageWidth": 3840,
    "imageHeight": 2160,
}

_PHOTO_HIT_SMALL = {
    "id": 11,
    "pageURL": "https://pixabay.com/photos/11",
    "largeImageURL": "https://cdn.pixabay.com/photo/small.jpg",
    "imageWidth": 800,
    "imageHeight": 600,
}


def _mock_response(data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


# ── search_videos ─────────────────────────────────────────────────────────────


class TestSearchVideos:
    @pytest.mark.asyncio
    async def test_happy_path_returns_video_list(self):
        client = PixabayClient(api_key="testkey")
        with patch("src.pixabay_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response({"hits": [_VIDEO_HIT]})

            result = await client.search_videos("housing market")

        assert len(result) == 1
        assert isinstance(result[0], PixabayVideo)
        assert result[0].url == "https://cdn.pixabay.com/video/medium.mp4"
        assert result[0].width == 1280
        assert result[0].height == 720
        assert result[0].duration_seconds == 30

    @pytest.mark.asyncio
    async def test_prefers_medium_over_large(self):
        """When both 'medium' and 'large' exist, medium (720p) is returned to keep downloads lean."""
        client = PixabayClient(api_key="testkey")
        with patch("src.pixabay_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response({"hits": [_VIDEO_HIT]})

            result = await client.search_videos("market")

        assert result[0].url == "https://cdn.pixabay.com/video/medium.mp4"

    @pytest.mark.asyncio
    async def test_falls_back_to_medium_when_large_absent(self):
        client = PixabayClient(api_key="testkey")
        with patch("src.pixabay_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response({"hits": [_VIDEO_HIT_MEDIUM_ONLY]})

            result = await client.search_videos("query")

        assert result[0].url == "https://cdn.pixabay.com/video/medium2.mp4"
        assert result[0].width == 1280

    @pytest.mark.asyncio
    async def test_api_error_returns_empty_list(self):
        """HTTP error → empty list (fault isolation, D048)."""
        client = PixabayClient(api_key="testkey")
        with patch("src.pixabay_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            import httpx
            mock_http.get.side_effect = httpx.HTTPStatusError(
                "429", request=MagicMock(), response=MagicMock()
            )

            result = await client.search_videos("query")

        assert result == []

    @pytest.mark.asyncio
    async def test_connection_error_returns_empty_list(self):
        import httpx
        client = PixabayClient(api_key="testkey")
        with patch("src.pixabay_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.side_effect = httpx.ConnectError("timeout")

            result = await client.search_videos("query")

        assert result == []

    @pytest.mark.asyncio
    async def test_empty_hits_returns_empty_list(self):
        client = PixabayClient(api_key="testkey")
        with patch("src.pixabay_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response({"hits": []})

            result = await client.search_videos("query")

        assert result == []

    @pytest.mark.asyncio
    async def test_api_key_passed_as_query_param(self):
        client = PixabayClient(api_key="my-secret-key", per_page=7)
        with patch("src.pixabay_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response({"hits": []})

            await client.search_videos("test")

        call_kwargs = mock_http.get.call_args
        params = call_kwargs[1]["params"]
        assert params["key"] == "my-secret-key"
        assert params["per_page"] == 7


# ── search_photos ─────────────────────────────────────────────────────────────


class TestSearchPhotos:
    @pytest.mark.asyncio
    async def test_happy_path_returns_photo_list(self):
        client = PixabayClient(api_key="testkey")
        with patch("src.pixabay_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response({"hits": [_PHOTO_HIT]})

            result = await client.search_photos("house")

        assert len(result) == 1
        assert isinstance(result[0], PixabayPhoto)
        assert result[0].url == "https://cdn.pixabay.com/photo/large.jpg"
        assert result[0].width == 3840
        assert result[0].height == 2160

    @pytest.mark.asyncio
    async def test_api_error_returns_empty_list(self):
        import httpx
        client = PixabayClient(api_key="testkey")
        with patch("src.pixabay_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.side_effect = httpx.HTTPStatusError(
                "403", request=MagicMock(), response=MagicMock()
            )

            result = await client.search_photos("query")

        assert result == []

    @pytest.mark.asyncio
    async def test_hit_without_largeImageURL_skipped(self):
        """Hits missing largeImageURL are silently skipped."""
        client = PixabayClient(api_key="testkey")
        hit_no_url = {**_PHOTO_HIT, "largeImageURL": ""}
        with patch("src.pixabay_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response({"hits": [hit_no_url]})

            result = await client.search_photos("query")

        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_hits_all_returned(self):
        client = PixabayClient(api_key="testkey")
        with patch("src.pixabay_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response(
                {"hits": [_PHOTO_HIT, _PHOTO_HIT_SMALL]}
            )

            result = await client.search_photos("query")

        # Both returned — dimension filtering is acquisition's responsibility
        assert len(result) == 2
