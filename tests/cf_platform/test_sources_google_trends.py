"""Tests for the Google Trends source adapter (P3-S2, D050).

Covers the unofficial-API response shapes this adapter parses: the `)]}',`
anti-XSSI prefix, the explore widgets list, and the related-searches ranked
lists. Since this is an undocumented API, these tests pin our understanding of
its shape — if Google changes it, these tests (not just production) will fail.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from cf_platform.core.schemas import Signal
from cf_platform.sources.google_trends import GoogleTrendsAdapter, GoogleTrendsAdapterError

_EXPLORE_PAYLOAD = {
    "widgets": [
        {"id": "TIMESERIES", "token": "tok-timeseries", "request": {}},
        {
            "id": "RELATED_QUERIES",
            "token": "tok-related",
            "request": {"restriction": {"geo": {}}, "keywordType": "QUERY"},
        },
    ]
}

_RELATED_SEARCHES_PAYLOAD = {
    "default": {
        "rankedList": [
            {"rankedKeyword": [{"query": "starter home prices", "value": 100}]},
            {"rankedKeyword": [{"query": "starter homes near me", "value": 250}]},
        ]
    }
}


def _prefixed(payload: dict) -> str:
    return ")]}',\n" + json.dumps(payload)


def _mock_response(text: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.text = text
    return response


def _mock_client(explore_text: str, related_text: str) -> MagicMock:
    client_instance = MagicMock()
    client_instance.get = AsyncMock(
        side_effect=[_mock_response(explore_text), _mock_response(related_text)]
    )
    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=False)
    return client_instance


class TestGoogleTrendsAdapterFetch:
    """fetch() performs the explore -> relatedsearches handshake and normalizes results."""

    @pytest.mark.asyncio
    async def test_fetch_normalizes_ranked_keywords_into_signals(self):
        client_instance = _mock_client(_prefixed(_EXPLORE_PAYLOAD), _prefixed(_RELATED_SEARCHES_PAYLOAD))

        adapter = GoogleTrendsAdapter()
        with patch("httpx.AsyncClient", return_value=client_instance):
            signals = await adapter.fetch("starter homes", {})

        assert signals == [
            Signal(
                source="google_trends",
                title="starter home prices",
                url=None,
                score=100.0,
                meta={"metric": "relative_interest", "rank_list": "top"},
            ),
            Signal(
                source="google_trends",
                title="starter homes near me",
                url=None,
                score=250.0,
                meta={"metric": "relative_interest", "rank_list": "rising"},
            ),
        ]

        # the related-searches call replays the RELATED_QUERIES widget's token + request
        _, related_kwargs = client_instance.get.call_args_list[1]
        assert related_kwargs["params"]["token"] == "tok-related"

    @pytest.mark.asyncio
    async def test_missing_related_queries_widget_raises(self):
        explore_payload = {"widgets": [{"id": "TIMESERIES", "token": "tok-timeseries", "request": {}}]}
        client_instance = MagicMock()
        client_instance.get = AsyncMock(return_value=_mock_response(_prefixed(explore_payload)))
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)

        adapter = GoogleTrendsAdapter()
        with patch("httpx.AsyncClient", return_value=client_instance):
            with pytest.raises(GoogleTrendsAdapterError):
                await adapter.fetch("starter homes", {})

    @pytest.mark.asyncio
    async def test_malformed_response_raises_adapter_error(self):
        client_instance = MagicMock()
        client_instance.get = AsyncMock(return_value=_mock_response("not json at all"))
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)

        adapter = GoogleTrendsAdapter()
        with patch("httpx.AsyncClient", return_value=client_instance):
            with pytest.raises(GoogleTrendsAdapterError):
                await adapter.fetch("starter homes", {})

    @pytest.mark.asyncio
    async def test_http_error_raises_adapter_error(self):
        client_instance = MagicMock()
        client_instance.get = AsyncMock(side_effect=httpx.HTTPError("boom"))
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)

        adapter = GoogleTrendsAdapter()
        with patch("httpx.AsyncClient", return_value=client_instance):
            with pytest.raises(GoogleTrendsAdapterError):
                await adapter.fetch("starter homes", {})
