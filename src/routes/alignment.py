"""Alignment route — POST /runs/{run_id}/alignment.

Extracts word-level timestamps from the run's uploaded voiceover via Deepgram Nova-2.
Falls back to proportional distribution if the API call fails.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from src import pipeline
from src.alignment import AlignmentError, align_audio, proportional_fallback
from src.config import Settings, get_settings
from src.exceptions import StorageError
from src.models import AlignmentResponse, WordTimestamp
from src.storage import R2Client

logger = logging.getLogger(__name__)
router = APIRouter()


def _make_r2_client(settings: Settings) -> R2Client:
    """Construct R2Client from settings."""
    return R2Client(
        account_id=settings.R2_ACCOUNT_ID,
        access_key_id=settings.R2_ACCESS_KEY_ID,
        secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        bucket_name=settings.R2_BUCKET_NAME,
    )


@router.post("/runs/{run_id}/alignment")
async def create_alignment(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> AlignmentResponse:
    """Extract word-level timestamps from the run's voiceover and store alignment.json in R2.

    Tries Deepgram Nova-2 first; falls back to character-count proportional distribution
    using storyboard voiceover lines if Deepgram is unavailable.
    """
    storage = _make_r2_client(settings)

    # Discover the voiceover file
    voiceover_prefix = f"runs/{run_id}/voiceover/"
    try:
        keys = storage.list_keys(voiceover_prefix)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    audio_keys = [k for k in keys if k.lower().endswith((".mp3", ".wav", ".m4a"))]
    if not audio_keys:
        raise HTTPException(
            status_code=404,
            detail=f"No voiceover file found under {voiceover_prefix}",
        )

    audio_key = audio_keys[0]
    try:
        audio_url = storage.generate_presigned_url(audio_key, expires_in=300)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Attempt Deepgram alignment; fall back to proportional if it fails
    words: list[WordTimestamp]
    used_fallback = False

    if not settings.DEEPGRAM_API_KEY:
        logger.warning(
            "DEEPGRAM_API_KEY not set — using proportional fallback: run_id=%s", run_id
        )
        used_fallback = True
        words = _proportional_from_storyboard(run_id, storage)
    else:
        try:
            words = await align_audio(audio_url, settings.DEEPGRAM_API_KEY)
            logger.info(
                "Deepgram alignment complete: run_id=%s words=%d", run_id, len(words)
            )
        except AlignmentError as exc:
            logger.warning(
                "Deepgram failed (%s) — using proportional fallback: run_id=%s", exc, run_id
            )
            used_fallback = True
            words = _proportional_from_storyboard(run_id, storage)

    # Store alignment.json
    alignment_key = f"runs/{run_id}/alignment.json"
    alignment_data: dict = {
        "run_id": run_id,
        "word_count": len(words),
        "used_fallback": used_fallback,
        "words": [w.model_dump() for w in words],
    }
    try:
        storage.upload_json(alignment_key, alignment_data)
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to store alignment.json: {exc}")

    try:
        storage.update_run_log(run_id, "alignment", "complete", output_url=alignment_key)
    except Exception as exc:
        # Non-fatal: run_log update may fail for runs created before alignment step was added
        logger.warning("Could not update run_log alignment step: run_id=%s error=%s", run_id, exc)
    pipeline.summarize_step(run_id, storage, settings)

    return AlignmentResponse(
        status="complete",
        alignment_key=alignment_key,
        word_count=len(words),
        used_fallback=used_fallback,
    )


def _proportional_from_storyboard(run_id: str, storage: R2Client) -> list[WordTimestamp]:
    """Build proportional timestamps from storyboard voiceover lines.

    Raises HTTPException 404 if storyboard.json is missing.
    """
    try:
        storyboard = storage.get_json(f"runs/{run_id}/storyboard.json")
    except StorageError:
        raise HTTPException(
            status_code=404,
            detail="Deepgram unavailable and storyboard.json not found for proportional fallback",
        )

    scenes = storyboard.get("scenes", [])
    text = " ".join(s.get("voiceover_line", "") for s in scenes)
    total_duration_s = float(
        storyboard.get("summary", {}).get("total_duration_s", 60.0)
    )
    return proportional_fallback(text, total_duration_s)
