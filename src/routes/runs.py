"""Route handlers for /runs endpoints."""

import logging
import re
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from src.config import Settings, get_settings
from src.exceptions import StorageError
from src.models import (
    ArtifactResponse,
    AssetLinkResponse,
    DraftRequest,
    DraftResponse,
    MusicUploadUrlRequest,
    MusicUploadUrlResponse,
    RunCreateRequest,
    RunCreateResponse,
    RunListResponse,
    RunLogTxtResponse,
    RunSummary,
    VideoSettings,
    VideoSettingsResponse,
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
    "ffmpeg_log": ("runs/{run_id}/ffmpeg_log.txt", "text/plain"),
    "run_log": ("runs/{run_id}/run_log.json", "application/json"),
    "render": ("runs/{run_id}/output/final.mp4", "video/mp4"),
    "metadata": ("runs/{run_id}/metadata.json", "application/json"),
}


def _make_r2_client(settings: Settings) -> R2Client:
    """Construct an R2Client from settings."""
    return R2Client(
        settings.R2_ACCOUNT_ID,
        settings.R2_ACCESS_KEY_ID,
        settings.R2_SECRET_ACCESS_KEY,
        settings.R2_BUCKET_NAME,
    )


def _slugify(name: str) -> str:
    """Convert a project name to a URL-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@router.post("/runs", response_model=RunCreateResponse, status_code=201)
def create_run(
    body: RunCreateRequest,
    settings: Settings = Depends(get_settings),
) -> RunCreateResponse:
    """Create an R2 run prefix and initialise run_log.json."""
    client = _make_r2_client(settings)
    slug = _slugify(body.project_name)
    run_id = f"{date.today().isoformat()}_{slug}"
    try:
        prefix = client.create_run_folder(run_id, project_name=body.project_name)
    except StorageError as exc:
        logger.error("Storage error creating run '%s': %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RunCreateResponse(run_id=run_id, project_name=body.project_name, storage_prefix=prefix)


@router.get("/runs", response_model=RunListResponse)
def list_runs(settings: Settings = Depends(get_settings)) -> RunListResponse:
    """List all runs sorted by date descending."""
    t_start = time.monotonic()
    client = _make_r2_client(settings)
    try:
        runs = client.list_runs()
    except StorageError as exc:
        logger.error("Storage error listing runs: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    elapsed_ms = (time.monotonic() - t_start) * 1000
    logger.info("GET /runs: %d runs in %.0fms", len(runs), elapsed_ms)
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


@router.delete("/runs/{run_id}/voiceover", status_code=204)
def delete_voiceover(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> None:
    """Delete all voiceover files for a run. No-op if none exist."""
    client = _make_r2_client(settings)
    try:
        keys = client.list_keys(f"runs/{run_id}/voiceover/")
    except StorageError as exc:
        logger.error("Storage error listing voiceover for run '%s': %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    for key in keys:
        try:
            client._client.delete_object(Bucket=client._bucket, Key=key)
        except Exception as exc:
            logger.warning("Could not delete voiceover key '%s': %s", key, exc)


@router.post("/runs/{run_id}/music-upload-url", response_model=MusicUploadUrlResponse)
def music_upload_url(
    run_id: str,
    body: MusicUploadUrlRequest,
    settings: Settings = Depends(get_settings),
) -> MusicUploadUrlResponse:
    """Generate a presigned R2 PUT URL for uploading a background music file from the browser."""
    key = f"runs/{run_id}/music/{body.filename}"
    client = _make_r2_client(settings)
    try:
        url = client.generate_presigned_put_url(key)
    except StorageError as exc:
        logger.error("Storage error generating music upload URL for '%s': %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return MusicUploadUrlResponse(upload_url=url, key=key)


@router.delete("/runs/{run_id}/music", status_code=204)
def delete_music(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> None:
    """Delete all background music files for a run. No-op if none exist."""
    client = _make_r2_client(settings)
    try:
        keys = client.list_keys(f"runs/{run_id}/music/")
    except StorageError as exc:
        logger.error("Storage error listing music for run '%s': %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    for key in keys:
        try:
            client._client.delete_object(Bucket=client._bucket, Key=key)
        except Exception as exc:
            logger.warning("Could not delete music key '%s': %s", key, exc)


@router.get("/runs/{run_id}/run-log-txt", response_model=RunLogTxtResponse)
def get_run_log_txt(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> RunLogTxtResponse:
    """Return the Haiku-generated run_log.txt for a run. Returns available=False if not yet written."""
    client = _make_r2_client(settings)
    try:
        text = client.get_bytes(f"runs/{run_id}/run_log.txt").decode("utf-8")
        return RunLogTxtResponse(content=text, available=True)
    except StorageError:
        return RunLogTxtResponse(content="", available=False)


@router.post("/runs/{run_id}/draft", response_model=DraftResponse)
def save_draft(
    run_id: str,
    body: DraftRequest,
    settings: Settings = Depends(get_settings),
) -> DraftResponse:
    """Save project_name + script as a draft. Rejected (409) if storyboard is already complete."""
    client = _make_r2_client(settings)
    try:
        run_log = client.get_json(f"runs/{run_id}/run_log.json")
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}") from exc

    if run_log.get("steps", {}).get("storyboard", {}).get("status") == "complete":
        raise HTTPException(
            status_code=409, detail="Cannot save draft: storyboard is already complete"
        )

    try:
        client.upload_text(f"runs/{run_id}/script.txt", body.script)
    except StorageError as exc:
        logger.error("Storage error saving draft for run '%s': %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return DraftResponse(
        status="saved",
        project_name=run_log.get("project_name", body.project_name),
        script=body.script,
    )


@router.get("/runs/{run_id}/draft", response_model=DraftResponse)
def get_draft(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> DraftResponse:
    """Return the saved draft: project_name (from run_log), script (from script.txt), VO filename."""
    client = _make_r2_client(settings)
    try:
        run_log = client.get_json(f"runs/{run_id}/run_log.json")
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}") from exc

    project_name = run_log.get("project_name", "")

    try:
        script = client.get_bytes(f"runs/{run_id}/script.txt").decode("utf-8")
    except StorageError:
        script = ""

    vo_filename: str | None = None
    try:
        keys = client.list_keys(f"runs/{run_id}/voiceover/")
        audio_keys = [k for k in keys if k.endswith((".mp3", ".wav", ".m4a"))]
        if audio_keys:
            vo_filename = audio_keys[0].split("/")[-1]
    except StorageError:
        pass

    music_filename: str | None = None
    try:
        music_keys = client.list_keys(f"runs/{run_id}/music/")
        audio_music = [k for k in music_keys if k.endswith((".mp3", ".wav", ".m4a"))]
        if audio_music:
            music_filename = audio_music[0].split("/")[-1]
    except StorageError:
        pass

    return DraftResponse(
        status="ok",
        project_name=project_name,
        script=script,
        vo_filename=vo_filename,
        music_filename=music_filename,
    )


@router.get("/runs/{run_id}/asset-link", response_model=AssetLinkResponse)
def get_asset_link(
    run_id: str,
    key: str,
    settings: Settings = Depends(get_settings),
) -> AssetLinkResponse:
    """Generate a 1-hour presigned GET URL for a run asset. Rejects keys outside the run prefix."""
    expected_prefix = f"runs/{run_id}/"
    if not key.startswith(expected_prefix) or ".." in key.split("/"):
        raise HTTPException(
            status_code=403,
            detail=f"Key must start with '{expected_prefix}'",
        )
    client = _make_r2_client(settings)
    try:
        url = client.generate_presigned_url(key)
    except StorageError as exc:
        logger.error("Storage error generating asset link for run '%s' key '%s': %s", run_id, key, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return AssetLinkResponse(url=url, expires_in=3600)


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> None:
    """Delete a run and all its R2 assets. Returns 204 on success, 404 if not found."""
    client = _make_r2_client(settings)
    try:
        client.delete_run(run_id)
    except StorageError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg) from exc
        logger.error("Storage error deleting run '%s': %s", run_id, exc)
        raise HTTPException(status_code=500, detail=msg) from exc


@router.post("/runs/{run_id}/settings", response_model=VideoSettingsResponse)
def save_video_settings(
    run_id: str,
    body: VideoSettings,
    settings: Settings = Depends(get_settings),
) -> VideoSettingsResponse:
    """Save video settings to settings.json in R2."""
    client = _make_r2_client(settings)
    key = f"runs/{run_id}/settings.json"
    try:
        client.upload_json(key, body.model_dump())
    except StorageError as exc:
        logger.error("Storage error saving settings for run '%s': %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return VideoSettingsResponse(status="saved", settings=body)


@router.get("/runs/{run_id}/settings", response_model=VideoSettingsResponse)
def get_video_settings(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> VideoSettingsResponse:
    """Return stored video settings, or defaults when settings.json is absent."""
    client = _make_r2_client(settings)
    key = f"runs/{run_id}/settings.json"
    try:
        data = client.get_json(key)
        video_settings = VideoSettings.model_validate(data)
    except StorageError:
        video_settings = VideoSettings()
    return VideoSettingsResponse(status="ok", settings=video_settings)


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


@router.get("/runs/{run_id}/download")
def download_video(
    run_id: str,
    settings: Settings = Depends(get_settings),
) -> Response:
    """Stream the final rendered video as an attachment for browser download.

    Proxies the file through the server so the browser can fetch it
    same-origin — direct fetch() of the cross-origin R2 presigned URL
    fails with a CORS error even though <video src> playback works fine.
    Returns 404 when no final.mp4 has been rendered for this run.
    """
    client = _make_r2_client(settings)
    key = f"runs/{run_id}/output/final.mp4"
    try:
        data = client.get_bytes(key)
    except StorageError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Rendered video not found for run '{run_id}'",
        ) from exc
    return Response(
        content=data,
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{run_id}_final.mp4"'},
    )
