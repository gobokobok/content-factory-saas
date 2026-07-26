"""Reddit source adapter (P3-S2, D050) — httpx only, no SDK.

Implements `SourceAdapter`: fetches the top search results for a niche from
Reddit and normalizes them into `Signal`s. IO only — never writes artifacts or
trace events itself (the Discovery worker emits trace events around `fetch()`,
D050/D057).

Auth: Reddit's "script"/client-credentials OAuth flow
(`POST https://www.reddit.com/api/v1/access_token`) — a fresh token is requested
on every `fetch()` call. No token caching in v1; acceptable at Discovery's call
volume, revisit if this adapter is called frequently.
"""

from typing import Any

import httpx

from cf_platform.core.schemas import Signal

_ACCESS_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_SEARCH_URL = "https://oauth.reddit.com/search"
_REQUEST_TIMEOUT_SECONDS = 10.0
_DEFAULT_LIMIT = 10


class RedditAdapterError(Exception):
    """Raised when the Reddit adapter cannot fetch signals (missing credentials, HTTP/auth failure)."""


class RedditAdapter:
    """SourceAdapter implementation for Reddit (D050)."""

    def __init__(self, client_id: str, client_secret: str, user_agent: str) -> None:
        """Store Reddit API credentials. Empty values cause fetch() to raise RedditAdapterError."""
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_agent = user_agent

    async def fetch(self, niche: str, params: dict[str, Any]) -> list[Signal]:
        """Search Reddit for niche and return the top posts as normalized Signals.

        Raises RedditAdapterError if credentials are missing or any HTTP call fails —
        the Discovery worker catches this for partial-failure isolation (AC #3).
        """
        if not self._client_id or not self._client_secret or not self._user_agent:
            raise RedditAdapterError("Reddit credentials not configured")

        limit = params.get("limit", _DEFAULT_LIMIT)
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
                token = await self._get_access_token(client)
                response = await client.get(
                    _SEARCH_URL,
                    params={"q": niche, "sort": "relevance", "limit": limit, "type": "link"},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "User-Agent": self._user_agent,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise RedditAdapterError(f"Reddit search request failed: {exc}") from exc

        return [_to_signal(child["data"]) for child in payload.get("data", {}).get("children", [])]

    async def _get_access_token(self, client: httpx.AsyncClient) -> str:
        """Request a client-credentials access token. Raises RedditAdapterError on failure."""
        try:
            response = await client.post(
                _ACCESS_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
                headers={"User-Agent": self._user_agent},
            )
            response.raise_for_status()
            return response.json()["access_token"]
        except httpx.HTTPError as exc:
            raise RedditAdapterError(f"Reddit access token request failed: {exc}") from exc


def _to_signal(post: dict[str, Any]) -> Signal:
    """Normalize a Reddit post payload into a Signal."""
    permalink: str | None = post.get("permalink")
    return Signal(
        source="reddit",
        title=post.get("title", ""),
        url=f"https://www.reddit.com{permalink}" if permalink else None,
        score=float(post.get("score", 0)),
        meta={
            "metric": "upvotes",
            "subreddit": post.get("subreddit", ""),
            "num_comments": post.get("num_comments", 0),
        },
    )
