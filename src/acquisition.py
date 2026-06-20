"""Asset acquisition orchestrator — Pexels + Pixabay merged candidate pool (D063).

Both sources are searched concurrently for every scene.  Candidates are ranked by
resolution (pixel area); only the winner is downloaded and uploaded to R2.  Losers
are never fetched — no cleanup needed.

Step status rule
---------------
Step asset_acquisition is marked 'complete' when at least MIN_ACQUIRED_FOR_COMPLETE
entries in the manifest have status 'acquired' after the loop completes (counting
pre-existing acquired entries from earlier calls). It is marked 'failed' only when
the total acquired count is zero — i.e. no scene in the run has an asset at all.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

from src.exceptions import PexelsError
from src.models import AssetManifest, ManifestEntry
from src.pexels import PexelsClient, _pick_best_video_file
from src.pixabay_client import PixabayClient
from src.storage import R2Client
from src.wikimedia_client import WikimediaClient

logger = logging.getLogger(__name__)

# Step → 'complete' if at least this many entries are acquired; 'failed' only if 0.
MIN_ACQUIRED_FOR_COMPLETE = 1

# Minimum dimensions to accept a photo candidate.
_MIN_PHOTO_WIDTH = 1920
_MIN_PHOTO_HEIGHT = 1080


@dataclass
class _Candidate:
    """Unified asset candidate from any stock source (metadata only, not downloaded yet)."""

    url: str
    width: int
    height: int
    source: str          # "pexels" | "pixabay" | "wikimedia"
    content_type: str
    ext: str
    attribution: Optional[str] = None   # CC/public-domain credit text (Wikimedia only)
    priority: int = 0                   # Higher = tried first (1 for Wikimedia in historic scenes)


def _resolution_score(c: _Candidate) -> int:
    """Rank candidates by pixel area (higher = better)."""
    return c.width * c.height


def _ext_from_url(url: str) -> str:
    """Extract lowercase file extension from a URL path, defaulting to .jpg."""
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext.lower() if ext else ".jpg"


# ── Per-source search helpers (each returns list[_Candidate]) ─────────────────


def _pexels_video_candidates(pexels: PexelsClient, query: str) -> list[_Candidate]:
    """Search Pexels Videos and return candidates. Sync — call via asyncio.to_thread."""
    try:
        videos = pexels.search_videos(query)
    except PexelsError as exc:
        logger.warning("Pexels video search failed query='%s': %s", query, exc)
        return []
    candidates: list[_Candidate] = []
    for video in videos:
        vfile = _pick_best_video_file(video)
        if vfile and vfile.get("link"):
            candidates.append(
                _Candidate(
                    url=vfile["link"],
                    width=vfile.get("width", 0),
                    height=vfile.get("height", 0),
                    source="pexels",
                    content_type=vfile.get("file_type", "video/mp4"),
                    ext=".mp4",
                )
            )
    return candidates


def _pexels_photo_candidates(pexels: PexelsClient, query: str) -> list[_Candidate]:
    """Search Pexels Photos and return candidates. Sync — call via asyncio.to_thread."""
    try:
        photos = pexels.search_photos(query)
    except PexelsError as exc:
        logger.warning("Pexels photo search failed query='%s': %s", query, exc)
        return []
    candidates: list[_Candidate] = []
    for photo in photos:
        w = photo.get("width", 0)
        h = photo.get("height", 0)
        url = photo.get("src", {}).get("original", "")
        if url and w >= _MIN_PHOTO_WIDTH and h >= _MIN_PHOTO_HEIGHT:
            ext = _ext_from_url(url)
            candidates.append(
                _Candidate(
                    url=url,
                    width=w,
                    height=h,
                    source="pexels",
                    content_type="image/jpeg",
                    ext=ext,
                )
            )
    return candidates


async def _pixabay_video_candidates(pixabay: PixabayClient, query: str) -> list[_Candidate]:
    """Search Pixabay Videos and return candidates."""
    videos = await pixabay.search_videos(query)
    return [
        _Candidate(
            url=v.url,
            width=v.width,
            height=v.height,
            source="pixabay",
            content_type="video/mp4",
            ext=".mp4",
        )
        for v in videos
    ]


async def _pixabay_photo_candidates(pixabay: PixabayClient, query: str) -> list[_Candidate]:
    """Search Pixabay Images and return candidates meeting minimum dimensions."""
    photos = await pixabay.search_photos(query)
    return [
        _Candidate(
            url=p.url,
            width=p.width,
            height=p.height,
            source="pixabay",
            content_type="image/jpeg",
            ext=_ext_from_url(p.url),
        )
        for p in photos
        if p.width >= _MIN_PHOTO_WIDTH and p.height >= _MIN_PHOTO_HEIGHT
    ]


async def _wikimedia_photo_candidates(wikimedia: WikimediaClient, query: str) -> list[_Candidate]:
    """Search Wikimedia Commons for photos and return candidates with attribution."""
    assets = await wikimedia.search_media(query, media_type="photo")
    return [
        _Candidate(
            url=a.url,
            width=a.width,
            height=a.height,
            source="wikimedia",
            content_type="image/jpeg",
            ext=_ext_from_url(a.url),
            attribution=a.attribution,
        )
        for a in assets
    ]


async def _gather_candidates(
    entry: ManifestEntry,
    pexels: PexelsClient,
    pixabay: Optional[PixabayClient],
    wikimedia: Optional[WikimediaClient],
    is_video: bool,
) -> list[_Candidate]:
    """Search all sources concurrently and return a merged, deduplicated candidate list.

    Photo scenes include Wikimedia Commons in the candidate pool.
    For historic scenes (entry.historic=True), Wikimedia candidates are promoted
    to priority=1 so they are tried before Pexels/Pixabay regardless of resolution.
    """
    queries = [q for q in (entry.primary_query, entry.fallback_query) if q]

    tasks = []
    for query in queries:
        if is_video:
            tasks.append(asyncio.to_thread(_pexels_video_candidates, pexels, query))
            if pixabay:
                tasks.append(_pixabay_video_candidates(pixabay, query))
        else:
            tasks.append(asyncio.to_thread(_pexels_photo_candidates, pexels, query))
            if pixabay:
                tasks.append(_pixabay_photo_candidates(pixabay, query))
            if wikimedia:
                tasks.append(_wikimedia_photo_candidates(wikimedia, query))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_candidates: list[_Candidate] = []
    seen_urls: set[str] = set()
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Candidate search task failed: %s", result)
            continue
        for c in result:
            if c.url not in seen_urls:
                seen_urls.add(c.url)
                all_candidates.append(c)

    # Historic scenes: promote Wikimedia candidates so they are tried first.
    if entry.historic:
        for c in all_candidates:
            if c.source == "wikimedia":
                c.priority = 1

    return all_candidates


async def _download_bytes(url: str) -> bytes:
    """Download bytes from a direct CDN URL. Raises httpx.HTTPError on failure."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return resp.content


