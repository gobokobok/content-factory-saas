"""Route handlers for /runs/{run_id}/storyboard endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from src import pipeline
from src.config import Settings, get_settings
from src.exceptions import (
    StoryboardAPIError,
    StoryboardParseError,
    StoryboardValidationError,
    StorageError,
)
from src.models import StoryboardRequest, StoryboardResponse, WordTimestamp
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
    """Generate storyboard.json from a VO script, upload to R2, update run_log.json.

    When alignment.json is present in R2, word-level timestamps are injected into the
    Claude prompt so scene durations are derived from real speech timing (VO-first flow).
    """
    storage = R2Client(
        settings.R2_ACCOUNT_ID,
        settings.R2_ACCESS_KEY_ID,
        settings.R2_SECRET_ACCESS_KEY,
        settings.R2_BUCKET_NAME,
    )

    # Load alignment timestamps if available (VO-first flow)
    word_timestamps: Optional[list[WordTimestamp]] = None
    alignment_key = f"runs/{run_id}/alignment.json"
    try:
        alignment_data = storage.get_json(alignment_key)
        words_raw = alignment_data.get("words", [])
        if words_raw:
            word_timestamps = [WordTimestamp.model_validate(w) for w in words_raw]
            logger.info(
                "Alignment data loaded for storyboard: run=%s words=%d", run_id, len(word_timestamps)
            )
    except StorageError:
        logger.info(
            "No alignment.json found — generating storyboard without timestamps: run=%s", run_id
        )

    # Resolve script: body takes precedence; fall back to saved draft in R2
    script = body.script.strip()
    if not script:
        try:
            script = storage.get_bytes(f"runs/{run_id}/script.txt").decode("utf-8").strip()
            logger.info("Using draft script.txt for storyboard: run=%s", run_id)
        except StorageError:
            pass
    if not script:
        raise HTTPException(
            status_code=422,
            detail="script is required — provide in the request body or save a draft first",
        )

    try:
        storyboard, validation = await generate_storyboard(script, settings, word_timestamps)
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
