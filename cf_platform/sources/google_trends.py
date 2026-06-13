"""Google Trends source adapter (P3-S2, D050) — raw httpx, no pytrends dependency.

Implements `SourceAdapter` against Google's **unofficial** Trends API: a
two-step handshake against `trends.google.com/trends/api/explore` (returns a
per-widget token) and `.../trends/api/widgetdata/relatedsearches` (returns
related search queries for a niche, scored by relative interest 0-100).

This is unofficial and undocumented — Google can change response shapes or
rate-limit datacenter IPs without notice. All parsing is wrapped narrowly so
any failure raises `GoogleTrendsAdapterError`; the Discovery worker catches
this for partial-failure isolation (AC #3) and records an error trace event
for this source while Reddit/YouTube continue normally. If this adapter
becomes unreliable in DEV/PROD, see the P8+ candidate in BACKLOG.md (EPIC 28)
to evaluate a managed scraping provider (Apify/ScrapeBadger) behind this same
`SourceAdapter` Protocol — no Discovery worker changes required.

All Google-specific parsing (response prefix stripping, widget/token lookup,
ranked-keyword extraction) is isolated in this module.
"""

import json
from typing import Any

import httpx

from cf_platform.core.schemas import Signal

_EXPLORE_URL = "https://trends.google.com/trends/api/explore"
_RELATED_SEARCHES_URL = "https://trends.google.com/trends/api/widgetdata/relatedsearches"
_REQUEST_TIMEOUT_SECONDS = 10.0
_RESPONSE_PREFIX = ")]}',"
_RELATED_QUERIES_WIDGET_ID = "RELATED_QUERIES"
_RANK_LIST_NAMES = ["top", "rising"]


class GoogleTrendsAdapterError(Exception):
    """Raised when the Google Trends adapter cannot fetch signals (HTTP, parsing, or token failure)."""


class GoogleTrendsAdapter:
    """SourceAdapter implementation for Google Trends' unofficial API (D050)."""

    async def fetch(self, niche: str, params: dict[str, Any]) -> list[Signal]:
        """Return related-search Signals for niche from Google Trends' "related queries" widget.

        Raises GoogleTrendsAdapterError on any HTTP or parsing failure — the
        Discovery worker catches this for partial-failure isolation (AC #3).
        """
        geo = params.get("geo", "")
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
                widget = await self._fetch_related_queries_widget(client, niche, geo)
                return await self._fetch_related_searches(client, widget)
        except httpx.HTTPError as exc:
            raise GoogleTrendsAdapterError(f"Google Trends request failed: {exc}") from exc
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise GoogleTrendsAdapterError(f"Google Trends response could not be parsed: {exc}") from exc

    async def _fetch_related_queries_widget(
        self, client: httpx.AsyncClient, niche: str, geo: str
    ) -> dict[str, Any]:
        """Return the RELATED_QUERIES widget descriptor (token + request) for niche."""
        explore_req = {
            "comparisonItem": [{"keyword": niche, "geo": geo, "time": "today 12-m"}],
            "category": 0,
            "property": "",
        }
        response = await client.get(
            _EXPLORE_URL,
            params={"hl": "en-US", "tz": "0", "req": json.dumps(explore_req)},
        )
        response.raise_for_status()
        payload = _parse_json_with_prefix(response.text)

        for widget in payload["widgets"]:
            if widget["id"] == _RELATED_QUERIES_WIDGET_ID:
                return widget
        raise GoogleTrendsAdapterError("No RELATED_QUERIES widget in Google Trends response")

    async def _fetch_related_searches(self, client: httpx.AsyncClient, widget: dict[str, Any]) -> list[Signal]:
        """Fetch and normalize related search queries for the RELATED_QUERIES widget."""
        response = await client.get(
            _RELATED_SEARCHES_URL,
            params={
                "hl": "en-US",
                "tz": "0",
                "req": json.dumps(widget["request"]),
                "token": widget["token"],
            },
        )
        response.raise_for_status()
        payload = _parse_json_with_prefix(response.text)

        ranked_lists = payload["default"]["rankedList"]
        signals: list[Signal] = []
        for rank_list_index, ranked_list in enumerate(ranked_lists):
            rank_list_name = _RANK_LIST_NAMES[rank_list_index] if rank_list_index < len(_RANK_LIST_NAMES) else "other"
            for keyword in ranked_list["rankedKeyword"]:
                signals.append(
                    Signal(
                        source="google_trends",
                        title=keyword["query"],
                        url=None,
                        score=float(keyword.get("value", 0)),
                        meta={"metric": "relative_interest", "rank_list": rank_list_name},
                    )
                )
        return signals


def _parse_json_with_prefix(text: str) -> dict[str, Any]:
    """Strip Google's anti-XSSI `)]}',` prefix and parse the remaining JSON body."""
    if text.startswith(_RESPONSE_PREFIX):
        text = text[len(_RESPONSE_PREFIX) :]
    return json.loads(text)
