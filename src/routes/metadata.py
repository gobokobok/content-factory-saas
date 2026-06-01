"""POST /runs/{run_id}/metadata endpoint."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from src import pipeline
from src.config import Settings, get_settings
from src.exceptions import MetadataError, StorageError
from src.metadata_generator import generate_metadata
from src.models import MetadataResponse, Storyboard
from src.storage import R2Client
from src.utils.model_router import ModelRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/runs/{run_id}/metadata", response_model=MetadataResponse)
async def create_metadata(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> MetadataResponse:
    """Generate publishing metadata via Claude Haiku and store as metadata.json in R2."""
    storage = R2Client(
        settings.R2_ACCOUNT_ID,
        settings.R2_ACCESS_KEY_ID,
        settings.R2_SECRET_ACCESS_KEY,
        settings.R2_BUCKET_NAME,
    )

    # Load project_name from run_log.json
    try:
        run_log_data = storage.get_json(f"runs/{run_id}/run_log.json")
    except StorageError:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    project_name = run_log_data.get("project_name") or run_id

    # Load storyboard.json
    try:
        storyboard_data = storage.get_json(f"runs/{run_id}/storyboard.json")
    except StorageError:
        raise HTTPException(
            status_code=404, detail=f"storyboard.json not found for run '{run_id}'"
        )

    try:
        storyboard = Storyboard.model_validate(storyboard_data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid storyboard: {exc}") from exc

    # Generate metadata via Claude Haiku
    router_obj = ModelRouter(settings)
    try:
        metadata, input_tokens, output_tokens, cost_usd = await generate_metadata(
            project_name, storyboard, settings.ANTHROPIC_API_KEY, router_obj
        )
    except MetadataError as exc:
        logger.error("Metadata generation failed for run '%s': %s", run_id, exc)
        try:
            storage.update_run_log(run_id, "metadata", "failed", error=str(exc))
        except StorageError as storage_exc:
            logger.error(
                "Failed to write run_log failure for run '%s': %s", run_id, storage_exc
            )
        pipeline.summarize_step(run_id, storage, settings)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Persist metadata.json and update run_log
    metadata_key = f"runs/{run_id}/metadata.json"
    try:
        storage.upload_json(metadata_key, metadata.model_dump())
        storage.update_run_log(
            run_id,
            "metadata",
            "complete",
            output_url=metadata_key,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )
    except StorageError as exc:
        logger.error("Storage error after metadata generation for run '%s': %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    pipeline.summarize_step(run_id, storage, settings)

    return MetadataResponse(status="complete", metadata_key=metadata_key)
