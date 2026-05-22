"""Route handler for POST /runs/{run_id}/ffmpeg-script."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from src.config import Settings, get_settings
from src.exceptions import FFmpegBuildError, StorageError
from src.ffmpeg_builder import build_ffmpeg_script
from src.models import AssetManifest, FFmpegScriptResponse, Storyboard
from src.storage import R2Client

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/runs/{run_id}/ffmpeg-script", response_model=FFmpegScriptResponse)
def generate_ffmpeg_script(
    run_id: str, settings: Settings = Depends(get_settings)
) -> FFmpegScriptResponse:
    """Generate ffmpeg_script.sh from storyboard and asset manifest and upload to R2."""
    storage = R2Client(
        account_id=settings.R2_ACCOUNT_ID,
        access_key_id=settings.R2_ACCESS_KEY_ID,
        secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        bucket_name=settings.R2_BUCKET_NAME,
    )

    storyboard_key = f"runs/{run_id}/storyboard.json"
    try:
        storyboard_data = storage.get_json(storyboard_key)
    except StorageError as exc:
        logger.error("Storyboard not found for run=%s: %s", run_id, exc)
        raise HTTPException(
            status_code=404, detail=f"Storyboard not found for run '{run_id}'"
        ) from exc

    manifest_key = f"runs/{run_id}/asset_manifest.json"
    try:
        manifest_data = storage.get_json(manifest_key)
    except StorageError as exc:
        logger.error("Asset manifest not found for run=%s: %s", run_id, exc)
        raise HTTPException(
            status_code=404, detail=f"Asset manifest not found for run '{run_id}'"
        ) from exc

    storyboard = Storyboard.model_validate(storyboard_data)
    manifest = AssetManifest.model_validate(manifest_data)

    try:
        script = build_ffmpeg_script(run_id, storyboard, manifest)
    except FFmpegBuildError as exc:
        logger.error("FFmpeg script build failed for run=%s: %s", run_id, exc)
        storage.update_run_log(run_id, "ffmpeg_script", "failed", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    script_key = f"runs/{run_id}/ffmpeg_script.sh"
    try:
        storage.upload_text(script_key, script, content_type="text/x-shellscript")
    except StorageError as exc:
        logger.error("Failed to upload ffmpeg_script.sh for run=%s: %s", run_id, exc)
        storage.update_run_log(run_id, "ffmpeg_script", "failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to upload ffmpeg_script.sh") from exc

    storage.update_run_log(run_id, "ffmpeg_script", "complete", output_url=script_key)
    logger.info("ffmpeg_script.sh generated: run=%s key=%s", run_id, script_key)
    return FFmpegScriptResponse(status="complete", script_key=script_key)
