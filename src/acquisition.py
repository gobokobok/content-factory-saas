"""Asset acquisition orchestrator — Pexels + Pixabay merged candidate pool (D063).

Both sources are searched concurrently for every scene.  Candidates are ranked by
resolution (pixel area); only the winner is downloaded and uploaded to R2.  Losers
are never fetched — no cleanup needed.

QA gate (P8-S4)
---------------
Every candidate is checked for minimum resolution, video duration fit, and
optionally CLIP semantic similarity before being accepted.  On QA failure the
next candidate in priority+resolution order is tried.  If no candidate passes QA,
the best-scoring available candidate is accepted (never leave a scene empty).

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
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx

from src.exceptions import PexelsError
from src.footage_qa import QAResult, pick_best, qa_score
from src.models import AssetManifest, ManifestEntry
from src.pexels import PexelsClient, _pick_best_video_file
from src.pixabay_client import PixabayClient
from src.storage import R2Client
from src.wikimedia_client import WikimediaClient

logger = logging.getLogger(__name__)

# Step → 'complete' if at least this many entries are acquired; 'failed' only if 0.
MIN_ACQUIRED_FOR_COMPLETE = 1

# Minimum dimensions to accept a photo candidate (legacy pre-filter).
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
    duration_seconds: Optional[float] = None  # Video duration for duration QA (P8-S4)
    from_fallback: bool = False          # True when sourced from entry.fallback_query (P8-S4)


def _resolution_score(c: _Candidate) -> int:
    """Rank candidates by pixel area (higher = better)."""
    return c.width * c.height


def _ext_from_url(url: str) -> str:
    """Extract lowercase file extension from a URL path, defaulting to .jpg."""
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext.lower() if ext else ".jpg"


# ── Per-source search helpers (each returns list[_Candidate]) ─────────────────


def _pexels_video_candidates(
    pexels: PexelsClient, query: str, from_fallback: bool = False
) -> list[_Candidate]:
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
            raw_duration = video.get("duration")
            candidates.append(
                _Candidate(
                    url=vfile["link"],
                    width=vfile.get("width", 0),
                    height=vfile.get("height", 0),
                    source="pexels",
                    content_type=vfile.get("file_type", "video/mp4"),
                    ext=".mp4",
                    duration_seconds=float(raw_duration) if raw_duration else None,
                    from_fallback=from_fallback,
                )
            )
    return candidates


def _pexels_photo_candidates(
    pexels: PexelsClient, query: str, from_fallback: bool = False
) -> list[_Candidate]:
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
                    from_fallback=from_fallback,
                )
            )
    return candidates


async def _pixabay_video_candidates(
    pixabay: PixabayClient, query: str, from_fallback: bool = False
) -> list[_Candidate]:
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
            duration_seconds=float(v.duration_seconds) if v.duration_seconds else None,
            from_fallback=from_fallback,
        )
        for v in videos
    ]


async def _pixabay_photo_candidates(
    pixabay: PixabayClient, query: str, from_fallback: bool = False
) -> list[_Candidate]:
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
            from_fallback=from_fallback,
        )
        for p in photos
        if p.width >= _MIN_PHOTO_WIDTH and p.height >= _MIN_PHOTO_HEIGHT
    ]


async def _wikimedia_photo_candidates(
    wikimedia: WikimediaClient, query: str, from_fallback: bool = False
) -> list[_Candidate]:
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
            from_fallback=from_fallback,
        )
        for a in assets
    ]


def _build_search_tasks(
    entry: ManifestEntry,
    pexels: PexelsClient,
    pixabay: Optional[PixabayClient],
    wikimedia: Optional[WikimediaClient],
    is_video: bool,
    query: str,
    from_fallback: bool,
) -> list:
    """Build a list of concurrent search tasks for one query string.

    Returns awaitable coroutines / thread wrappers for each source.
    """
    tasks = []
    if is_video:
        tasks.append(
            asyncio.to_thread(_pexels_video_candidates, pexels, query, from_fallback)
        )
        if pixabay:
            tasks.append(_pixabay_video_candidates(pixabay, query, from_fallback))
    else:
        tasks.append(
            asyncio.to_thread(_pexels_photo_candidates, pexels, query, from_fallback)
        )
        if pixabay:
            tasks.append(_pixabay_photo_candidates(pixabay, query, from_fallback))
        if wikimedia:
            tasks.append(_wikimedia_photo_candidates(wikimedia, query, from_fallback))
    return tasks


async def _gather_candidates(
    entry: ManifestEntry,
    pexels: PexelsClient,
    pixabay: Optional[PixabayClient],
    wikimedia: Optional[WikimediaClient],
    is_video: bool,
) -> list[_Candidate]:
    """Search all sources concurrently and return a merged, deduplicated candidate list.

    Primary-query candidates are tagged from_fallback=False; fallback-query
    candidates are tagged from_fallback=True.  Photo scenes include Wikimedia
    Commons.  Historic scenes promote Wikimedia candidates to priority=1.
    """
    primary_tasks = []
    fallback_tasks = []

    if entry.primary_query:
        primary_tasks = _build_search_tasks(
            entry, pexels, pixabay, wikimedia, is_video, entry.primary_query, False
        )
    if entry.fallback_query:
        fallback_tasks = _build_search_tasks(
            entry, pexels, pixabay, wikimedia, is_video, entry.fallback_query, True
        )

    all_tasks = primary_tasks + fallback_tasks
    if not all_tasks:
        return []

    results = await asyncio.gather(*all_tasks, return_exceptions=True)

    primary_results = results[: len(primary_tasks)]
    fallback_results = results[len(primary_tasks) :]

    all_candidates: list[_Candidate] = []
    seen_urls: set[str] = set()

    for result_group in (primary_results, fallback_results):
        for result in result_group:
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


_DOWNLOAD_HEADERS = {
    # Wikimedia CDN (upload.wikimedia.org) returns 403 to requests with no User-Agent.
    "User-Agent": "ContentFactory/1.0 (https://github.com/gobokobok/content-factory-saas)"
}


async def _download_bytes(url: str) -> bytes:
    """Download bytes from a direct CDN URL. Raises httpx.HTTPError on failure."""
    async with httpx.AsyncClient(timeout=60, headers=_DOWNLOAD_HEADERS) as client:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return resp.content


def _apply_entry_fields(
    entry: ManifestEntry,
    candidate: _Candidate,
    key: str,
    qa_result: QAResult,
) -> None:
    """Write all acquisition + QA fields onto a manifest entry in-place."""
    entry.source = candidate.source
    entry.file_key = key
    entry.status = "acquired"
    entry.attribution = candidate.attribution
    entry.fallback_used = candidate.from_fallback
    entry.qa_passed = qa_result.passed
    entry.qa_resolution_ok = qa_result.resolution_ok
    entry.qa_duration_ok = qa_result.duration_ok
    entry.qa_clip_score = qa_result.clip_score


# ── Public API ────────────────────────────────────────────────────────────────


async def _try_person_photo(
    entry: ManifestEntry,
    run_id: str,
    wikimedia: WikimediaClient,
    storage: R2Client,
) -> bool:
    """Attempt to acquire a Wikipedia portrait for a named person.

    Calls fetch_person_photo; on success downloads and uploads the image, sets
    entry.source="wikimedia_person", and returns True.  Returns False when the
    Wikipedia API returns no image or download fails — caller then falls back to
    generic stock search.
    """
    asset = await wikimedia.fetch_person_photo(entry.person_name)  # type: ignore[arg-type]
    if asset is None:
        logger.info("No Wikipedia portrait found for person='%s' scene=%s", entry.person_name, entry.scene_id)
        return False

    try:
        data = await _download_bytes(asset.url)
        ext = _ext_from_url(asset.url)
        key = f"runs/{run_id}/images/{entry.scene_id}{ext}"
        storage.upload_bytes(key, data, content_type="image/jpeg")
        entry.source = "wikimedia_person"
        entry.file_key = key
        entry.status = "acquired"
        entry.attribution = asset.attribution
        entry.qa_passed = True   # Wikipedia portraits skip QA — ground truth
        entry.qa_resolution_ok = True
        entry.qa_duration_ok = True
        logger.info(
            "Acquired person photo: scene=%s person='%s' key=%s",
            entry.scene_id,
            entry.person_name,
            key,
        )
        return True
    except Exception as exc:
        logger.warning(
            "Person photo download failed scene=%s person='%s': %s",
            entry.scene_id,
            entry.person_name,
            exc,
        )
        return False


async def acquire_scene(
    entry: ManifestEntry,
    run_id: str,
    pexels: PexelsClient,
    pixabay: Optional[PixabayClient],
    storage: R2Client,
    wikimedia: Optional[WikimediaClient] = None,
) -> bool:
    """Acquire the best asset for one manifest entry from the merged source pool.

    QA gate (P8-S4): candidates are checked for resolution, video duration fit,
    and optionally CLIP semantic similarity.  Primary-query candidates are tried
    before fallback-query candidates.  Within each group, candidates are sorted
    by priority (historic Wikimedia gets priority=1) then resolution.  The first
    candidate to pass all QA checks is downloaded, uploaded, and accepted.

    If no candidate passes QA, the best-scoring downloaded candidate is accepted
    to avoid leaving the scene empty.  If all pre-checks fail (no candidate meets
    even the resolution floor), the highest-resolution candidate is downloaded as
    a last resort.

    Person scenes (entry.person_name set): tries wikimedia.fetch_person_photo
    first; on miss falls back to generic Pexels+Pixabay only (no Wikimedia
    general, no AI — wrong generated face is worse than generic B-roll).

    Mutates entry fields in-place on success. Returns True on success, False only
    when every candidate is exhausted.
    """
    from src.clip_reranker import get_reranker  # noqa: PLC0415

    clip_reranker = get_reranker()  # None when CLIP_RERANK_ENABLED=False (default)

    # Person scene: Wikipedia portrait first, generic stock fallback (no AI).
    if entry.person_name and wikimedia:
        found = await _try_person_photo(entry, run_id, wikimedia, storage)
        if found:
            return True
        logger.info(
            "Person photo miss — falling back to generic stock for scene=%s person='%s'",
            entry.scene_id,
            entry.person_name,
        )
        # Generic Pexels+Pixabay only; no Wikimedia general, no AI for person scenes.
        is_video = entry.clip_type == "hard_cut"
        candidates = await _gather_candidates(entry, pexels, pixabay, None, is_video)
    else:
        is_video = entry.clip_type == "hard_cut"
        candidates = await _gather_candidates(entry, pexels, pixabay, wikimedia, is_video)

    if not candidates:
        logger.warning("No candidates found for scene=%s", entry.scene_id)
        entry.status = "failed"
        return False

    # Sort: primary candidates first, then by priority (historic boost), then resolution.
    candidates.sort(key=lambda c: (c.from_fallback, -c.priority, -_resolution_score(c)))

    folder = "video" if is_video else "images"

    # QA loop: download each candidate, check, accept on first pass.
    # Track (candidate, bytes, result) triples for pick_best fallback.
    checked: list[tuple[_Candidate, bytes, QAResult]] = []

    for candidate in candidates:
        # Pre-check metadata (resolution + duration) — skip download on obvious failure.
        pre_result = qa_score(candidate, entry)
        if not pre_result.resolution_ok or not pre_result.duration_ok:
            logger.debug(
                "QA pre-check failed scene=%s source=%s res_ok=%s dur_ok=%s",
                entry.scene_id,
                candidate.source,
                pre_result.resolution_ok,
                pre_result.duration_ok,
            )
            continue

        try:
            data = await _download_bytes(candidate.url)
        except Exception as exc:
            logger.warning(
                "Download failed scene=%s source=%s: %s",
                entry.scene_id,
                candidate.source,
                exc,
            )
            continue

        # Full QA including CLIP when enabled.
        result = qa_score(candidate, entry, image_data=data, clip_reranker=clip_reranker)

        if result.passed:
            key = f"runs/{run_id}/{folder}/{entry.scene_id}{candidate.ext}"
            storage.upload_bytes(key, data, content_type=candidate.content_type)
            _apply_entry_fields(entry, candidate, key, result)
            logger.info(
                "QA passed: scene=%s source=%s fallback=%s clip_score=%s",
                entry.scene_id,
                candidate.source,
                candidate.from_fallback,
                result.clip_score,
            )
            return True

        # QA failed (CLIP below threshold) — track for pick_best.
        checked.append((candidate, data, result))
        logger.debug(
            "QA failed scene=%s source=%s clip_score=%s",
            entry.scene_id,
            candidate.source,
            result.clip_score,
        )

    # No QA pass — accept best available from downloaded candidates.
    if checked:
        best = pick_best([(c, r) for c, _, r in checked])
        best_data, best_result = next(
            (d, r) for c, d, r in checked if c is best
        )
        key = f"runs/{run_id}/{folder}/{entry.scene_id}{best.ext}"
        storage.upload_bytes(key, best_data, content_type=best.content_type)
        _apply_entry_fields(entry, best, key, best_result)
        entry.qa_passed = False  # override — accepted best available, QA did not pass
        logger.warning(
            "QA miss — accepted best available: scene=%s source=%s clip_score=%s",
            entry.scene_id,
            best.source,
            best_result.clip_score,
        )
        return True

    # Last resort: all pre-checks failed (no candidate met the resolution floor).
    # Download the highest-resolution candidate and accept regardless.
    best_by_res = max(candidates, key=_resolution_score)
    try:
        data = await _download_bytes(best_by_res.url)
        key = f"runs/{run_id}/{folder}/{entry.scene_id}{best_by_res.ext}"
        storage.upload_bytes(key, data, content_type=best_by_res.content_type)
        entry.source = best_by_res.source
        entry.file_key = key
        entry.status = "acquired"
        entry.attribution = best_by_res.attribution
        entry.fallback_used = best_by_res.from_fallback
        entry.qa_passed = False
        entry.qa_resolution_ok = False
        entry.qa_duration_ok = True
        entry.qa_clip_score = None
        logger.warning(
            "All pre-checks failed — accepted best-resolution candidate: scene=%s source=%s",
            entry.scene_id,
            best_by_res.source,
        )
        return True
    except Exception as exc:
        logger.warning(
            "Last-resort download failed scene=%s: %s", entry.scene_id, exc
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
