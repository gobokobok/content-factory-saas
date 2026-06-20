"""Asset acquisition route — POST /runs/{run_id}/assets (202 + background task)."""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from src import pipeline
from src.acquisition import MIN_ACQUIRED_FOR_COMPLETE, run_acquisition
from src.config import Settings, get_settings
from src.exceptions import StorageError
from src.models import (
    AcquisitionAcceptedResponse,
    AcquisitionStatusResponse,
    AssetManifest,
    VideoSettings,
)
from src.pexels import PexelsClient
from src.pixabay_client import PixabayClient
from src.storage import R2Client
from src.wikimedia_client import WikimediaClient

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory acquisition state keyed by run_id.  Same pattern as _RENDER_STATE in
# render.py — Railway keeps a single process per service instance, so this survives
# across requests within the same deployment.
_ACQUISITION_STATE: dict[str, dict] = {}


async def _background_acquire(
    run_id: str,
    manifest: AssetManifest,
    manifest_key: str,
    pexels: PexelsClient,
    pixabay: Optional[PixabayClient],
    wikimedia: WikimediaClient,
    storage: R2Client,
    batch_size: int,
    settings: Settings,
) -> None:
    """Run acquisition and update run_log on completion or failure."""
    try:
        summary = await run_acquisition(
            run_id, manifest, pexels, pixabay, storage,
            wikimedia=wikimedia,
            batch_size=batch_size,
        )
    except BaseException as exc:
        err_msg = str(exc) or type(exc).__name__
        logger.error("Background acquisition failed: run=%s error=%s", run_id, err_msg)
        _ACQUISITION_STATE[run_id] = {
            "status": "failed",
            "acquired": 0,
            "failed": 0,
            "sources": {},
            "manifest_key": None,
            "error": err_msg,
        }
        try:
            storage.update_run_log(run_id, "asset_acquisition", "failed", error=err_msg)
            pipeline.summarize_step(run_id, storage, settings)
        except Exception:
            pass
        return

    try:
        storage.upload_json(manifest_key, manifest.model_dump(mode="json"))
    except StorageError as exc:
        err_msg = str(exc)
        logger.error("Failed to write updated manifest: run=%s error=%s", run_id, err_msg)
        _ACQUISITION_STATE[run_id] = {
            "status": "failed",
            "acquired": summary["acquired"],
            "failed": summary["failed"],
            "sources": summary["sources"],
            "manifest_key": None,
            "error": err_msg,
        }
        storage.update_run_log(run_id, "asset_acquisition", "failed", error=err_msg)
        pipeline.summarize_step(run_id, storage, settings)
        return

    step_status = "complete" if summary["acquired"] >= MIN_ACQUIRED_FOR_COMPLETE else "failed"
    _ACQUISITION_STATE[run_id] = {
        "status": step_status,
        "acquired": summary["acquired"],
        "failed": summary["failed"],
        "sources": summary["sources"],
        "manifest_key": manifest_key,
        "error": None if step_status == "complete" else "Too few assets acquired",
    }
    storage.update_run_log(
        run_id, "asset_acquisition", step_status, output_url=manifest_key
    )
    pipeline.summarize_step(run_id, storage, settings)


