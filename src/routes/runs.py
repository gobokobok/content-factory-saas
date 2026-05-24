"""Route handlers for /runs endpoints."""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from src.config import Settings, get_settings
from src.exceptions import StorageError
from src.models import (
    ArtifactResponse,
    RunCreateRequest,
    RunCreateResponse,
    RunListResponse,
    RunSummary,
    VoiceoverUploadUrlRequest,
    VoiceoverUploadUrlResponse,
)
from src.storage import R2Client

logger = logging.getLogger(__name__)

router = APIRouter()

_STEP_ARTIFACT_KEYS: dict[str, tuple[str, str]] = {
    "storyboard": ("runs/{run_id}/storyboard.json", "application/json"),
    "manifest": ("runs/{run_id}/asset_manifest.json", "application/json"),
    "ffmpeg_script": ("runs/{run_id}/ffmpeg_script.sh", "text/plain"),
    "render": ("runs/{run_id}/output/final.mp4", "video/mp4"),
}


def _make_r2_client(settings: Settings) -> R2Client:
    """Construct an R2Client from settings."""
    return R2Client(
        settings.R2_ACCOUNT_ID,
        settings.R2_ACCESS_KEY_ID,
        settings.R2_SECRET_ACCESS_KEY,
        settings.R2_BUCKET_NAME,
    )


@router.post("/runs", response_model=RunCreateResponse, status_code=201)
def create_run(
    body: RunCreateRequest,
    settings: Settings = Depends(get_settings),
) -> RunCreateResponse:
    """Create an R2 run prefix and initialise run_log.json."""
    client = _make_r2_client(settings)
    run_id = f"{date.today().isoformat()}_{body.slug}"
    try:
        prefix = client.create_run_folder(run_id)
    except StorageError as exc:
        logger.error("Storage error creating run '%s': %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RunCreateResponse(run_id=run_id, storage_prefix=prefix)


@router.get("/runs", response_model=RunListResponse)
def list_runs(settings: Settings = Depends(get_settings)) -> RunListResponse:
    """List all runs sorted by date descending."""
    client = _make_r2_client(settings)
    try:
        runs = client.list_runs()
    except StorageError as exc:
        logger.error("Storage error listing runs: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RunListResponse(runs=[RunSummary(**r) for r in runs])


@router.post("/runs/{run_id}/voiceover-upload-url", response_model=VoiceoverUploadUrlResponse)
def voiceover_upload_url(
    run_id: str,
    body: VoiceoverUploadUrlRequest,
    settings: Settings = Depends(get_settings),
) -> VoiceoverUploadUrlResponse:
    """Generate a presigned R2 PUT URL for uploading a voiceover file directly from the browser."""
    key = f"runs/{run_id}/voiceover/{body.filename}"
    client = _make_r2_client(settings)
    try:
        url = client.generate_presigned_put_url(key)
    except StorageError as exc:
        logger.error("Storage error generating voiceover upload URL for '%s': %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return VoiceoverUploadUrlResponse(upload_url=url, key=key)


@router.get("/runs/{run_id}/artifact/{step}", response_model=ArtifactResponse)
def get_artifact(
    run_id: str,
    step: str,
    settings: Settings = Depends(get_settings),
) -> ArtifactResponse:
    """Fetch the artifact for a pipeline step. render step returns a presigned URL."""
    if step not in _STEP_ARTIFACT_KEYS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid step '{step}'. Must be one of: {', '.join(_STEP_ARTIFACT_KEYS)}",
        )
    client = _make_r2_client(settings)
    key_template, content_type = _STEP_ARTIFACT_KEYS[step]
    key = key_template.format(run_id=run_id)
    try:
        if step == "render":
            url = client.generate_presigned_url(key)
            return ArtifactResponse(step=step, content_type=content_type, url=url)
        elif content_type == "application/json":
            data = client.get_json(key)
            return ArtifactResponse(step=step, content_type=content_type, content=data)
        else:
            text = client.get_bytes(key).decode("utf-8")
            return ArtifactResponse(step=step, content_type=content_type, content=text)
    except StorageError as exc:
        logger.warning("Artifact not found: run=%s step=%s key=%s: %s", run_id, step, key, exc)
        raise HTTPException(
            status_code=404, detail=f"Artifact not found for step '{step}' in run '{run_id}'"
        ) from exc
