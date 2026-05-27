"""POST /runs/{run_id}/render endpoint."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from src import pipeline
from src.config import Settings, get_settings
from src.exceptions import StorageError
from src.models import AssetManifest, RenderResponse
from src.renderer import render_run
from src.storage import R2Client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/runs/{run_id}/render", response_model=RenderResponse)
def render(run_id: str, settings: Settings = Depends(get_settings)) -> RenderResponse:
    """Download assets, execute ffmpeg_script.sh, upload output video, and clean up."""
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

    try:
        result = render_run(run_id, manifest, storage, settings.FFMPEG_TIMEOUT_SECONDS)
    except StorageError as exc:
        logger.error("Storage error during render for run %s: %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))

    error = None if result["status"] == "complete" else f"FFmpeg exit code {result['exit_code']}"
    storage.update_run_log(
        run_id,
        "render",
        result["status"],
        output_url=result["output_key"] or None,
        error=error,
    )
    pipeline.summarize_step(run_id, storage, settings)

    return RenderResponse(**result)
