"""Tests for src/freesound_client.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.freesound_client import FreesoundClient, FreesoundResult

# ── Fixtures ──────────────────────────────────────────────────────────────────

_HIT = {
    "id": 1,
    "name": "Cash Register Ka-Ching",
    "license": "https://creativecommons.org/publicdomain/zero/1.0/",
    "duration": 1.5,
    "previews": {
        "preview-hq-mp3": "https://freesound.org/data/previews/1/1_hq.mp3",
        "preview-lq-mp3": "https://freesound.org/data/previews/1/1_lq.mp3",
    },
    "avg_rating": 4.2,
    "num_downloads": 8123,
    "url": "https://freesound.org/people/someone/sounds/1/",
}

_HIT_LQ_ONLY = {
    "id": 2,
    "name": "Checkmark Ding",
    "license": "https://creativecommons.org/publicdomain/zero/1.0/",
    "duration": 0.8,
    "previews": {"preview-lq-mp3": "https://freesound.org/data/previews/2/2_lq.mp3"},
    "avg_rating": None,
    "num_downloads": None,
    "url": "https://freesound.org/people/someone/sounds/2/",
}

_HIT_NO_PREVIEW = {
    "id": 3,
    "name": "No Preview",
    "license": "https://creativecommons.org/publicdomain/zero/1.0/",
    "duration": 2.0,
    "previews": {},
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


# ── search ────────────────────────────────────────────────────────────────────


class TestSearch:
    @pytest.mark.asyncio
    async def test_happy_path_returns_result_list(self):
        client = FreesoundClient(api_key="testtoken")
        with patch("src.freesound_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response({"results": [_HIT]})

            result = await client.search("cash register")

        assert len(result) == 1
        assert isinstance(result[0], FreesoundResult)
        assert result[0].id == 1
        assert result[0].name == "Cash Register Ka-Ching"
        assert result[0].preview_url == "https://freesound.org/data/previews/1/1_hq.mp3"
        assert result[0].duration == 1.5
        assert result[0].avg_rating == 4.2
        assert result[0].num_downloads == 8123
        assert result[0].page_url == "https://freesound.org/people/someone/sounds/1/"

    @pytest.mark.asyncio
    async def test_falls_back_to_lq_preview_when_hq_absent(self):
        client = FreesoundClient(api_key="testtoken")
        with patch("src.freesound_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response({"results": [_HIT_LQ_ONLY]})

            result = await client.search("checkmark")

        assert result[0].preview_url == "https://freesound.org/data/previews/2/2_lq.mp3"

    @pytest.mark.asyncio
    async def test_hit_without_any_preview_skipped(self):
        client = FreesoundClient(api_key="testtoken")
        with patch("src.freesound_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response({"results": [_HIT_NO_PREVIEW]})

            result = await client.search("query")

        assert result == []

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty_list(self):
        client = FreesoundClient(api_key="testtoken")
        with patch("src.freesound_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response({"results": []})

            result = await client.search("query")

        assert result == []

    @pytest.mark.asyncio
    async def test_api_error_returns_empty_list(self):
        """HTTP error → empty list (fault isolation, D048)."""
        import httpx
        client = FreesoundClient(api_key="testtoken")
        with patch("src.freesound_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.side_effect = httpx.HTTPStatusError(
                "429", request=MagicMock(), response=MagicMock()
            )

            result = await client.search("query")

        assert result == []

    @pytest.mark.asyncio
    async def test_connection_error_returns_empty_list(self):
        import httpx
        client = FreesoundClient(api_key="testtoken")
        with patch("src.freesound_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.side_effect = httpx.ConnectError("timeout")

            result = await client.search("query")

        assert result == []

    @pytest.mark.asyncio
    async def test_token_and_cc0_filter_passed_as_query_params(self):
        client = FreesoundClient(api_key="my-secret-token")
        with patch("src.freesound_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response({"results": []})

            await client.search("whoosh", max_results=5)

        call_kwargs = mock_http.get.call_args
        params = call_kwargs[1]["params"]
        assert params["token"] == "my-secret-token"
        assert params["query"] == "whoosh"
        assert params["page_size"] == 5
        assert "Creative Commons 0" in params["filter"]

    @pytest.mark.asyncio
    async def test_malformed_hit_missing_id_skipped_not_raised(self):
        client = FreesoundClient(api_key="testtoken")
        malformed = {"name": "no id", "previews": {"preview-hq-mp3": "https://x/y.mp3"}}
        with patch("src.freesound_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            mock_http.get.return_value = _mock_response({"results": [malformed, _HIT]})

            result = await client.search("query")

        # Malformed hit skipped, well-formed hit still returned
        assert len(result) == 1
        assert result[0].id == 1


# ── download_preview ─────────────────────────────────────────────────────────


class TestDownloadPreview:
    @pytest.mark.asyncio
    async def test_happy_path_returns_bytes(self):
        client = FreesoundClient(api_key="testtoken")
        result = FreesoundResult(
            id=1, name="x", license="cc0", duration=1.0,
            preview_url="https://freesound.org/data/previews/1/1_hq.mp3",
        )
        with patch("src.freesound_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.content = b"fake mp3 bytes"
            mock_http.get.return_value = resp

            data = await client.download_preview(result)

        assert data == b"fake mp3 bytes"
        mock_http.get.assert_awaited_once_with(result.preview_url)

    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        """Unlike search(), download_preview() raises — caller decides how to handle it."""
        import httpx
        client = FreesoundClient(api_key="testtoken")
        result = FreesoundResult(
            id=1, name="x", license="cc0", duration=1.0,
            preview_url="https://freesound.org/data/previews/1/1_hq.mp3",
        )
        with patch("src.freesound_client.httpx.AsyncClient") as mock_cls:
            mock_http = AsyncMock()
            mock_cls.return_value.__aenter__.return_value = mock_http
            resp = MagicMock()
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "404", request=MagicMock(), response=resp
            )
            mock_http.get.return_value = resp

            with pytest.raises(httpx.HTTPStatusError):
                await client.download_preview(result)
