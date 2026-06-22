"""AcquisitionWorker (P9-S3) — verified_storyboard → asset_manifest artifact.

Routes each scene by segment_type using P8 src/ modules directly (P8 portability contract).
Three-tier STK query cascade (primary_stk → context_stk → concept_stk) within each
source group before advancing. QA gate per candidate; pick_best last resort; scene
never left empty.

Pipeline position (after P9-S5 wiring):
    storyboard_worker → acquisition_worker → render_worker
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.storyboard_worker import VerifiedStoryboardArtifact
from src.exceptions import PexelsError
from src.footage_qa import QAResult, pick_best, qa_score
from src.models import AssetManifest, ManifestEntry, Storyboard
from src.pexels import PexelsClient, _pick_best_video_file
from src.pixabay_client import PixabayClient
from src.wikimedia_client import WikimediaClient

logger = logging.getLogger(__name__)

ACQUISITION_WORKER_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="none",
    prompt="",
    model="none",
    sampling_params={},
)

# Wikimedia CDN returns 403 without a descriptive User-Agent.
_DOWNLOAD_HEADERS = {
    "User-Agent": "ContentFactory/1.0 (https://github.com/gobokobok/content-factory-saas)"
}

# Pexels photo minimum dimensions for pre-filter.
_MIN_PEXELS_PHOTO_WIDTH = 1920
_MIN_PEXELS_PHOTO_HEIGHT = 1080

# Maximum concurrent scene acquisitions per batch.
_BATCH_SIZE = 20


# ── Candidate model ───────────────────────────────────────────────────────────


@dataclass
class _Candidate:
    """Unified metadata record for one asset candidate (not yet downloaded)."""

    url: str
    width: int
    height: int
    source: str           # "pexels" | "pixabay" | "wikimedia"
    content_type: str
    ext: str
    attribution: Optional[str] = None
    duration_seconds: Optional[float] = None

    def resolution_score(self) -> int:
        """Return pixel area — higher is preferred."""
        return self.width * self.height


# ── Utility helpers ───────────────────────────────────────────────────────────


def _ext_from_url(url: str) -> str:
    """Extract lowercase file extension from URL path, defaulting to .jpg."""
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext.lower() if ext else ".jpg"


def _asset_key(run_id: str, scene_id: str, is_video: bool, ext: str) -> str:
    """Build the R2 storage key for an acquired scene asset."""
    folder = "video" if is_video else "images"
    return f"runs/{run_id}/{folder}/{scene_id}{ext}"


def _apply_fields(entry: ManifestEntry, candidate: "_Candidate", key: str, result: QAResult) -> None:
    """Write acquisition and QA fields onto a manifest entry in-place."""
    entry.source = candidate.source
    entry.file_key = key
    entry.status = "acquired"
    entry.attribution = candidate.attribution
    entry.qa_passed = result.passed
    entry.qa_resolution_ok = result.resolution_ok
    entry.qa_duration_ok = result.duration_ok
    entry.qa_clip_score = result.clip_score


# ── Source search helpers ─────────────────────────────────────────────────────


def _pexels_video_candidates(pexels: PexelsClient, query: str) -> list[_Candidate]:
    """Search Pexels Videos and return metadata candidates. Sync — call via asyncio.to_thread."""
    try:
        videos = pexels.search_videos(query)
    except PexelsError as exc:
        logger.warning("Pexels video search failed query=%r: %s", query, exc)
        return []
    results: list[_Candidate] = []
    for video in videos:
        vfile = _pick_best_video_file(video)
        if vfile and vfile.get("link"):
            raw_dur = video.get("duration")
            results.append(_Candidate(
                url=vfile["link"],
                width=vfile.get("width", 0),
                height=vfile.get("height", 0),
                source="pexels",
                content_type=vfile.get("file_type", "video/mp4"),
                ext=".mp4",
                duration_seconds=float(raw_dur) if raw_dur else None,
            ))
    return results


def _pexels_photo_candidates(pexels: PexelsClient, query: str) -> list[_Candidate]:
    """Search Pexels Photos and return metadata candidates meeting minimum dimensions. Sync."""
    try:
        photos = pexels.search_photos(query)
    except PexelsError as exc:
        logger.warning("Pexels photo search failed query=%r: %s", query, exc)
        return []
    results: list[_Candidate] = []
    for photo in photos:
        w = photo.get("width", 0)
        h = photo.get("height", 0)
        url = photo.get("src", {}).get("original", "")
        if url and w >= _MIN_PEXELS_PHOTO_WIDTH and h >= _MIN_PEXELS_PHOTO_HEIGHT:
            results.append(_Candidate(
                url=url,
                width=w,
                height=h,
                source="pexels",
                content_type="image/jpeg",
                ext=_ext_from_url(url),
            ))
    return results


async def _pixabay_video_candidates(pixabay: PixabayClient, query: str) -> list[_Candidate]:
    """Search Pixabay Videos and return metadata candidates."""
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
        )
        for v in videos
    ]


async def _pixabay_photo_candidates(pixabay: PixabayClient, query: str) -> list[_Candidate]:
    """Search Pixabay Images and return metadata candidates."""
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
    ]


async def _wikimedia_photo_candidates(wikimedia: WikimediaClient, query: str) -> list[_Candidate]:
    """Search Wikimedia Commons for photos and return metadata candidates with attribution."""
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


# ── Download helper ───────────────────────────────────────────────────────────


async def _download_bytes(url: str) -> bytes:
    """Download raw bytes from a CDN URL. Raises httpx.HTTPError on failure."""
    async with httpx.AsyncClient(timeout=60, headers=_DOWNLOAD_HEADERS) as client:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return resp.content


# ── Core QA + cascade helpers ─────────────────────────────────────────────────


async def _try_candidates(
    candidates: list[_Candidate],
    entry: ManifestEntry,
    is_video: bool,
    run_id: str,
    storage: ArtifactStorage,
    collected: list[tuple["_Candidate", bytes, QAResult]],
) -> bool:
    """Try each candidate in descending resolution order; accept on first QA pass.

    Pre-checks resolution and duration from metadata (no download) before
    downloading. Appends all downloaded (candidate, bytes, result) tuples to
    collected for later pick_best fallback. Returns True on first QA pass.
    """
    for candidate in sorted(candidates, key=lambda c: -c.resolution_score()):
        pre = qa_score(candidate, entry)
        if not pre.resolution_ok or not pre.duration_ok:
            logger.debug(
                "Pre-check failed scene=%s source=%s res_ok=%s dur_ok=%s",
                entry.scene_id, candidate.source, pre.resolution_ok, pre.duration_ok,
            )
            continue
        try:
            data = await _download_bytes(candidate.url)
        except Exception as exc:
            logger.warning(
                "Download failed scene=%s source=%s: %s", entry.scene_id, candidate.source, exc
            )
            continue
        result = qa_score(candidate, entry, image_data=data)
        if result.passed:
            key = _asset_key(run_id, entry.scene_id, is_video, candidate.ext)
            await storage.put_bytes(key, data, content_type=candidate.content_type)
            _apply_fields(entry, candidate, key, result)
            logger.info(
                "QA passed: scene=%s source=%s clip_score=%s",
                entry.scene_id, candidate.source, result.clip_score,
            )
            return True
        collected.append((candidate, data, result))
        logger.debug(
            "QA failed scene=%s source=%s clip_score=%s", entry.scene_id, candidate.source, result.clip_score,
        )
    return False


async def _accept_best(
    collected: list[tuple[_Candidate, bytes, QAResult]],
    all_seen: list[_Candidate],
    entry: ManifestEntry,
    is_video: bool,
    run_id: str,
    storage: ArtifactStorage,
) -> bool:
    """Accept best available from downloaded candidates; last-resort downloads best-resolution.

    Returns True if any candidate was accepted (entry mutated in-place).
    """
    if collected:
        best = pick_best([(c, r) for c, _, r in collected])
        best_data, best_result = next((d, r) for c, d, r in collected if c is best)
        key = _asset_key(run_id, entry.scene_id, is_video, best.ext)
        await storage.put_bytes(key, best_data, content_type=best.content_type)
        _apply_fields(entry, best, key, best_result)
        entry.qa_passed = False  # override — accepted best available, QA did not pass
        logger.warning(
            "QA miss — accepted best available: scene=%s source=%s clip_score=%s",
            entry.scene_id, best.source, best_result.clip_score,
        )
        return True

    # Last resort: no candidate passed pre-check — download highest-resolution anyway.
    if all_seen:
        best_by_res = max(all_seen, key=lambda c: c.resolution_score())
        try:
            data = await _download_bytes(best_by_res.url)
            key = _asset_key(run_id, entry.scene_id, is_video, best_by_res.ext)
            await storage.put_bytes(key, data, content_type=best_by_res.content_type)
            entry.source = best_by_res.source
            entry.file_key = key
            entry.status = "acquired"
            entry.attribution = best_by_res.attribution
            entry.qa_passed = False
            entry.qa_resolution_ok = False
            entry.qa_duration_ok = True
            entry.qa_clip_score = None
            logger.warning(
                "All pre-checks failed — last resort: scene=%s source=%s", entry.scene_id, best_by_res.source,
            )
            return True
        except Exception as exc:
            logger.warning("Last-resort download failed scene=%s: %s", entry.scene_id, exc)

    return False


# ── Per-segment-type acquisition routing ──────────────────────────────────────


async def _acquire_character(
    entry: ManifestEntry,
    queries: list[str],
    run_id: str,
    storage: ArtifactStorage,
    pexels: PexelsClient,
    pixabay: Optional[PixabayClient],
    wikimedia: WikimediaClient,
) -> bool:
    """Character scene: Wikipedia portrait first; generic Pexels+Pixabay fallback.

    Wikipedia portraits skip the QA gate — they are the ground truth image for the
    named person. No Wikimedia general search, no AI fallback for person scenes
    (a generated wrong face is worse than generic B-roll).
    """
    # 1. Try Wikipedia portrait (QA skipped — ground truth)
    asset = await wikimedia.fetch_person_photo(entry.person_name)  # type: ignore[arg-type]
    if asset is not None:
        try:
            data = await _download_bytes(asset.url)
            ext = _ext_from_url(asset.url)
            key = _asset_key(run_id, entry.scene_id, is_video=False, ext=ext)
            await storage.put_bytes(key, data, content_type="image/jpeg")
            entry.source = "wikimedia_person"
            entry.file_key = key
            entry.status = "acquired"
            entry.attribution = asset.attribution
            entry.qa_passed = True
            entry.qa_resolution_ok = True
            entry.qa_duration_ok = True
            logger.info(
                "Character portrait acquired: scene=%s person=%r", entry.scene_id, entry.person_name
            )
            return True
        except Exception as exc:
            logger.warning(
                "Character portrait download failed scene=%s person=%r: %s",
                entry.scene_id, entry.person_name, exc,
            )

    logger.info(
        "Character portrait miss — falling back to generic stock: scene=%s person=%r",
        entry.scene_id, entry.person_name,
    )

    # 2. Generic Pexels+Pixabay fallback (no Wikimedia general, no AI)
    collected: list[tuple[_Candidate, bytes, QAResult]] = []
    all_seen: list[_Candidate] = []

    for query in queries:
        if not query:
            continue
        tasks: list = [asyncio.to_thread(_pexels_photo_candidates, pexels, query)]
        if pixabay:
            tasks.append(_pixabay_photo_candidates(pixabay, query))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        tier_cands: list[_Candidate] = []
        for result in results:
            if not isinstance(result, Exception):
                tier_cands.extend(result)
        all_seen.extend(tier_cands)
        if await _try_candidates(tier_cands, entry, False, run_id, storage, collected):
            return True

    return await _accept_best(collected, all_seen, entry, False, run_id, storage)


async def _acquire_event(
    entry: ManifestEntry,
    queries: list[str],
    run_id: str,
    storage: ArtifactStorage,
    pexels: PexelsClient,
    pixabay: Optional[PixabayClient],
    wikimedia: WikimediaClient,
) -> bool:
    """Event scene: Wikimedia Commons (three tiers) → Pexels+Pixabay fallback (three tiers)."""
    collected: list[tuple[_Candidate, bytes, QAResult]] = []
    all_seen: list[_Candidate] = []

    # Source 1: Wikimedia Commons general search — three-tier cascade
    for query in queries:
        if not query:
            continue
        wiki_cands = await _wikimedia_photo_candidates(wikimedia, query)
        all_seen.extend(wiki_cands)
        if await _try_candidates(wiki_cands, entry, False, run_id, storage, collected):
            return True

    # Source 2: Pexels+Pixabay concurrent — three-tier cascade
    for query in queries:
        if not query:
            continue
        tasks: list = [asyncio.to_thread(_pexels_photo_candidates, pexels, query)]
        if pixabay:
            tasks.append(_pixabay_photo_candidates(pixabay, query))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        tier_cands: list[_Candidate] = []
        for result in results:
            if not isinstance(result, Exception):
                tier_cands.extend(result)
        all_seen.extend(tier_cands)
        if await _try_candidates(tier_cands, entry, False, run_id, storage, collected):
            return True

    return await _accept_best(collected, all_seen, entry, False, run_id, storage)


async def _acquire_broll(
    entry: ManifestEntry,
    queries: list[str],
    is_video: bool,
    run_id: str,
    storage: ArtifactStorage,
    pexels: PexelsClient,
    pixabay: Optional[PixabayClient],
) -> bool:
    """B-roll scene: Pexels+Pixabay concurrent merge+rank, three-tier cascade."""
    collected: list[tuple[_Candidate, bytes, QAResult]] = []
    all_seen: list[_Candidate] = []

    for query in queries:
        if not query:
            continue
        if is_video:
            tasks: list = [asyncio.to_thread(_pexels_video_candidates, pexels, query)]
            if pixabay:
                tasks.append(_pixabay_video_candidates(pixabay, query))
        else:
            tasks = [asyncio.to_thread(_pexels_photo_candidates, pexels, query)]
            if pixabay:
                tasks.append(_pixabay_photo_candidates(pixabay, query))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        tier_cands: list[_Candidate] = []
        for result in results:
            if not isinstance(result, Exception):
                tier_cands.extend(result)
        all_seen.extend(tier_cands)
        if await _try_candidates(tier_cands, entry, is_video, run_id, storage, collected):
            return True

    return await _accept_best(collected, all_seen, entry, is_video, run_id, storage)


async def _acquire_scene(
    entry: ManifestEntry,
    run_id: str,
    storage: ArtifactStorage,
    pexels: PexelsClient,
    pixabay: Optional[PixabayClient],
    wikimedia: WikimediaClient,
) -> None:
    """Route scene acquisition by segment_type; mutates entry in-place on success."""
    queries = [entry.primary_stk, entry.context_stk, entry.concept_stk]
    is_video = entry.clip_type == "hard_cut"

    if entry.segment_type == "Character" and entry.person_name:
        ok = await _acquire_character(entry, queries, run_id, storage, pexels, pixabay, wikimedia)
    elif entry.segment_type == "Event":
        ok = await _acquire_event(entry, queries, run_id, storage, pexels, pixabay, wikimedia)
    else:
        ok = await _acquire_broll(entry, queries, is_video, run_id, storage, pexels, pixabay)

    if not ok:
        logger.warning(
            "All candidates exhausted for scene=%s segment_type=%s",
            entry.scene_id, entry.segment_type,
        )
        entry.status = "failed"


# ── Footage summary ───────────────────────────────────────────────────────────


def _compute_footage_summary(entries: list[ManifestEntry]) -> dict:
    """Compute per-source acquisition counts from the manifest entries."""
    counts: dict[str, int] = {
        "pexels": 0,
        "pixabay": 0,
        "wikimedia": 0,
        "wikimedia_person": 0,
        "failed": 0,
        "qa_failed_scenes": 0,
    }
    for entry in entries:
        if entry.status != "acquired":
            counts["failed"] += 1
        else:
            source = entry.source or "unknown"
            counts[source] = counts.get(source, 0) + 1
            if entry.qa_passed is False:
                counts["qa_failed_scenes"] += 1
    return counts


# ── Artifact schema ───────────────────────────────────────────────────────────


class AssetManifestArtifact(BaseModel):
    """Terminal artifact of the AcquisitionWorker.

    manifest is the full AssetManifest serialised to a dict.
    footage_summary holds per-source counts for Telegram reporting.
    """

    scene_count: int
    acquired: int
    failed: int
    footage_summary: dict[str, Any]
    manifest: dict[str, Any]  # AssetManifest.model_dump(mode="json")
    generated_at: datetime


# ── Worker factory ────────────────────────────────────────────────────────────


def build_acquisition_worker(
    storage: ArtifactStorage,
    pexels_api_key: str,
    pixabay_api_key: str = "",
) -> WorkerNode:
    """Build the native AcquisitionWorker node.

    Reads state.artifacts['verified_storyboard']; routes each scene by segment_type;
    runs three-tier STK cascade with QA gate; writes asset_manifest artifact and a
    footage_summary.json side-car to R2. Emits a single AssetManifestArtifact.
    """

    async def _worker(state: StageState) -> WorkerOutput:
        """Acquire assets for all storyboard scenes and return AssetManifestArtifact."""
        run_id = state.run_id

        # Read verified storyboard
        sb_key = state.artifacts["verified_storyboard"]
        _, sb_body = await read_artifact(storage, sb_key)
        sb_artifact = VerifiedStoryboardArtifact.model_validate(sb_body)
        storyboard = Storyboard.model_validate(sb_artifact.storyboard)

        # Build manifest entries from v2 storyboard scene fields
        entries: list[ManifestEntry] = []
        for scene in storyboard.scenes:
            entries.append(ManifestEntry(
                scene_id=scene.scene,
                clip_type=scene.clip_type,
                segment_type=scene.segment_type,
                primary_stk=scene.primary_stk,
                context_stk=scene.context_stk,
                concept_stk=scene.concept_stk,
                person_name=scene.person_name,
                person_title=scene.person_title,
                duration_s=scene.duration_s,
                historic=scene.historic,
            ))

        # Build source clients
        pexels = PexelsClient(api_key=pexels_api_key)
        pixabay: Optional[PixabayClient] = PixabayClient(api_key=pixabay_api_key) if pixabay_api_key else None
        wikimedia = WikimediaClient()

        # Acquire all scenes in parallel batches; capture unexpected exceptions per scene
        for batch_start in range(0, len(entries), _BATCH_SIZE):
            batch = entries[batch_start : batch_start + _BATCH_SIZE]
            results = await asyncio.gather(
                *[_acquire_scene(entry, run_id, storage, pexels, pixabay, wikimedia) for entry in batch],
                return_exceptions=True,
            )
            for entry, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.error("Unexpected error scene=%s: %s", entry.scene_id, result)
                    entry.status = "failed"

        manifest = AssetManifest(run_id=run_id, entries=entries)
        footage_summary = _compute_footage_summary(entries)

        # Write footage_summary.json side-car for legacy compatibility (P8-S5 path)
        try:
            await storage.put_json(f"runs/{run_id}/footage_summary.json", footage_summary)
        except Exception as exc:
            logger.warning("Failed to write footage_summary side-car: %s", exc)

        acquired = sum(1 for e in entries if e.status == "acquired")
        failed = len(entries) - acquired

        artifact = AssetManifestArtifact(
            scene_count=len(entries),
            acquired=acquired,
            failed=failed,
            footage_summary=footage_summary,
            manifest=manifest.model_dump(mode="json"),
            generated_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact)

    return _worker
