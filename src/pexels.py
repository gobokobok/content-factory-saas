"""Pexels API client — search, select best asset, download, and upload to R2.

Asset selection strategy
------------------------
The final output is a 9:16 vertical Short (1080×1920). Source assets are
acquired in landscape orientation and cropped/scaled by FFmpeg at render time.

Video (hard_cut scenes):
    Query Pexels Videos API with orientation=landscape. From the most-relevant
    result, pick the highest-height video file where height <= 1080px.
    Among files at the same height, prefer wider (more detail). UHD/4K files
    are excluded to keep download sizes manageable.

Photo (still_with_motion / animated scenes):
    Query Pexels Photos API with orientation=landscape. Require width >= 1920
    AND height >= 1080 (minimum source resolution for a 1080p render). Among
    qualifying photos, minimise excess area = (w × h) − (1920 × 1080) to keep
    downloads lean while preserving enough pixels for FFmpeg scaling.
    If no photo meets the minimum, the result is None → caller tries the
    fallback query, then hands off to Replicate (E3-S2/E3-S3).
"""

import logging
import os
import time
from urllib.parse import urlparse

import requests

from src.clip_reranker import get_reranker
from src.exceptions import CLIPError, PexelsError
from src.models import ManifestEntry, PexelsAcquireResult
from src.storage import R2Client

logger = logging.getLogger(__name__)

_PHOTOS_BASE = "https://api.pexels.com/v1"
_VIDEOS_BASE = "https://api.pexels.com/videos"
_TARGET_WIDTH = 1920
_TARGET_HEIGHT = 1080
_MAX_VIDEO_HEIGHT = 720   # cap video downloads at 720p — 1080p files are 4–8× larger with no benefit for Shorts
_MAX_CLIP_DURATION = 30   # skip clips longer than 30s — we use at most 4–8s per scene
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds; doubles each retry: 1s, 2s, 4s


# ── Asset-selection helpers ───────────────────────────────────────────────────


def _pick_best_video_file(video: dict) -> dict | None:
    """Pick the best video file capped at 720p from a Pexels video object.

    Skips the video entirely when its duration exceeds MAX_CLIP_DURATION — we
    only use 4–8s per scene and downloading a 30-min clip wastes bandwidth.
    Among files with height <= 720, picks the highest available (720p preferred
    over 540p/480p). Returns None if no file meets the constraints.
    """
    if video.get("duration", 0) > _MAX_CLIP_DURATION:
        return None
    candidates = [
        f for f in video.get("video_files", [])
        if f.get("height") and f.get("width") and f["height"] <= _MAX_VIDEO_HEIGHT
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda f: (f["height"], f["width"]))


def _pick_best_photo(photos: list[dict]) -> dict | None:
    """Pick the photo closest to 1920×1080 without going under on either dimension.

    Requires width >= 1920 AND height >= 1080. Among qualifying photos,
    minimises excess area to keep the download size lean. Returns None if no
    photo meets the minimum dimensions.
    """
    candidates = [
        p for p in photos
        if p.get("width", 0) >= _TARGET_WIDTH and p.get("height", 0) >= _TARGET_HEIGHT
    ]
    if not candidates:
        return None
    target_area = _TARGET_WIDTH * _TARGET_HEIGHT
    return min(candidates, key=lambda p: p["width"] * p["height"] - target_area)


def _pick_first_qualifying_photo(photos: list[dict]) -> dict | None:
    """Return the first photo meeting 1920×1080 minimum dimensions.

    Used after CLIP reranking so the ordering already encodes relevance — we
    just want the first result that satisfies the size floor. Returns None if
    no photo meets the minimum dimensions.
    """
    for photo in photos:
        if (
            photo.get("width", 0) >= _TARGET_WIDTH
            and photo.get("height", 0) >= _TARGET_HEIGHT
        ):
            return photo
    return None


def _ext_from_url(url: str) -> str:
    """Extract lowercase file extension from a URL path, defaulting to .jpg."""
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext.lower() if ext else ".jpg"


def _content_type_from_ext(ext: str) -> str:
    """Map a file extension to its MIME type, defaulting to image/jpeg."""
    mapping = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
    }
    return mapping.get(ext.lower(), "image/jpeg")


