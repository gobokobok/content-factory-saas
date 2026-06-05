"""Asset acquisition orchestrator — Pexels → Replicate fallback chain for every pending scene.

Step status rule
---------------
Step asset_acquisition is marked 'complete' when at least MIN_ACQUIRED_FOR_COMPLETE
entries in the manifest have status 'acquired' after the loop completes (counting
pre-existing acquired entries from earlier calls). It is marked 'failed' only when
the total acquired count is zero — i.e. no scene in the run has an asset at all.
"""

import asyncio
import logging

from src.exceptions import PexelsError, ReplicateError
from src.models import AssetManifest, ManifestEntry
from src.pexels import PexelsClient
from src.replicate_client import ReplicateClient
from src.storage import R2Client

logger = logging.getLogger(__name__)

# Step → 'complete' if at least this many entries are acquired; 'failed' only if 0.
MIN_ACQUIRED_FOR_COMPLETE = 1


def acquire_scene(
    entry: ManifestEntry,
    run_id: str,
    pexels: PexelsClient,
    replicate: ReplicateClient,
    storage: R2Client,
    visual_style: str = "Realistic",
) -> bool:
    """Try to acquire an asset for one manifest entry, mutating it in-place on success.

    Routing is controlled by entry.asset_mode:
      "stock"        → Pexels only; skip Replicate on miss
      "ai_generated" → Replicate only; skip Pexels entirely
      None           → Pexels → Replicate fallback chain (legacy behaviour)

    A PexelsError is treated the same as no result — falls through to Replicate
    when asset_mode is None.
    Sets entry.source, entry.file_key, entry.status = 'acquired' on success.
    Sets entry.status = 'failed' when the chosen source is exhausted.
    visual_style is forwarded to Replicate for AI generation prompts.
    Returns True on success, False on failure.
    """
    mode = entry.asset_mode

    if mode == "ai_generated":
        try:
            replicate_result = replicate.acquire_for_entry(entry, run_id, storage, visual_style=visual_style)
            entry.source = replicate_result.source
            entry.file_key = replicate_result.file_key
            entry.status = replicate_result.status
            return True
        except ReplicateError as exc:
            logger.error("Replicate failed for scene=%s: %s", entry.scene_id, exc)
            entry.status = "failed"
            return False

    if mode == "stock":
        pexels_result = None
        try:
            pexels_result = pexels.acquire_for_entry(entry, run_id, storage)
        except PexelsError as exc:
            logger.warning("Pexels failed for scene=%s: %s", entry.scene_id, exc)
        if pexels_result is not None:
            entry.source = pexels_result.source
            entry.file_key = pexels_result.file_key
            entry.status = pexels_result.status
            return True
        logger.warning("Stock mode: no Pexels result for scene=%s, marking failed", entry.scene_id)
        entry.status = "failed"
        return False

    # mode is None — legacy Pexels → Replicate fallback chain
    pexels_result = None
    try:
        pexels_result = pexels.acquire_for_entry(entry, run_id, storage)
    except PexelsError as exc:
        logger.warning("Pexels failed for scene=%s: %s", entry.scene_id, exc)

    if pexels_result is not None:
        entry.source = pexels_result.source
        entry.file_key = pexels_result.file_key
        entry.status = pexels_result.status
        return True

    try:
        replicate_result = replicate.acquire_for_entry(entry, run_id, storage, visual_style=visual_style)
        entry.source = replicate_result.source
        entry.file_key = replicate_result.file_key
        entry.status = replicate_result.status
        return True
    except ReplicateError as exc:
        logger.error("Replicate failed for scene=%s: %s", entry.scene_id, exc)
        entry.status = "failed"
        return False


async def run_acquisition(
    run_id: str,
    manifest: AssetManifest,
    pexels: PexelsClient,
    replicate: ReplicateClient,
    storage: R2Client,
    visual_style: str = "Realistic",
    batch_size: int = 20,
) -> dict:
    """Run the full acquisition loop over all pending manifest entries in parallel batches.

    Skips entries already marked 'acquired' (idempotent / resumable). Pending
    entries are processed in batches of batch_size using asyncio.gather.
    Each acquire_scene call runs in a thread (asyncio.to_thread) because
    PexelsClient and ReplicateClient are synchronous HTTP clients.
    A failure in one scene within a batch is caught and logged; the batch
    continues and the manifest entry is marked 'failed'.
    visual_style is forwarded to Replicate for AI generation prompts.

    Returns a summary dict:
        acquired  — total entries with status 'acquired' after the loop (includes
                    pre-existing; stable across repeated calls once all scenes done)
        failed    — entries that were attempted this call and could not be acquired
        sources   — acquisition source counts across all acquired entries
    """
    pending = [e for e in manifest.entries if e.status != "acquired"]

    newly_failed = 0
    for batch_start in range(0, len(pending), batch_size):
        batch = pending[batch_start : batch_start + batch_size]
        results = await asyncio.gather(
            *[
                asyncio.to_thread(acquire_scene, entry, run_id, pexels, replicate, storage, visual_style)
                for entry in batch
            ],
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
