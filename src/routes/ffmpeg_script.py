"""Route handler for POST /runs/{run_id}/ffmpeg-script."""

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from src import pipeline
from src.config import Settings, get_settings
from src.exceptions import FFmpegBuildError, StorageError
from src.ffmpeg_builder import build_ffmpeg_script, get_audio_duration, redistribute_scene_durations
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

    # When alignment.json is present, storyboard durations already reflect real speech timing
    # (set by Claude using Deepgram timestamps). Skip ffprobe redistribution.
    alignment_key = f"runs/{run_id}/alignment.json"
    has_alignment = False
    try:
        storage.get_json(alignment_key)
        has_alignment = True
        logger.info("alignment.json present — skipping ffprobe redistribution: run=%s", run_id)
    except StorageError:
        pass

    if not has_alignment:
        vo_prefix = f"runs/{run_id}/voiceover/"
        try:
            vo_keys = storage.list_keys(vo_prefix)
            vo_key = next(
                (k for k in vo_keys if k.lower().endswith((".mp3", ".wav", ".m4a"))),
                None,
            )
            if vo_key:
                filename = vo_key.split("/")[-1]
                with tempfile.TemporaryDirectory() as tmpdir:
                    vo_local = Path(tmpdir) / filename
                    vo_local.write_bytes(storage.get_bytes(vo_key))
                    audio_duration = get_audio_duration(vo_local)
                updated_scenes = redistribute_scene_durations(storyboard.scenes, audio_duration)
                storyboard = storyboard.model_copy(update={"scenes": updated_scenes})
                logger.info(
                    "Pacing calibrated: run=%s vo=%s duration=%.2fs", run_id, vo_key, audio_duration
                )
            else:
                logger.warning(
                    "No voiceover found for run=%s — using storyboard durations unchanged", run_id
                )
        except (StorageError, FFmpegBuildError) as exc:
            logger.warning("Voiceover pacing skipped for run=%s: %s", run_id, exc)

    try:
        script = build_ffmpeg_script(run_id, storyboard, manifest)
    except FFmpegBuildError as exc:
        logger.error("FFmpeg script build failed for run=%s: %s", run_id, exc)
        storage.update_run_log(run_id, "ffmpeg_script", "failed", error=str(exc))
        pipeline.summarize_step(run_id, storage, settings)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    script_key = f"runs/{run_id}/ffmpeg_script.sh"
    try:
        storage.upload_text(script_key, script, content_type="text/x-shellscript")
    except StorageError as exc:
        logger.error("Failed to upload ffmpeg_script.sh for run=%s: %s", run_id, exc)
        storage.update_run_log(run_id, "ffmpeg_script", "failed", error=str(exc))
        pipeline.summarize_step(run_id, storage, settings)
        raise HTTPException(status_code=500, detail="Failed to upload ffmpeg_script.sh") from exc

    storage.update_run_log(run_id, "ffmpeg_script", "complete", output_url=script_key)
    pipeline.summarize_step(run_id, storage, settings)
    logger.info("ffmpeg_script.sh generated: run=%s key=%s", run_id, script_key)
    return FFmpegScriptResponse(status="complete", script_key=script_key)
