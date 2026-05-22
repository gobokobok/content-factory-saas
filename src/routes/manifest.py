"""Route handlers for /runs/{run_id}/manifest endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from src.config import Settings, get_settings
from src.exceptions import ManifestError, StorageError
from src.manifest import build_manifest, clip_type_breakdown
from src.models import ManifestResponse
from src.storage import R2Client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/runs/{run_id}/manifest", response_model=ManifestResponse)
def create_manifest(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> ManifestResponse:
    """Read storyboard.json from R2, build asset_manifest.json, upload, and update run_log."""
    storage = R2Client(
        settings.R2_ACCOUNT_ID,
        settings.R2_ACCESS_KEY_ID,
        settings.R2_SECRET_ACCESS_KEY,
        settings.R2_BUCKET_NAME,
    )

    storyboard_key = f"runs/{run_id}/storyboard.json"
    try:
        storyboard_data = storage.get_json(storyboard_key)
    except StorageError as exc:
        logger.error("Failed to read storyboard for run '%s': %s", run_id, exc)
        raise HTTPException(status_code=404, detail=f"storyboard.json not found: {exc}") from exc

    try:
        manifest = build_manifest(run_id, storyboard_data)
    except ManifestError as exc:
        logger.error("Manifest build failed for run '%s': %s", run_id, exc)
        try:
            storage.update_run_log(run_id, "asset_manifest", "failed", error=str(exc))
        except StorageError as storage_exc:
            logger.error(
                "Failed to write run_log failure for run '%s': %s", run_id, storage_exc
            )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    manifest_key = f"runs/{run_id}/asset_manifest.json"
    try:
        storage.upload_json(manifest_key, manifest.model_dump(mode="json"))
        storage.update_run_log(
            run_id, "asset_manifest", "complete", output_url=manifest_key
        )
    except StorageError as exc:
        logger.error("Storage error writing manifest for run '%s': %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    breakdown = clip_type_breakdown(manifest)
    return ManifestResponse(
        status="complete",
        manifest_key=manifest_key,
        scene_count=len(manifest.entries),
        clip_type_breakdown=breakdown,
    )
