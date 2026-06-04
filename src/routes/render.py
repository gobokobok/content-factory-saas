"""POST /runs/{run_id}/render and GET /runs/{run_id}/render/status endpoints."""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from src import pipeline
from src.config import Settings, get_settings
from src.exceptions import StorageError
from src.models import AssetManifest, RenderAcceptedResponse, RenderStatusResponse
from src.renderer import _RENDER_STATE, render_run
from src.storage import R2Client

logger = logging.getLogger(__name__)

router = APIRouter()


async def _background_render(
    run_id: str,
    manifest: AssetManifest,
    storage: R2Client,
    timeout_seconds: int,
    total_frames: int,
    settings: Settings,
) -> None:
    """Execute render in a thread pool. Updates run_log.json on completion or failure."""
    try:
        result = await asyncio.to_thread(
            render_run, run_id, manifest, storage, timeout_seconds, total_frames
        )
    except StorageError as exc:
        logger.error("Storage error during background render for run %s: %s", run_id, exc)
        _RENDER_STATE[run_id] = {
            "status": "failed",
            "progress_pct": 0,
            "output_key": None,
            "error": str(exc),
        }
        try:
            storage.update_run_log(run_id, "render", "failed", error=str(exc))
        except StorageError:
            logger.error("Failed to update run log for run %s after storage error", run_id)
        return

    is_complete = result["status"] == "complete"
    error = None if is_complete else f"FFmpeg exit code {result['exit_code']}"
    # Ensure state reflects final result even when render_run is mocked in tests.
    _RENDER_STATE[run_id] = {
        "status": result["status"],
        "progress_pct": 100 if is_complete else 0,
        "output_key": result["output_key"] or None,
        "error": error,
    }
    storage.update_run_log(
        run_id,
        "render",
        result["status"],
        output_url=result["output_key"] or None,
        error=error,
    )
    pipeline.summarize_step(run_id, storage, settings)


@router.post("/runs/{run_id}/render", response_model=RenderAcceptedResponse, status_code=202)
async def render(
    run_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
) -> RenderAcceptedResponse:
    """Accept a render request. Returns 202 immediately; render executes as a background task."""
    storage = R2Client(
        account_id=settings.R2_ACCOUNT_ID,
        access_key_id=settings.R2_ACCESS_KEY_ID,
        secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        bucket_name=settings.R2_BUCKET_NAME,
    )

    try:
        manifest_data = storage.get_json(f"runs/{run_id}/asset_manifest.json")
    except StorageError:
        raise HTTPException(
            status_code=404, detail=f"Asset manifest not found for run '{run_id}'"
        )

    manifest = AssetManifest(**manifest_data)

    total_frames = 0
    try:
        sb_data = storage.get_json(f"runs/{run_id}/storyboard.json")
        total_duration_s = sb_data.get("summary", {}).get("total_duration_s", 0)
        total_frames = int(total_duration_s * 25)
    except StorageError:
        pass

    # Initialise state before task starts so the status endpoint never returns 404
    # in the brief window between 202 response and background task execution.
    _RENDER_STATE[run_id] = {
        "status": "running",
        "progress_pct": 0,
        "output_key": None,
        "error": None,
    }

    background_tasks.add_task(
        _background_render,
        run_id=run_id,
        manifest=manifest,
        storage=storage,
        timeout_seconds=settings.FFMPEG_TIMEOUT_SECONDS,
        total_frames=total_frames,
        settings=settings,
    )

    return RenderAcceptedResponse(
        status="running",
        poll_url=f"/runs/{run_id}/render/status",
    )


@router.get("/runs/{run_id}/render/status", response_model=RenderStatusResponse)
def render_status(run_id: str) -> RenderStatusResponse:
    """Poll render task status. Returns 404 if no render has been started for this run."""
    if run_id not in _RENDER_STATE:
        raise HTTPException(
            status_code=404, detail=f"No active render found for run '{run_id}'"
        )
    return RenderStatusResponse(**_RENDER_STATE[run_id])
