"""Standalone worker routes — POST /workers/{storyboard,metadata,voice,acquisition,render}.

Designed for a future step-by-step manual UI and standalone testing; storyboard,
voice, and render run as background tasks (Studio polls .../status) because
Railway's HTTP layer times out long-running LLM/FFmpeg calls.
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.schemas import StageState
from cf_platform.interfaces.dependencies import PLATFORM_USER_ID, get_artifact_storage
from cf_platform.interfaces.routes._helpers import latest_artifact_key as _latest_artifact_key
from cf_platform.workers.acquisition_worker import (
    ACQUISITION_WORKER_REGISTRATION,
    AssetManifestArtifact,
    build_acquisition_worker,
)
from cf_platform.workers.render_worker import (
    RENDER_WORKER_REGISTRATION,
    RenderArtifact,
    build_render_worker,
)
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.storyboard_worker import (
    STORYBOARD_WORKER_REGISTRATION,
    VerifiedStoryboardArtifact,
    build_storyboard_worker,
)
from cf_platform.workers.voice_production import (
    VOICE_PRODUCTION_REGISTRATION,
    VoiceAlignmentArtifact,
    build_voice_production_worker,
)

_logger = logging.getLogger(__name__)

router = APIRouter()


class StoryboardWorkerRequest(BaseModel):
    """Request body for POST /platform/workers/storyboard."""

    run_id: str
    script: str
    format_track: str = "portrait"


class StoryboardWorkerResponse(BaseModel):
    """202 response body for POST /platform/workers/storyboard (accepted — runs async)."""

    status: str = "accepted"
    run_id: str


async def _run_storyboard_background(
    run_id: str,
    job_id: str,
    state: StageState,
    worker: Any,
    storage: ArtifactStorage,
) -> None:
    """Background task: generates storyboard and updates storyboard/current_job.json."""
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope

    job_key = f"runs/{run_id}/storyboard/current_job.json"
    try:
        output = await worker(state)
        result_artifact = output.artifact
        if not isinstance(result_artifact, VerifiedStoryboardArtifact):
            raise RuntimeError(f"StoryboardWorker returned unexpected type: {type(result_artifact)}")

        storyboard_lineage = LineageEnvelope(
            run_id=run_id,
            worker="storyboard_worker",
            worker_version=STORYBOARD_WORKER_REGISTRATION.worker_version,
            prompt_version=STORYBOARD_WORKER_REGISTRATION.prompt_version,
            model=STORYBOARD_WORKER_REGISTRATION.model,
            created_at=datetime.now(),
        )
        storyboard_record = await write_artifact(
            storage,
            result_artifact,
            name="verified_storyboard",
            stage="storyboard",
            run_id=run_id,
            user_id=PLATFORM_USER_ID,
            lineage=storyboard_lineage,
        )

        # Invalidate stale asset_manifest so Studio sees 0/0 counts after a re-generate.
        old_manifest_key = await _latest_artifact_key(storage, run_id, "acquisition", "asset_manifest")
        if old_manifest_key:
            try:
                await storage.put_json(old_manifest_key, {"run_id": run_id, "entries": []})
            except Exception:
                pass

        await storage.put_json(job_key, {
            "job_id": job_id,
            "status": "complete",
            "artifact_key": storyboard_record.r2_key,
            "scene_count": result_artifact.scene_count,
            "prompt_version": result_artifact.prompt_version,
        })
        _logger.info("StoryboardWorker background task complete for run %s (%d scenes)", run_id, result_artifact.scene_count)
    except Exception as exc:
        _logger.exception("StoryboardWorker background task failed for run %s: %s", run_id, exc)
        try:
            await storage.put_json(job_key, {"job_id": job_id, "status": "error", "error": str(exc)})
        except Exception:
            pass


@router.post("/workers/storyboard", response_model=StoryboardWorkerResponse, status_code=202)
async def storyboard_worker_endpoint(
    body: StoryboardWorkerRequest,
    background_tasks: BackgroundTasks,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> StoryboardWorkerResponse:
    """Enqueue storyboard generation (returns 202 immediately).

    Writes the script artifact synchronously, resolves any existing voice_alignment,
    then hands off the Claude generate→review→patch cycle to a background task.
    Poll GET /platform/studio/runs/{run_id}/storyboard/status for progress.
    """
    import uuid as _uuid_mod

    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope

    script_artifact = ScriptArtifact(
        idea_title="",
        niche=None,
        script=body.script,
        word_count=len(body.script.split()),
        status="ok",
        generated_at=datetime.now(),
    )
    script_lineage = LineageEnvelope(
        run_id=body.run_id,
        worker="storyboard_request",
        worker_version="1.0.0",
        prompt_version="v1",
        model="none",
        created_at=datetime.now(),
    )
    script_record = await write_artifact(
        storage,
        script_artifact,
        name="script",
        stage="script",
        run_id=body.run_id,
        user_id=PLATFORM_USER_ID,
        lineage=script_lineage,
    )

    state_artifacts: dict[str, str] = {"script": script_record.r2_key}
    va_key = await _latest_artifact_key(storage, body.run_id, "voice", "voice_alignment")
    if va_key:
        state_artifacts["voice_alignment"] = va_key
        _logger.info("Voice alignment found for run %s — using Deepgram timestamps", body.run_id)

    worker = build_storyboard_worker(storage, settings.ANTHROPIC_API_KEY)
    state = StageState(
        run_id=body.run_id,
        user_id=PLATFORM_USER_ID,
        inputs={"format_track": body.format_track},
        artifacts=state_artifacts,
    )

    job_id = str(_uuid_mod.uuid4())
    await storage.put_json(
        f"runs/{body.run_id}/storyboard/current_job.json",
        {"job_id": job_id, "status": "running"},
    )
    background_tasks.add_task(_run_storyboard_background, body.run_id, job_id, state, worker, storage)
    _logger.info("StoryboardWorker background task enqueued for run %s job %s", body.run_id, job_id)
    return StoryboardWorkerResponse(status="accepted", run_id=body.run_id)


class MetadataWorkerRequest(BaseModel):
    """Request body for POST /platform/workers/metadata."""

    run_id: str


class MetadataWorkerResponse(BaseModel):
    """Response body for POST /platform/workers/metadata."""

    artifact_key: str
    title: str
    description: str
    tags: list[str]


@router.post("/workers/metadata", response_model=MetadataWorkerResponse)
async def metadata_worker_endpoint(
    body: MetadataWorkerRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> MetadataWorkerResponse:
    """Generate suggested YouTube title/description/tags from the run's script.

    Reuses the existing youtube_metadata worker (P7-S2), previously only invoked
    from the Telegram full_pipeline graph. Reads the latest script artifact for
    this run directly (Studio's step-by-step flow already has one from the
    Script stage) rather than the graph's `state.artifacts["script"]` handoff.
    """
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope
    from cf_platform.workers.youtube_metadata import (
        YOUTUBE_METADATA_REGISTRATION,
        YoutubeMetadataArtifact,
        build_youtube_metadata_worker,
    )

    script_key = await _latest_artifact_key(storage, body.run_id, "script", "script")
    if not script_key:
        raise HTTPException(
            status_code=404,
            detail=f"No script artifact for run_id={body.run_id!r}. Write a script first.",
        )

    worker = build_youtube_metadata_worker(storage, settings.ANTHROPIC_API_KEY)
    state = StageState(
        run_id=body.run_id,
        user_id=PLATFORM_USER_ID,
        inputs={},
        artifacts={"script": script_key},
    )
    output = await worker(state)
    result_artifact = output.artifact
    if not isinstance(result_artifact, YoutubeMetadataArtifact):
        raise HTTPException(status_code=500, detail="youtube_metadata worker returned unexpected artifact type")

    lineage = LineageEnvelope(
        run_id=body.run_id,
        worker="youtube_metadata",
        worker_version=YOUTUBE_METADATA_REGISTRATION.worker_version,
        prompt_version=YOUTUBE_METADATA_REGISTRATION.prompt_version,
        model=YOUTUBE_METADATA_REGISTRATION.model,
        created_at=datetime.now(),
    )
    record = await write_artifact(
        storage,
        result_artifact,
        name="youtube_metadata",
        stage="metadata",
        run_id=body.run_id,
        user_id=PLATFORM_USER_ID,
        lineage=lineage,
    )

    return MetadataWorkerResponse(
        artifact_key=record.r2_key,
        title=result_artifact.title,
        description=result_artifact.description,
        tags=result_artifact.tags,
    )


class VoiceWorkerRequest(BaseModel):
    """Request body for POST /platform/workers/voice."""

    run_id: str
    script: str


class VoiceWorkerResponse(BaseModel):
    """202 response body for POST /platform/workers/voice (accepted — runs async)."""

    status: str = "accepted"
    run_id: str


async def _run_voice_background(
    run_id: str,
    job_id: str,
    state: StageState,
    worker: Any,
    storage: ArtifactStorage,
) -> None:
    """Background task: runs TTS + alignment and updates voice/current_job.json."""
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope

    job_key = f"runs/{run_id}/voice/current_job.json"
    try:
        output = await worker(state)
        result = output.artifact
        if not isinstance(result, VoiceAlignmentArtifact):
            raise RuntimeError(f"VoiceProductionWorker returned unexpected type: {type(result)}")

        voice_lineage = LineageEnvelope(
            run_id=run_id,
            worker="voice_production",
            worker_version=VOICE_PRODUCTION_REGISTRATION.worker_version,
            prompt_version=VOICE_PRODUCTION_REGISTRATION.prompt_version,
            model=VOICE_PRODUCTION_REGISTRATION.model,
            created_at=datetime.now(),
        )
        await write_artifact(
            storage,
            result,
            name="voice_alignment",
            stage="voice",
            run_id=run_id,
            user_id=PLATFORM_USER_ID,
            lineage=voice_lineage,
        )
        await storage.put_json(job_key, {
            "job_id": job_id,
            "status": "complete",
            "alignment_method": result.alignment_method,
            "total_duration_s": result.total_duration_s,
            "word_count": len(result.word_timestamps),
        })
        _logger.info("VoiceWorker background task complete for run %s", run_id)
    except Exception as exc:
        _logger.exception("VoiceWorker background task failed for run %s: %s", run_id, exc)
        try:
            await storage.put_json(job_key, {"job_id": job_id, "status": "error", "error": str(exc)})
        except Exception:
            pass


@router.post("/workers/voice", response_model=VoiceWorkerResponse, status_code=202)
async def voice_worker_endpoint(
    body: VoiceWorkerRequest,
    background_tasks: BackgroundTasks,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> VoiceWorkerResponse:
    """Enqueue TTS + Deepgram alignment (returns 202 immediately).

    Writes the script artifact synchronously, then hands off TTS and alignment to
    a background task.  Poll GET /platform/studio/runs/{run_id}/voice/status for
    progress; fetch GET /platform/studio/runs/{run_id}/voice for the full artifact
    once complete.  This avoids Railway's HTTP timeout for long scripts.
    """
    import uuid as _uuid_mod

    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope

    script_artifact = ScriptArtifact(
        idea_title="",
        niche=None,
        script=body.script,
        word_count=len(body.script.split()),
        status="ok",
        generated_at=datetime.now(),
    )
    script_lineage = LineageEnvelope(
        run_id=body.run_id,
        worker="voice_request",
        worker_version="1.0.0",
        prompt_version="v1",
        model="none",
        created_at=datetime.now(),
    )
    script_record = await write_artifact(
        storage,
        script_artifact,
        name="script",
        stage="script",
        run_id=body.run_id,
        user_id=PLATFORM_USER_ID,
        lineage=script_lineage,
    )

    # Read the run's stored aspect ratio (set in Settings, before Voice runs) so
    # voice_production can apply a faster narration pace for 9:16 Shorts.
    aspect_ratio = "16:9"
    try:
        settings_data = await storage.get_json(f"runs/{body.run_id}/settings.json")
        aspect_ratio = settings_data.get("aspect_ratio", "16:9")
    except Exception:
        pass

    worker = build_voice_production_worker(
        storage,
        gemini_api_key=settings.GEMINI_API_KEY,
        gemini_tts_voice=settings.GEMINI_TTS_VOICE,
        deepgram_api_key=settings.DEEPGRAM_API_KEY,
    )
    worker_state = StageState(
        run_id=body.run_id,
        user_id=PLATFORM_USER_ID,
        inputs={"aspect_ratio": aspect_ratio},
        artifacts={"script": script_record.r2_key},
    )

    job_id = str(_uuid_mod.uuid4())
    await storage.put_json(
        f"runs/{body.run_id}/voice/current_job.json",
        {"job_id": job_id, "status": "running"},
    )
    background_tasks.add_task(_run_voice_background, body.run_id, job_id, worker_state, worker, storage)
    _logger.info("VoiceWorker background task enqueued for run %s job %s", body.run_id, job_id)
    return VoiceWorkerResponse(status="accepted", run_id=body.run_id)


class AcquisitionWorkerRequest(BaseModel):
    """Request body for POST /platform/workers/acquisition."""

    run_id: str


class AcquisitionWorkerResponse(BaseModel):
    """Response body for POST /platform/workers/acquisition."""

    manifest_key: str
    footage_summary: dict
    acquired: int
    failed: int


@router.post("/workers/acquisition", response_model=AcquisitionWorkerResponse)
async def acquisition_worker_endpoint(
    body: AcquisitionWorkerRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> AcquisitionWorkerResponse:
    """Acquire assets for all scenes in an existing verified storyboard.

    Reads the latest verified_storyboard artifact for run_id, routes each scene
    by segment_type (Character/Event/B-roll), runs the three-tier STK cascade with
    a QA gate, and persists the asset_manifest artifact to R2. The run must have a
    verified_storyboard artifact written by a prior /platform/workers/storyboard call.

    Designed for future step-by-step manual UI and standalone testing; not wired into
    Telegram in this story.
    """
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope

    # Locate the latest verified_storyboard artifact for this run
    prefix = f"users/{PLATFORM_USER_ID}/runs/{body.run_id}/storyboard/verified_storyboard@v"
    storyboard_keys = await storage.list_keys(prefix)
    if not storyboard_keys:
        raise HTTPException(
            status_code=404,
            detail=f"No verified_storyboard artifact found for run_id={body.run_id!r}. "
                   "Run /platform/workers/storyboard first.",
        )
    storyboard_key = sorted(storyboard_keys)[-1]  # latest version

    worker = build_acquisition_worker(
        storage,
        pexels_api_key=settings.PEXELS_API_KEY,
        pixabay_api_key=settings.PIXABAY_API_KEY,
    )
    state = StageState(
        run_id=body.run_id,
        user_id=PLATFORM_USER_ID,
        inputs={},
        artifacts={"verified_storyboard": storyboard_key},
    )
    output = await worker(state)
    result_artifact = output.artifact
    if not isinstance(result_artifact, AssetManifestArtifact):
        raise HTTPException(status_code=500, detail="AcquisitionWorker returned unexpected artifact type")

    manifest_lineage = LineageEnvelope(
        run_id=body.run_id,
        worker="acquisition_worker",
        worker_version=ACQUISITION_WORKER_REGISTRATION.worker_version,
        prompt_version=ACQUISITION_WORKER_REGISTRATION.prompt_version,
        model=ACQUISITION_WORKER_REGISTRATION.model,
        created_at=datetime.now(),
    )
    manifest_record = await write_artifact(
        storage,
        result_artifact,
        name="asset_manifest",
        stage="acquisition",
        run_id=body.run_id,
        user_id=PLATFORM_USER_ID,
        lineage=manifest_lineage,
    )

    return AcquisitionWorkerResponse(
        manifest_key=manifest_record.r2_key,
        footage_summary=result_artifact.footage_summary,
        acquired=result_artifact.acquired,
        failed=result_artifact.failed,
    )


class RenderWorkerRequest(BaseModel):
    """Request body for POST /platform/workers/render."""

    run_id: str
    format_track: str = "landscape"
    captions: bool = True
    music_enabled: bool = True


class RenderWorkerResponse(BaseModel):
    """Response body for POST /platform/workers/render (accepted — render runs async)."""

    status: str = "accepted"
    run_id: str


async def _run_render_background(
    run_id: str,
    job_id: str,
    state: StageState,
    worker: Any,
    storage: ArtifactStorage,
    settings: Any,
) -> None:
    """Background task: runs FFmpeg render and updates current_job.json in R2."""
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope

    job_key = f"runs/{run_id}/render/current_job.json"
    try:
        output = await worker(state)
        result_artifact = output.artifact
        if not isinstance(result_artifact, RenderArtifact):
            raise RuntimeError(f"RenderWorker returned unexpected artifact type: {type(result_artifact)}")

        render_lineage = LineageEnvelope(
            run_id=run_id,
            worker="render_worker",
            worker_version=RENDER_WORKER_REGISTRATION.worker_version,
            prompt_version=RENDER_WORKER_REGISTRATION.prompt_version,
            model=RENDER_WORKER_REGISTRATION.model,
            created_at=datetime.now(),
        )
        await write_artifact(
            storage,
            result_artifact,
            name="render_result",
            stage="render",
            run_id=run_id,
            user_id=PLATFORM_USER_ID,
            lineage=render_lineage,
        )
        await storage.put_json(job_key, {
            "job_id": job_id,
            "status": "complete",
            "video_key": result_artifact.video_key,
            "scene_count": result_artifact.scene_count,
            "duration_s": result_artifact.duration_s,
        })
        _logger.info("RenderWorker background task complete for run %s job %s", run_id, job_id)
    except Exception as exc:
        _logger.exception("RenderWorker background task failed for run %s: %s", run_id, exc)
        try:
            await storage.put_json(job_key, {"job_id": job_id, "status": "error", "error": str(exc)})
        except Exception:
            pass


@router.post("/workers/render", response_model=RenderWorkerResponse, status_code=202)
async def render_worker_endpoint(
    body: RenderWorkerRequest,
    background_tasks: BackgroundTasks,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> RenderWorkerResponse:
    """Enqueue an FFmpeg render for an acquired run (returns 202 immediately).

    The actual render runs as a background task — FFmpeg can take several minutes.
    Poll GET /platform/studio/runs/{run_id}/render/status for progress.
    """
    import uuid as _uuid_mod

    def _latest_key(keys: list[str]) -> str:
        return sorted(keys)[-1]

    sb_prefix = f"users/{PLATFORM_USER_ID}/runs/{body.run_id}/storyboard/verified_storyboard@v"
    sb_keys = await storage.list_keys(sb_prefix)
    if not sb_keys:
        raise HTTPException(
            status_code=404,
            detail=f"No verified_storyboard artifact for run_id={body.run_id!r}.",
        )

    mf_prefix = f"users/{PLATFORM_USER_ID}/runs/{body.run_id}/acquisition/asset_manifest@v"
    mf_keys = await storage.list_keys(mf_prefix)
    if not mf_keys:
        raise HTTPException(
            status_code=404,
            detail=f"No asset_manifest artifact for run_id={body.run_id!r}. "
                   "Run /platform/workers/acquisition first.",
        )

    artifacts: dict[str, str] = {
        "verified_storyboard": _latest_key(sb_keys),
        "asset_manifest": _latest_key(mf_keys),
    }

    va_prefix = f"users/{PLATFORM_USER_ID}/runs/{body.run_id}/voice/voice_alignment@v"
    va_keys = await storage.list_keys(va_prefix)
    if va_keys:
        artifacts["voice_alignment"] = _latest_key(va_keys)

    worker = build_render_worker(
        storage,
        color_grade_preset=settings.COLOR_GRADE_PRESET,
        blur_fill_enabled=settings.BLUR_FILL_ENABLED,
        ffmpeg_timeout_seconds=settings.FFMPEG_TIMEOUT_SECONDS,
    )
    state = StageState(
        run_id=body.run_id,
        user_id=PLATFORM_USER_ID,
        inputs={"format_track": body.format_track, "captions": body.captions, "music_enabled": body.music_enabled},
        artifacts=artifacts,
    )

    # Write job marker BEFORE enqueuing so the status endpoint knows a fresh render is running.
    # This prevents the old final.mp4 (from a previous killed render) from being returned
    # as "complete" before the new FFmpeg job finishes.
    job_id = str(_uuid_mod.uuid4())
    await storage.put_json(
        f"runs/{body.run_id}/render/current_job.json",
        {"job_id": job_id, "status": "running"},
    )

    background_tasks.add_task(_run_render_background, body.run_id, job_id, state, worker, storage, settings)
    _logger.info("RenderWorker background task enqueued for run %s job %s", body.run_id, job_id)
    return RenderWorkerResponse(status="accepted", run_id=body.run_id)