@router.post("/runs/{run_id}/assets", response_model=AcquisitionAcceptedResponse, status_code=202)
async def acquire_assets(
    run_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
) -> AcquisitionAcceptedResponse:
    """Accept an acquisition request. Returns 202 immediately; acquisition runs as a background task.

    Railway's 60-second HTTP timeout previously killed long-running acquisition mid-flight
    (BUG-005).  Moving to BackgroundTasks means the HTTP response is sent before acquisition
    starts, and the UI polls /runs/{run_id}/assets/status until status != 'running'.
    """
    storage = R2Client(
        account_id=settings.R2_ACCOUNT_ID,
        access_key_id=settings.R2_ACCESS_KEY_ID,
        secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        bucket_name=settings.R2_BUCKET_NAME,
    )

    manifest_key = f"runs/{run_id}/asset_manifest.json"
    try:
        manifest_data = storage.get_json(manifest_key)
    except StorageError:
        raise HTTPException(
            status_code=404,
            detail=f"asset_manifest.json not found for run '{run_id}'",
        )

    manifest = AssetManifest(**manifest_data)

    settings_key = f"runs/{run_id}/settings.json"
    try:
        settings_data = storage.get_json(settings_key)
        video_settings = VideoSettings.model_validate(settings_data)
    except StorageError:
        video_settings = VideoSettings()
        logger.debug("No settings.json for run=%s — using defaults for asset acquisition", run_id)

    pexels = PexelsClient(
        api_key=settings.PEXELS_API_KEY,
        per_page=settings.PEXELS_PER_PAGE,
    )
    pixabay = PixabayClient(api_key=settings.PIXABAY_API_KEY) if settings.PIXABAY_API_KEY else None
    wikimedia = WikimediaClient()

    # Initialise state before the task starts so the status endpoint never 404s
    # in the brief window between the 202 response and background task execution.
    _ACQUISITION_STATE[run_id] = {
        "status": "running",
        "acquired": 0,
        "failed": 0,
        "sources": {},
        "manifest_key": None,
        "error": None,
    }
    # Also persist "running" to run_log so the fallback (container restart) sees
    # a meaningful status rather than "pending" (which means acquisition never ran).
    try:
        storage.update_run_log(run_id, "asset_acquisition", "running")
    except Exception:
        pass  # Non-fatal — in-memory state is the primary source

    background_tasks.add_task(
        _background_acquire,
        run_id=run_id,
        manifest=manifest,
        manifest_key=manifest_key,
        pexels=pexels,
        pixabay=pixabay,
        wikimedia=wikimedia,
        storage=storage,
        batch_size=settings.ACQUISITION_BATCH_SIZE,
        settings=settings,
    )

    return AcquisitionAcceptedResponse(
        status="running",
        poll_url=f"/runs/{run_id}/assets/status",
    )


@router.get("/runs/{run_id}/assets/status", response_model=AcquisitionStatusResponse)
def acquisition_status(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> AcquisitionStatusResponse:
    """Poll acquisition task status.

    Primary: checks _ACQUISITION_STATE (in-memory, set by the background task).
    Fallback: if the state is missing (e.g. Railway restarted the container
    mid-acquisition), reads run_log.json from R2 to recover the last persisted
    status.  Returns 404 only if neither source has data for this run.
    """
    if run_id in _ACQUISITION_STATE:
        return AcquisitionStatusResponse(**_ACQUISITION_STATE[run_id])

    # In-memory state was lost — check the run_log for the persisted status.
    storage = R2Client(
        account_id=settings.R2_ACCOUNT_ID,
        access_key_id=settings.R2_ACCESS_KEY_ID,
        secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        bucket_name=settings.R2_BUCKET_NAME,
    )
    try:
        run_log = storage.get_json(f"runs/{run_id}/run_log.json")
        step = run_log.get("steps", {}).get("asset_acquisition", {})
        persisted_status = step.get("status")
        if not persisted_status:
            raise HTTPException(
                status_code=404, detail=f"No acquisition state found for run '{run_id}'"
            )
        # "pending" means the task never started (container restarted before the
        # background task wrote "running" to run_log).  "running" means it started
        # but was killed before completion.  Both are interrupted — surface as failed
        # so the UI shows a clear retry prompt instead of looping forever.
        error_msg = step.get("error")
        if persisted_status in ("pending", "running"):
            return AcquisitionStatusResponse(
                status="failed",
                error="Acquisition was interrupted (container restart). Retry.",
            )
        if not error_msg and persisted_status == "failed":
            # Failed but no error recorded — container restart after task completion.
            error_msg = "Acquisition was interrupted (container restart). Retry."
        return AcquisitionStatusResponse(
            status=persisted_status,
            error=error_msg,
        )
    except StorageError:
        raise HTTPException(
            status_code=404, detail=f"No acquisition state found for run '{run_id}'"
        )
