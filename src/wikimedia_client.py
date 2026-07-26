"""Wikimedia Commons client — search media and fetch person photos.

No API key required. Assets are public-domain or CC-licensed; attribution must
be stored per asset in the manifest (WikimediaAsset.attribution).
Clean module; no src/ imports — directly importable by P9 AcquisitionWorker.
"""

import logging
from typing import Literal

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

# Wikimedia / Wikipedia API guidelines require a descriptive User-Agent.
# Without it, requests from shared IPs (e.g. Railway) may be rate-limited or blocked.
_HEADERS = {
    "User-Agent": "ContentFactory/1.0 (https://github.com/gobokobok/content-factory-saas)"
}

# Minimum width (px) to accept a photo from Commons.
_MIN_PHOTO_WIDTH = 800

# MIME types accepted for each media_type mode.
_PHOTO_MIMES = {"image/jpeg", "image/png", "image/webp"}


class WikimediaAsset(BaseModel):
    """Metadata for one Wikimedia Commons or Wikipedia asset (no bytes downloaded yet)."""

    url: str
    width: int
    height: int
    title: str
    licence: str
    attribution: str


class WikimediaClient:
    """Async HTTP client for Wikimedia Commons and Wikipedia APIs."""

    def __init__(self, limit: int = 10) -> None:
        """Initialise with default result page size."""
        self._limit = limit

    async def search_media(
        self,
        query: str,
        media_type: Literal["photo", "video"] = "photo",
        limit: int | None = None,
    ) -> list[WikimediaAsset]:
        """Search Wikimedia Commons for photos or videos matching query.

        Filters results by MIME type; photos must meet the minimum width threshold.
        Returns empty list on any API or network error (fault isolation, D048).
        """
        per_page = limit or self._limit
        params = {
            "action": "query",
            "generator": "search",
            "gsrnamespace": "6",
            "gsrsearch": query,
            "gsrlimit": str(per_page),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiextmetadatafilter": "LicenseShortName|Artist",
            "format": "json",
            "formatversion": "2",
        }
        try:
            async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
                resp = await client.get(_COMMONS_API, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Wikimedia Commons search failed query='%s': %s", query, exc)
            return []

        pages = data.get("query", {}).get("pages", [])
        # formatversion=2 returns a list; older format returns a dict keyed by page id.
        if isinstance(pages, dict):
            pages = list(pages.values())

        results: list[WikimediaAsset] = []
        for page in pages:
            info_list = page.get("imageinfo", [])
            if not info_list:
                continue
            info = info_list[0]
            mime: str = info.get("mime", "")
            url: str = info.get("url", "")
            width: int = info.get("width", 0)
            height: int = info.get("height", 0)

            if not url:
                continue

            if media_type == "photo":
                if mime not in _PHOTO_MIMES:
                    continue
                if width < _MIN_PHOTO_WIDTH:
                    continue
            else:  # video
                if not mime.startswith("video/"):
                    continue

            meta = info.get("extmetadata", {})
            licence = meta.get("LicenseShortName", {}).get("value", "Unknown")
            artist_raw = meta.get("Artist", {}).get("value", "")
            artist = _strip_html(artist_raw) or "Unknown author"
            title = page.get("title", "").removeprefix("File:")
            attribution = f'"{title}" by {artist} ({licence})'

            results.append(
                WikimediaAsset(
                    url=url,
                    width=width,
                    height=height,
                    title=title,
                    licence=licence,
                    attribution=attribution,
                )
            )
        return results

    async def fetch_person_photo(self, person_name: str) -> WikimediaAsset | None:
        """Fetch the lead portrait image for a named person from Wikipedia.

        Requests both 'original' and 'thumbnail' (1000px) in one API call.
        'original' is preferred; 'thumbnail' serves as fallback for articles
        where the original-size metadata is absent (common for paintings/engravings).
        Returns None when no image exists or on any error.
        """
        params = {
            "action": "query",
            "titles": person_name,
            "prop": "pageimages",
            "piprop": "original|thumbnail",
            "pithumbsize": "1000",
            "format": "json",
            "formatversion": "2",
        }
        try:
            async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
                resp = await client.get(_WIKIPEDIA_API, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("Wikipedia person photo failed person='%s': %s", person_name, exc)
            return None

        pages = data.get("query", {}).get("pages", [])
        if isinstance(pages, dict):
            pages = list(pages.values())

        for page in pages:
            # Prefer original (full resolution); fall back to thumbnail (1000px).
            image = page.get("original") or page.get("thumbnail")
            if not image:
                continue
            url = image.get("source", "")
            width = image.get("width", 0)
            height = image.get("height", 0)
            if not url:
                continue
            logger.info(
                "Wikipedia portrait found person='%s' url=%s size=%dx%d",
                person_name, url, width, height,
            )
            attribution = f"Photo of {person_name} via Wikipedia"
            return WikimediaAsset(
                url=url,
                width=width,
                height=height,
                title=person_name,
                licence="Via Wikipedia",
                attribution=attribution,
            )
        logger.info("Wikipedia portrait not found person='%s'", person_name)
        return None


def _strip_html(text: str) -> str:
    """Remove HTML tags from text (minimal tag-stripping without regex or lxml)."""
    result: list[str] = []
    inside_tag = False
    for ch in text:
        if ch == "<":
            inside_tag = True
        elif ch == ">":
            inside_tag = False
        elif not inside_tag:
            result.append(ch)
    return "".join(result).strip()
