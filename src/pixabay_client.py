"""Pixabay API client — search videos and photos by keyword.

Free tier: 100 req/min. Pixabay Content Licence (commercial use OK, no attribution required).
Clean module; no src/ imports — directly importable by P9 AcquisitionWorker.
"""

import logging

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_VIDEOS_API = "https://pixabay.com/api/videos/"
_IMAGES_API = "https://pixabay.com/api/"


class PixabayVideo(BaseModel):
    """Metadata for one Pixabay video result (no bytes downloaded yet)."""

    url: str
    width: int
    height: int
    duration_seconds: int
    page_url: str


class PixabayPhoto(BaseModel):
    """Metadata for one Pixabay photo result (no bytes downloaded yet)."""

    url: str
    width: int
    height: int
    page_url: str


class PixabayClient:
    """Async HTTP client for the Pixabay Videos and Images APIs."""

    def __init__(self, api_key: str, per_page: int = 10) -> None:
        """Initialise with API key and result page size."""
        self._api_key = api_key
        self._per_page = per_page

    async def search_videos(self, query: str) -> list[PixabayVideo]:
        """Search Pixabay Videos API. Returns empty list on any error (fault isolation, D048).

        Prefers 'medium' (1280×720) over 'large' (1920×1080) — 720p is sufficient
        for Shorts and reduces download size by ~4×. Also skips clips longer than
        30s since we only use 4–8s per scene.
        """
        _MAX_CLIP_DURATION = 30

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    _VIDEOS_API,
                    params={
                        "key": self._api_key,
                        "q": query,
                        "per_page": self._per_page,
                        "safesearch": "true",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Pixabay video search failed query='%s': %s", query, exc)
            return []

        results: list[PixabayVideo] = []
        for hit in data.get("hits", []):
            if hit.get("duration", 0) > _MAX_CLIP_DURATION:
                continue
            for size in ("medium", "large"):
                vfile = hit.get("videos", {}).get(size, {})
                url = vfile.get("url", "")
                if url:
                    results.append(
                        PixabayVideo(
                            url=url,
                            width=vfile.get("width", 0),
                            height=vfile.get("height", 0),
                            duration_seconds=hit.get("duration", 0),
                            page_url=hit.get("pageURL", ""),
                        )
                    )
                    break
        return results

    async def search_photos(self, query: str) -> list[PixabayPhoto]:
        """Search Pixabay Images API. Returns empty list on any error (fault isolation, D048)."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    _IMAGES_API,
                    params={
                        "key": self._api_key,
                        "q": query,
                        "per_page": self._per_page,
                        "safesearch": "true",
                        "image_type": "photo",
                        "orientation": "horizontal",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Pixabay photo search failed query='%s': %s", query, exc)
            return []

        results: list[PixabayPhoto] = []
        for hit in data.get("hits", []):
            url = hit.get("largeImageURL", "")
            if url:
                results.append(
                    PixabayPhoto(
                        url=url,
                        width=hit.get("imageWidth", 0),
                        height=hit.get("imageHeight", 0),
                        page_url=hit.get("pageURL", ""),
                    )
                )
        return results
