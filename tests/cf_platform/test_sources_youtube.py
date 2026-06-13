"""Tests for the YouTube source adapter (P3-S2, D050)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from cf_platform.core.schemas import Signal
from cf_platform.sources.youtube import YouTubeAdapter, YouTubeAdapterError


def _mock_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=payload)
    return response


def _mock_client(search_payload: dict, videos_payload: dict) -> MagicMock:
    """Build a mocked httpx.AsyncClient whose get() returns search then videos payloads in order."""
    client_instance = MagicMock()
    client_instance.get = AsyncMock(
        side_effect=[_mock_response(search_payload), _mock_response(videos_payload)]
    )
    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=False)
    return client_instance


class TestYouTubeAdapterCredentials:
    """fetch() raises YouTubeAdapterError when the API key is missing."""

    @pytest.mark.asyncio
    async def test_missing_api_key_raises(self):
        adapter = YouTubeAdapter(api_key="")
        with pytest.raises(YouTubeAdapterError):
            await adapter.fetch("starter homes", {})


class TestYouTubeAdapterFetch:
    """fetch() searches, fetches view counts, and normalizes results into Signals."""

    @pytest.mark.asyncio
    async def test_fetch_normalizes_results_into_signals(self):
        search_payload = {
            "items": [
                {
                    "id": {"videoId": "abc123"},
                    "snippet": {"title": "Why starter homes vanished", "channelTitle": "Housing Channel"},
                }
            ]
        }
        videos_payload = {"items": [{"id": "abc123", "statistics": {"viewCount": "98765"}}]}
        client_instance = _mock_client(search_payload, videos_payload)

        adapter = YouTubeAdapter(api_key="key123")
        with patch("httpx.AsyncClient", return_value=client_instance):
            signals = await adapter.fetch("starter homes", {})

        assert signals == [
            Signal(
                source="youtube",
                title="Why starter homes vanished",
                url="https://www.youtube.com/watch?v=abc123",
                score=98765.0,
                meta={"metric": "views", "channel": "Housing Channel"},
            )
        ]

        first_call_params = client_instance.get.call_args_list[0].kwargs["params"]
        assert first_call_params["q"] == "starter homes"
        assert first_call_params["key"] == "key123"

        second_call_params = client_instance.get.call_args_list[1].kwargs["params"]
        assert second_call_params["id"] == "abc123"

    @pytest.mark.asyncio
    async def test_fetch_no_results_skips_view_count_call(self):
        client_instance = MagicMock()
        client_instance.get = AsyncMock(return_value=_mock_response({"items": []}))
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)

        adapter = YouTubeAdapter(api_key="key123")
        with patch("httpx.AsyncClient", return_value=client_instance):
            signals = await adapter.fetch("starter homes", {})

        assert signals == []
        client_instance.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_request_failure_raises_adapter_error(self):
        client_instance = MagicMock()
        client_instance.get = AsyncMock(side_effect=httpx.HTTPError("boom"))
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)

        adapter = YouTubeAdapter(api_key="key123")
        with patch("httpx.AsyncClient", return_value=client_instance):
            with pytest.raises(YouTubeAdapterError):
                await adapter.fetch("starter homes", {})
