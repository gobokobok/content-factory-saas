"""Asset acquisition route — POST /runs/{run_id}/assets."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from src.acquisition import MIN_ACQUIRED_FOR_COMPLETE, run_acquisition
from src.config import Settings, get_settings
from src.exceptions import StorageError
from src.models import AcquisitionResponse, AssetManifest
from src.pexels import PexelsClient
from src.replicate_client import ReplicateClient
from src.storage import R2Client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/runs/{run_id}/assets", response_model=AcquisitionResponse)
def acquire_assets(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> AcquisitionResponse:
    """Acquire all pending assets for a run using the Pexels → Replicate fallback chain.

    Reads asset_manifest.json from R2, processes every pending scene, writes
    the updated manifest back, and marks asset_acquisition in run_log.json as
    complete or failed based on total acquired count.
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

    try:
        summary = run_acquisition(run_id, manifest, pexels, replicate, storage)
    except Exception as exc:
        logger.error("Acquisition loop failed unexpectedly: run=%s error=%s", run_id, exc)
        storage.update_run_log(run_id, "asset_acquisition", "failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        storage.upload_json(manifest_key, manifest.model_dump(mode="json"))
    except StorageError as exc:
        logger.error("Failed to write updated manifest: run=%s error=%s", run_id, exc)
        storage.update_run_log(run_id, "asset_acquisition", "failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    step_status = "complete" if summary["acquired"] >= MIN_ACQUIRED_FOR_COMPLETE else "failed"
    storage.update_run_log(
        run_id, "asset_acquisition", step_status, output_url=manifest_key
    )

    return AcquisitionResponse(
        status=step_status,
        acquired=summary["acquired"],
        failed=summary["failed"],
        sources=summary["sources"],
        manifest_key=manifest_key,
    )
