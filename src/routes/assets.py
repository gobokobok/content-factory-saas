"""Asset acquisition route — POST /runs/{run_id}/assets (202 + background task)."""

import logging

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
from src.replicate_client import ReplicateClient
from src.storage import R2Client

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
    replicate: ReplicateClient,
    storage: R2Client,
    visual_style: str,
    batch_size: int,
    settings: Settings,
) -> None:
    """Run acquisition in a thread pool and update run_log on completion or failure."""
    try:
        summary = await run_acquisition(
            run_id, manifest, pexels, replicate, storage,
            visual_style=visual_style,
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
    replicate = ReplicateClient(
        api_token=settings.REPLICATE_API_TOKEN,
        model=settings.REPLICATE_FLUX_MODEL,
        poll_interval_seconds=settings.REPLICATE_POLL_INTERVAL_SECONDS,
        max_poll_attempts=settings.REPLICATE_MAX_POLL_ATTEMPTS,
    )

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

    background_tasks.add_task(
        _background_acquire,
        run_id=run_id,
        manifest=manifest,
        manifest_key=manifest_key,
        pexels=pexels,
        replicate=replicate,
        storage=storage,
        visual_style=video_settings.visual_style,
        batch_size=settings.ACQUISITION_BATCH_SIZE,
        settings=settings,
    )

    return AcquisitionAcceptedResponse(
        status="running",
        poll_url=f"/runs/{run_id}/assets/status",
    )


@router.get("/runs/{run_id}/assets/status", response_model=AcquisitionStatusResponse)
def acquisition_status(run_id: str) -> AcquisitionStatusResponse:
    """Poll acquisition task status. Returns 404 if no acquisition has been started for this run."""
    if run_id not in _ACQUISITION_STATE:
        raise HTTPException(
            status_code=404, detail=f"No active acquisition found for run '{run_id}'"
        )
    return AcquisitionStatusResponse(**_ACQUISITION_STATE[run_id])
