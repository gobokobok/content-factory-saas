"""YouTube source adapter (P3-S2, D050) — httpx only, no SDK.

Implements `SourceAdapter`: searches YouTube Data API v3 for videos matching a
niche, fetches view-count statistics for the results, and normalizes both into
`Signal`s. IO only — never writes artifacts or trace events itself (the
Discovery worker emits trace events around `fetch()`, D050/D057).
"""

from typing import Any

import httpx

from cf_platform.core.schemas import Signal

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
_REQUEST_TIMEOUT_SECONDS = 10.0
_DEFAULT_MAX_RESULTS = 10


class YouTubeAdapterError(Exception):
    """Raised when the YouTube adapter cannot fetch signals (missing API key, HTTP failure)."""


class YouTubeAdapter:
    """SourceAdapter implementation for YouTube (D050)."""

    def __init__(self, api_key: str) -> None:
        """Store the YouTube Data API v3 key. Empty value causes fetch() to raise YouTubeAdapterError."""
        self._api_key = api_key

    async def fetch(self, niche: str, params: dict[str, Any]) -> list[Signal]:
        """Search YouTube for niche and return matching videos with view counts as Signals.

        Raises YouTubeAdapterError if the API key is missing or any HTTP call fails —
        the Discovery worker catches this for partial-failure isolation (AC #3).
        """
        if not self._api_key:
            raise YouTubeAdapterError("YouTube API key not configured")

        max_results = params.get("max_results", _DEFAULT_MAX_RESULTS)
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
                search_response = await client.get(
                    _SEARCH_URL,
                    params={
                        "part": "snippet",
                        "q": niche,
                        "type": "video",
                        "order": "relevance",
                        "maxResults": max_results,
                        "key": self._api_key,
                    },
                )
                search_response.raise_for_status()
                search_payload = search_response.json()

                video_ids = [item["id"]["videoId"] for item in search_payload.get("items", [])]
                view_counts = await self._fetch_view_counts(client, video_ids)
        except httpx.HTTPError as exc:
            raise YouTubeAdapterError(f"YouTube search request failed: {exc}") from exc

        return [
            _to_signal(item, view_counts.get(item["id"]["videoId"], 0))
            for item in search_payload.get("items", [])
        ]

    async def _fetch_view_counts(self, client: httpx.AsyncClient, video_ids: list[str]) -> dict[str, int]:
        """Return {video_id: view_count} for video_ids. Returns {} if video_ids is empty."""
        if not video_ids:
            return {}
        try:
            response = await client.get(
                _VIDEOS_URL,
                params={"part": "statistics", "id": ",".join(video_ids), "key": self._api_key},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise YouTubeAdapterError(f"YouTube videos request failed: {exc}") from exc
        return {item["id"]: int(item["statistics"].get("viewCount", 0)) for item in payload.get("items", [])}


def _to_signal(item: dict[str, Any], view_count: int) -> Signal:
    """Normalize a YouTube search-result item + view count into a Signal."""
    snippet = item.get("snippet", {})
    video_id = item["id"]["videoId"]
    return Signal(
        source="youtube",
        title=snippet.get("title", ""),
        url=f"https://www.youtube.com/watch?v={video_id}",
        score=float(view_count),
        meta={"metric": "views", "channel": snippet.get("channelTitle", "")},
    )
