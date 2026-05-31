"""TTS route — POST /runs/{run_id}/tts.

Reads script.txt from R2, generates MP3 via ElevenLabs, purges any existing
voiceover files only on success, stores generated.mp3, then auto-runs alignment.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from src import pipeline
from src.config import Settings, get_settings
from src.exceptions import StorageError, TTSError
from src.models import TTSResponse
from src.storage import R2Client
from src.tts import generate_tts

logger = logging.getLogger(__name__)
router = APIRouter()

_PCM_SAMPLE_RATE = 44100
_PCM_CHANNELS = 1
_BITS_PER_SAMPLE = 16


def _make_r2_client(settings: Settings) -> R2Client:
    """Construct R2Client from settings."""
    return R2Client(
        account_id=settings.R2_ACCOUNT_ID,
        access_key_id=settings.R2_ACCESS_KEY_ID,
        secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        bucket_name=settings.R2_BUCKET_NAME,
    )


def _estimate_duration_s(mp3_bytes: bytes) -> float:
    """Return a rough duration estimate from MP3 byte count (128 kbps assumed)."""
    return len(mp3_bytes) / (128_000 / 8)


@router.post("/runs/{run_id}/tts")
async def create_tts(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> TTSResponse:
    """Generate a voiceover MP3 from the run's saved script using ElevenLabs TTS.

    On success: any existing voiceover files are purged from R2 before storing
    runs/{run_id}/voiceover/generated.mp3.  On failure the existing upload is
    left untouched.
    """
    if not settings.ELEVENLABS_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="ELEVENLABS_API_KEY is not configured on this server",
        )
    if not settings.ELEVENLABS_VOICE_ID:
        raise HTTPException(
            status_code=503,
            detail="ELEVENLABS_VOICE_ID is not configured on this server",
        )

    storage = _make_r2_client(settings)

    # Read script.txt from R2
    script_key = f"runs/{run_id}/script.txt"
    try:
        script_bytes = storage.get_bytes(script_key)
        script = script_bytes.decode("utf-8").strip()
    except StorageError:
        raise HTTPException(
            status_code=404,
            detail="script.txt not found — save a draft first",
        )

    if not script:
        raise HTTPException(status_code=422, detail="Script is empty")

    # Generate TTS — failures here leave any existing upload untouched
    try:
        mp3_bytes, chunk_count = await generate_tts(
            script,
            api_key=settings.ELEVENLABS_API_KEY,
            voice_id=settings.ELEVENLABS_VOICE_ID,
        )
    except TTSError as exc:
        logger.error("TTS generation failed: run_id=%s error=%s", run_id, exc)
        try:
            storage.update_run_log(run_id, "alignment", "failed", error=str(exc))
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=f"TTS generation failed: {exc}")

    # Delete-on-success: purge any existing voiceover files before storing the new one
    voiceover_prefix = f"runs/{run_id}/voiceover/"
    try:
        existing_keys = storage.list_keys(voiceover_prefix)
        for key in existing_keys:
            try:
                storage._client.delete_object(Bucket=storage._bucket, Key=key)
                logger.info("TTS: purged existing voiceover %s", key)
            except Exception as exc:
                logger.warning("TTS: could not delete %s: %s", key, exc)
    except StorageError as exc:
        logger.warning("TTS: could not list voiceover prefix to purge: %s", exc)

    # Store generated.mp3
    output_key = f"runs/{run_id}/voiceover/generated.mp3"
    try:
        storage.upload_bytes(output_key, mp3_bytes, content_type="audio/mpeg")
    except StorageError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to store generated.mp3: {exc}"
        )

    duration_s = _estimate_duration_s(mp3_bytes)
    logger.info(
        "TTS complete: run_id=%s chunks=%d mp3=%d bytes est_duration=%.1fs",
        run_id, chunk_count, len(mp3_bytes), duration_s,
    )

    pipeline.summarize_step(run_id, storage, settings)

    return TTSResponse(
        status="complete",
        key=output_key,
        chunk_count=chunk_count,
        duration_s=round(duration_s, 1),
    )
