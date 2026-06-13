"""Tests for the Reddit source adapter (P3-S2, D050)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from cf_platform.core.schemas import Signal
from cf_platform.sources.reddit import RedditAdapter, RedditAdapterError


def _mock_client(token_response: dict, search_response: dict) -> MagicMock:
    """Build a mocked httpx.AsyncClient whose post()/get() return canned JSON payloads."""
    token_mock = MagicMock()
    token_mock.raise_for_status = MagicMock()
    token_mock.json = MagicMock(return_value=token_response)

    search_mock = MagicMock()
    search_mock.raise_for_status = MagicMock()
    search_mock.json = MagicMock(return_value=search_response)

    client_instance = MagicMock()
    client_instance.post = AsyncMock(return_value=token_mock)
    client_instance.get = AsyncMock(return_value=search_mock)
    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=False)
    return client_instance


class TestRedditAdapterCredentials:
    """fetch() raises RedditAdapterError when any credential is missing (D048 partial-failure isolation)."""

    @pytest.mark.asyncio
    async def test_missing_client_id_raises(self):
        adapter = RedditAdapter(client_id="", client_secret="secret", user_agent="ua")
        with pytest.raises(RedditAdapterError):
            await adapter.fetch("starter homes", {})

    @pytest.mark.asyncio
    async def test_missing_user_agent_raises(self):
        adapter = RedditAdapter(client_id="id", client_secret="secret", user_agent="")
        with pytest.raises(RedditAdapterError):
            await adapter.fetch("starter homes", {})


class TestRedditAdapterFetch:
    """fetch() exchanges credentials for a token, searches, and normalizes results into Signals."""

    @pytest.mark.asyncio
    async def test_fetch_normalizes_posts_into_signals(self):
        search_response = {
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "Starter homes are disappearing",
                            "score": 1234,
                            "permalink": "/r/Economics/comments/abc123/starter_homes/",
                            "subreddit": "Economics",
                            "num_comments": 56,
                        }
                    }
                ]
            }
        }
        client_instance = _mock_client({"access_token": "tok123"}, search_response)

        adapter = RedditAdapter(client_id="id", client_secret="secret", user_agent="ua")
        with patch("httpx.AsyncClient", return_value=client_instance):
            signals = await adapter.fetch("starter homes", {})

        assert signals == [
            Signal(
                source="reddit",
                title="Starter homes are disappearing",
                url="https://www.reddit.com/r/Economics/comments/abc123/starter_homes/",
                score=1234.0,
                meta={"metric": "upvotes", "subreddit": "Economics", "num_comments": 56},
            )
        ]

        # access token requested via client_credentials grant with Basic auth
        _, post_kwargs = client_instance.post.call_args
        assert post_kwargs["data"] == {"grant_type": "client_credentials"}
        assert post_kwargs["auth"] == ("id", "secret")

        # search request authenticated with the bearer token
        _, get_kwargs = client_instance.get.call_args
        assert get_kwargs["headers"]["Authorization"] == "Bearer tok123"
        assert get_kwargs["params"]["q"] == "starter homes"

    @pytest.mark.asyncio
    async def test_fetch_empty_results(self):
        client_instance = _mock_client({"access_token": "tok123"}, {"data": {"children": []}})

        adapter = RedditAdapter(client_id="id", client_secret="secret", user_agent="ua")
        with patch("httpx.AsyncClient", return_value=client_instance):
            signals = await adapter.fetch("starter homes", {})

        assert signals == []

    @pytest.mark.asyncio
    async def test_token_request_failure_raises_adapter_error(self):
        client_instance = MagicMock()
        client_instance.post = AsyncMock(side_effect=httpx.HTTPError("boom"))
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)

        adapter = RedditAdapter(client_id="id", client_secret="secret", user_agent="ua")
        with patch("httpx.AsyncClient", return_value=client_instance):
            with pytest.raises(RedditAdapterError):
                await adapter.fetch("starter homes", {})

    @pytest.mark.asyncio
    async def test_search_request_failure_raises_adapter_error(self):
        token_mock = MagicMock()
        token_mock.raise_for_status = MagicMock()
        token_mock.json = MagicMock(return_value={"access_token": "tok123"})

        client_instance = MagicMock()
        client_instance.post = AsyncMock(return_value=token_mock)
        client_instance.get = AsyncMock(side_effect=httpx.HTTPError("boom"))
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)

        adapter = RedditAdapter(client_id="id", client_secret="secret", user_agent="ua")
        with patch("httpx.AsyncClient", return_value=client_instance):
            with pytest.raises(RedditAdapterError):
                await adapter.fetch("starter homes", {})