def _ext_from_content_type(content_type: str) -> str:
    """Map a MIME type to a file extension, defaulting to .mp4 for video."""
    mapping = {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/x-msvideo": ".avi",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    base = content_type.split(";")[0].strip()
    return mapping.get(base, ".mp4")


# ── Pexels HTTP client ────────────────────────────────────────────────────────


class PexelsClient:
    """HTTP client for the Pexels Photos and Videos APIs."""

    def __init__(self, api_key: str, per_page: int = 5) -> None:
        """Initialise with API key and result page size."""
        self._session = requests.Session()
        self._session.headers.update({"Authorization": api_key})
        self._per_page = per_page

    def _get(self, url: str, params: dict) -> dict:
        """GET with exponential backoff on 429 (up to _MAX_RETRIES attempts).

        Returns parsed JSON on 200. Raises PexelsError on non-200 response or
        when rate-limit retries are exhausted.
        """
        for attempt in range(_MAX_RETRIES):
            resp = self._session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429:
                wait = _BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Pexels rate limit (429) — retrying in %.1fs (attempt %d/%d)",
                    wait,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(wait)
                continue
            raise PexelsError(
                f"Pexels API error HTTP {resp.status_code}: {resp.text[:200]}"
            )
        raise PexelsError(f"Pexels rate limit exceeded after {_MAX_RETRIES} retries")

    def search_videos(self, query: str) -> list[dict]:
        """Search Pexels Videos API. Returns list of video objects."""
        data = self._get(
            f"{_VIDEOS_BASE}/search",
            {"query": query, "per_page": self._per_page, "orientation": "landscape"},
        )
        return data.get("videos", [])

    def search_photos(self, query: str) -> list[dict]:
        """Search Pexels Photos API. Returns list of photo objects."""
        data = self._get(
            f"{_PHOTOS_BASE}/search",
            {"query": query, "per_page": self._per_page, "orientation": "landscape"},
        )
        return data.get("photos", [])

    def _download_bytes(self, url: str) -> bytes:
        """Download asset bytes from a direct URL. Raises PexelsError on failure."""
        resp = self._session.get(url, timeout=60)
        if resp.status_code != 200:
            raise PexelsError(
                f"Asset download failed (HTTP {resp.status_code}): {url}"
            )
        return resp.content

    def _acquire_video(
        self,
        query: str,
        scene_id: str,
        run_id: str,
        storage: R2Client,
    ) -> PexelsAcquireResult | None:
        """Search and download a video clip from Pexels.

        When CLIP reranking is enabled, reorders results by visual-semantic
        similarity before iterating. Takes the first reranked result that has
        an acceptable video file. Returns None if no file meets the resolution
        criteria.
        """
        videos = self.search_videos(query)
        reranker = get_reranker()
        if reranker is not None:
            try:
                videos = reranker.rerank_videos(videos, query)
            except CLIPError as exc:
                logger.warning(
                    "CLIP reranking failed for scene=%s, using Pexels order: %s",
                    scene_id,
                    exc,
                )
        video_file = None
        for video in videos:
            video_file = _pick_best_video_file(video)
            if video_file:
                break
        if video_file is None:
            logger.debug(
                "No suitable video for scene=%s query='%s'", scene_id, query
            )
            return None

        data = self._download_bytes(video_file["link"])
        ext = _ext_from_content_type(video_file.get("file_type", "video/mp4"))
        key = f"runs/{run_id}/video/{scene_id}{ext}"
        storage.upload_bytes(key, data, content_type=video_file.get("file_type", "video/mp4"))
        logger.info("Acquired video: scene=%s key=%s", scene_id, key)
        return PexelsAcquireResult(scene_id=scene_id, source="pexels", file_key=key)

    def _acquire_photo(
        self,
        query: str,
        scene_id: str,
        run_id: str,
        storage: R2Client,
    ) -> PexelsAcquireResult | None:
        """Search and download a photo from Pexels.

        When CLIP reranking is enabled, reorders results by visual-semantic
        similarity and picks the first qualifying photo (>= 1920x1080). When
        disabled, picks the photo with the minimum excess area across all
        results. Returns None if no photo meets the minimum dimensions.
        """
        photos = self.search_photos(query)
        reranker = get_reranker()
        if reranker is not None:
            try:
                photos = reranker.rerank_photos(photos, query)
                photo = _pick_first_qualifying_photo(photos)
            except CLIPError as exc:
                logger.warning(
                    "CLIP reranking failed for scene=%s, using Pexels order: %s",
                    scene_id,
                    exc,
                )
                photo = _pick_best_photo(photos)
        else:
            photo = _pick_best_photo(photos)
        if photo is None:
            logger.debug(
                "No suitable photo for scene=%s query='%s'", scene_id, query
            )
            return None

        url = photo["src"]["original"]
        data = self._download_bytes(url)
        ext = _ext_from_url(url)
        key = f"runs/{run_id}/images/{scene_id}{ext}"
        storage.upload_bytes(key, data, content_type=_content_type_from_ext(ext))
        logger.info("Acquired photo: scene=%s key=%s", scene_id, key)
        return PexelsAcquireResult(scene_id=scene_id, source="pexels", file_key=key)

    def acquire_for_entry(
        self,
        entry: ManifestEntry,
        run_id: str,
        storage: R2Client,
    ) -> PexelsAcquireResult | None:
        """Acquire the best Pexels asset for one manifest entry.

        Tries primary_query then fallback_query. hard_cut → Videos API /
        video/ prefix; still_with_motion + animated → Photos API / images/
        prefix. Returns PexelsAcquireResult on success, None when both
        queries yield no suitable asset. Raises PexelsError on API failure.
        """
        is_video = entry.clip_type == "hard_cut"
        for query in (entry.primary_query, entry.fallback_query):
            if is_video:
                result = self._acquire_video(query, entry.scene_id, run_id, storage)
            else:
                result = self._acquire_photo(query, entry.scene_id, run_id, storage)
            if result is not None:
                return result
        logger.info(
            "Pexels exhausted for scene=%s — both queries returned no match",
            entry.scene_id,
        )
        return None
