"""Freesound API client — search SFX and download preview audio.

Used offline, once, by scripts/seed_sfx_library.py to seed the curated
sfx-library/ R2 prefix (D076). Not called at storyboard-generation or render
time — SFX acquisition is a one-time library-seeding step, not a per-scene
dynamic search (see D008, superseded by D076).

Search is restricted to CC0-licensed results only, so no attribution tracking
is needed. Downloads use Freesound's "preview" tier, which needs only the API
token (no OAuth2) — sufficient quality for short SFX clips.

Clean module; no src/ imports — importable by both worker code and a standalone
script.
"""

import logging

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_SEARCH_API = "https://freesound.org/apiv2/search/text/"
_CC0_LICENSE_FILTER = 'license:"Creative Commons 0"'
_RESULT_FIELDS = "id,name,previews,license,duration,avg_rating,num_downloads,url"


class FreesoundResult(BaseModel):
    """Metadata for one Freesound search result (no audio bytes downloaded yet)."""

    id: int
    name: str
    license: str
    duration: float
    preview_url: str
    avg_rating: float | None = None
    num_downloads: int | None = None
    page_url: str | None = None


class FreesoundClient:
    """Async HTTP client for the Freesound v2 search + preview-download API."""

    def __init__(self, api_key: str) -> None:
        """Initialise with a Freesound API token (FREESOUND_API_KEY)."""
        self._api_key = api_key

    async def search(self, query: str, max_results: int = 15) -> list[FreesoundResult]:
        """Search Freesound for CC0-licensed sounds matching query.

        Returns empty list on any error (fault isolation, D048) — never raises.
        Only CC0 results are returned (_CC0_LICENSE_FILTER), so callers never
        need to track or display attribution.
        """
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    _SEARCH_API,
                    params={
                        "token": self._api_key,
                        "query": query,
                        "filter": _CC0_LICENSE_FILTER,
                        "fields": _RESULT_FIELDS,
                        "page_size": max_results,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Freesound search failed query=%r: %s", query, exc)
            return []

        results: list[FreesoundResult] = []
        for hit in data.get("results", []):
            previews = hit.get("previews") or {}
            preview_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")
            if not preview_url:
                continue
            try:
                results.append(
                    FreesoundResult(
                        id=hit["id"],
                        name=hit.get("name", ""),
                        license=hit.get("license", ""),
                        duration=float(hit.get("duration", 0.0)),
                        preview_url=preview_url,
                        avg_rating=hit.get("avg_rating"),
                        num_downloads=hit.get("num_downloads"),
                        page_url=hit.get("url"),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Skipping malformed Freesound result %r: %s", hit.get("id"), exc)
        return results

    async def download_preview(self, result: FreesoundResult) -> bytes:
        """Download the preview-quality audio for one search result.

        Raises on failure (unlike search()) — the seeding script decides how to
        handle a failed download for a specific candidate (e.g. try the next one).
        """
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(result.preview_url)
            resp.raise_for_status()
            return resp.content
