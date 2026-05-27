"""Route handlers for /runs/{run_id}/storyboard endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from src import pipeline
from src.config import Settings, get_settings
from src.exceptions import (
    StoryboardAPIError,
    StoryboardParseError,
    StoryboardValidationError,
    StorageError,
)
from src.models import StoryboardRequest, StoryboardResponse
from src.storyboard import generate_storyboard
from src.storage import R2Client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/runs/{run_id}/storyboard", response_model=StoryboardResponse)
async def create_storyboard(
    run_id: str,
    body: StoryboardRequest,
    settings: Settings = Depends(get_settings),
) -> StoryboardResponse:
    """Generate storyboard.json from a VO script, upload to R2, update run_log.json."""
    storage = R2Client(
        settings.R2_ACCOUNT_ID,
        settings.R2_ACCESS_KEY_ID,
        settings.R2_SECRET_ACCESS_KEY,
        settings.R2_BUCKET_NAME,
    )

    try:
        storyboard, validation = await generate_storyboard(body.script, settings)
    except (StoryboardAPIError, StoryboardParseError, StoryboardValidationError) as exc:
        logger.error("Storyboard generation failed for run '%s': %s", run_id, exc)
        try:
            storage.update_run_log(run_id, "storyboard", "failed", error=str(exc))
        except StorageError as storage_exc:
            logger.error(
                "Failed to write run_log failure for run '%s': %s", run_id, storage_exc
            )
        pipeline.summarize_step(run_id, storage, settings)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    storyboard_key = f"runs/{run_id}/storyboard.json"
    try:
        storage.upload_json(
            storyboard_key,
            storyboard.model_dump(by_alias=True, mode="json"),
        )
        storage.update_run_log(
            run_id,
            "storyboard",
            "complete",
            output_url=storyboard_key,
            input_tokens=validation.input_tokens,
            output_tokens=validation.output_tokens,
            cost_usd=validation.cost_usd,
        )
    except StorageError as exc:
        logger.error("Storage error after storyboard generation for run '%s': %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    pipeline.summarize_step(run_id, storage, settings)

    return StoryboardResponse(status="complete", storyboard_key=storyboard_key)