# ── Public API ────────────────────────────────────────────────────────────────


async def acquire_scene(
    entry: ManifestEntry,
    run_id: str,
    pexels: PexelsClient,
    pixabay: Optional[PixabayClient],
    storage: R2Client,
    wikimedia: Optional[WikimediaClient] = None,
) -> bool:
    """Acquire the best asset for one manifest entry from the merged source pool.

    Searches Pexels, Pixabay (when key present), and Wikimedia Commons (photo scenes
    only) concurrently; merges into a candidate list sorted by priority then resolution;
    downloads only the winner.  Historic scenes give Wikimedia candidates priority=1 so
    they are tried before Pexels/Pixabay.  If the winner download fails, retries the
    next-best candidate.  Marks the entry 'failed' only when every candidate is exhausted.

    Mutates entry.source, entry.file_key, entry.status, entry.attribution in-place on
    success. Returns True on success, False on failure.
    """
    is_video = entry.clip_type == "hard_cut"
    candidates = await _gather_candidates(entry, pexels, pixabay, wikimedia, is_video)
    candidates.sort(key=lambda c: (-c.priority, -_resolution_score(c)))

    if not candidates:
        logger.warning("No candidates found for scene=%s", entry.scene_id)
        entry.status = "failed"
        return False

    folder = "video" if is_video else "images"
    for candidate in candidates:
        try:
            data = await _download_bytes(candidate.url)
            key = f"runs/{run_id}/{folder}/{entry.scene_id}{candidate.ext}"
            storage.upload_bytes(key, data, content_type=candidate.content_type)
            entry.source = candidate.source
            entry.file_key = key
            entry.status = "acquired"
            entry.attribution = candidate.attribution
            logger.info(
                "Acquired %s: scene=%s source=%s key=%s",
                "video" if is_video else "photo",
                entry.scene_id,
                candidate.source,
                key,
            )
            return True
        except Exception as exc:
            logger.warning(
                "Download failed for scene=%s source=%s: %s",
                entry.scene_id,
                candidate.source,
                exc,
            )

    logger.warning("All %d candidates failed for scene=%s", len(candidates), entry.scene_id)
    entry.status = "failed"
    return False


async def run_acquisition(
    run_id: str,
    manifest: AssetManifest,
    pexels: PexelsClient,
    pixabay: Optional[PixabayClient],
    storage: R2Client,
    wikimedia: Optional[WikimediaClient] = None,
    batch_size: int = 20,
) -> dict:
    """Run the full acquisition loop over all pending manifest entries in parallel batches.

    Skips entries already marked 'acquired' (idempotent / resumable). Pending
    entries are processed in batches of batch_size using asyncio.gather.
    A failure in one scene within a batch is caught and logged; the batch
    continues and the manifest entry is marked 'failed'.

    Returns a summary dict:
        acquired  — total entries with status 'acquired' after the loop
        failed    — entries that were attempted this call and could not be acquired
        sources   — acquisition source counts across all acquired entries
    """
    pending = [e for e in manifest.entries if e.status != "acquired"]

    newly_failed = 0
    for batch_start in range(0, len(pending), batch_size):
        batch = pending[batch_start : batch_start + batch_size]
        results = await asyncio.gather(
            *[acquire_scene(entry, run_id, pexels, pixabay, storage, wikimedia) for entry in batch],
            return_exceptions=True,
        )
        for entry, result in zip(batch, results):
            if isinstance(result, Exception):
                logger.error("Unexpected error for scene=%s: %s", entry.scene_id, result)
                entry.status = "failed"
                newly_failed += 1
            elif result is False:
                newly_failed += 1

    total_acquired = sum(1 for e in manifest.entries if e.status == "acquired")
    sources: dict[str, int] = {}
    for entry in manifest.entries:
        if entry.status == "acquired" and entry.source:
            sources[entry.source] = sources.get(entry.source, 0) + 1

    return {"acquired": total_acquired, "failed": newly_failed, "sources": sources}
