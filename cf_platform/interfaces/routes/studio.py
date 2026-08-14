"""Studio UI routes — read/patch endpoints backing the Studio operator UI, plus
per-scene asset override endpoints (P10-S2) and music upload."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.trace_repo import TraceEventRepository
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_artifact_storage,
    get_trace_event_repository,
)
from cf_platform.interfaces.routes._helpers import latest_artifact_key as _latest_artifact_key

_logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/studio/runs/{run_id}/script")
async def studio_get_script(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return the latest script artifact body for a Studio run."""
    key = await _latest_artifact_key(storage, run_id, "script", "script")
    if not key:
        raise HTTPException(status_code=404, detail="No script artifact found for this run.")
    _, body = await read_artifact(storage, key)
    return body


@router.get("/studio/runs/{run_id}/metadata")
async def studio_get_metadata(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return the latest youtube_metadata artifact body for a Studio run."""
    key = await _latest_artifact_key(storage, run_id, "metadata", "youtube_metadata")
    if not key:
        raise HTTPException(status_code=404, detail="No metadata artifact found for this run.")
    _, body = await read_artifact(storage, key)
    return body


@router.get("/studio/runs/{run_id}/storyboard")
async def studio_get_storyboard(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return the latest verified_storyboard artifact body for a Studio run."""
    key = await _latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard")
    if not key:
        raise HTTPException(status_code=404, detail="No storyboard artifact found for this run.")
    _, body = await read_artifact(storage, key)
    return body


@router.get("/studio/runs/{run_id}/storyboard/status")
async def studio_get_storyboard_status(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Poll storyboard generation progress. Returns {status: running|complete|error}."""
    job_key = f"runs/{run_id}/storyboard/current_job.json"
    try:
        job = await storage.get_json(job_key)
        if job:
            if job.get("status") == "complete":
                return {
                    "status": "complete",
                    "scene_count": job.get("scene_count", 0),
                    "prompt_version": job.get("prompt_version", ""),
                }
            if job.get("status") == "error":
                return {"status": "error", "error": job.get("error", "Storyboard generation failed")}
    except Exception:
        pass
    return {"status": "running"}


@router.get("/studio/runs/{run_id}/manifest")
async def studio_get_manifest(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return the latest asset_manifest artifact body, enriched with 1-hour presigned URLs.

    Each manifest entry gains an asset_url field so the Studio UI can render
    preview links without a second round-trip per scene.
    """
    key = await _latest_artifact_key(storage, run_id, "acquisition", "asset_manifest")
    if not key:
        raise HTTPException(status_code=404, detail="No asset manifest found for this run.")
    _, body = await read_artifact(storage, key)
    for entry in body.get("manifest", {}).get("entries", []):
        file_key: str | None = entry.get("file_key")
        if file_key:
            try:
                entry["asset_url"] = await storage.generate_presigned_url(file_key, expires_in=3600)
            except Exception:
                entry["asset_url"] = None
    return body


@router.get("/studio/runs/{run_id}/voice")
async def studio_get_voice(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return the latest voice_alignment artifact for a Studio run, with a presigned audio URL."""
    key = await _latest_artifact_key(storage, run_id, "voice", "voice_alignment")
    if not key:
        raise HTTPException(status_code=404, detail="No voice artifact found for this run.")
    _, body = await read_artifact(storage, key)
    mp3_url: str | None = None
    mp3_r2_key: str = body.get("mp3_r2_key", "")
    if mp3_r2_key:
        try:
            mp3_url = await storage.generate_presigned_url(mp3_r2_key, expires_in=3600)
        except Exception:
            pass
    return {
        "artifact_key": key,
        "mp3_r2_key": mp3_r2_key,
        "mp3_url": mp3_url,
        "alignment_method": body.get("alignment_method", ""),
        "total_duration_s": body.get("total_duration_s", 0.0),
        "word_count": len(body.get("word_timestamps", [])),
    }


@router.get("/studio/runs/{run_id}/voice/status")
async def studio_get_voice_status(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Poll voice generation progress. Returns {status: running|complete|error}."""
    job_key = f"runs/{run_id}/voice/current_job.json"
    try:
        job = await storage.get_json(job_key)
        if job:
            if job.get("status") == "complete":
                return {
                    "status": "complete",
                    "alignment_method": job.get("alignment_method", ""),
                    "total_duration_s": job.get("total_duration_s", 0.0),
                    "word_count": job.get("word_count", 0),
                }
            if job.get("status") == "error":
                return {"status": "error", "error": job.get("error", "Voice generation failed")}
    except Exception:
        pass
    return {"status": "running"}


@router.get("/studio/runs/{run_id}/video")
async def studio_get_video_url(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return a 24-hour presigned URL for this run's final.mp4."""
    video_key = f"runs/{run_id}/output/final.mp4"
    try:
        url = await storage.generate_presigned_url(video_key, expires_in=86400)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Video not found for this run: {exc}")
    return {"video_url": url, "video_key": video_key}


@router.get("/studio/runs/{run_id}/render/status")
async def studio_get_render_status(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Poll render progress.  Returns {status: running|complete|error, video_url?, error?}.

    Uses current_job.json written by the render endpoint as the source of truth so that
    a stale final.mp4 from a previously-killed render is not mistaken for a completed job.
    """
    job_key = f"runs/{run_id}/render/current_job.json"
    try:
        job = await storage.get_json(job_key)
        if job:
            if job.get("status") == "complete":
                video_key = job.get("video_key", f"runs/{run_id}/output/final.mp4")
                try:
                    url = await storage.generate_presigned_url(video_key, expires_in=86400)
                except Exception:
                    url = None
                return {
                    "status": "complete",
                    "video_url": url,
                    "video_key": video_key,
                    "scene_count": job.get("scene_count"),
                    "duration_s": job.get("duration_s"),
                }
            if job.get("status") == "error":
                return {"status": "error", "error": job.get("error", "Render failed")}
            # status == "running"
            return {"status": "running"}
    except Exception:
        pass

    # Fallback for runs rendered before the background-task refactor
    video_key = f"runs/{run_id}/output/final.mp4"
    try:
        url = await storage.generate_presigned_url(video_key, expires_in=86400)
        return {"status": "complete", "video_url": url, "video_key": video_key}
    except Exception:
        pass

    return {"status": "running"}


class ScenePatchRequest(BaseModel):
    """Fields that can be patched on a single storyboard scene via the Studio UI."""

    on_screen_text: str | None = None
    on_screen_text_type: str | None = None
    primary_stk: str | None = None
    context_stk: str | None = None
    concept_stk: str | None = None
    clear_on_screen_text: bool = False


@router.patch("/studio/runs/{run_id}/storyboard/scenes/{scene_id}")
async def studio_patch_scene(
    run_id: str,
    scene_id: str,
    body: ScenePatchRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict:
    """Patch one scene's editable fields and write a new storyboard artifact version.

    Recomputes render_options for all scenes (cumulative timing must stay coherent)
    using the same _patch_storyboard logic as the StoryboardWorker's internal cycle.
    """
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope
    from cf_platform.workers.storyboard_worker import (
        VerifiedStoryboardArtifact,
        _apply_patches_and_render_options,
        _sanitize_storyboard_data,
    )
    from src.models import Storyboard

    key = await _latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard")
    if not key:
        raise HTTPException(status_code=404, detail="No storyboard found — run storyboard generation first.")

    _, artifact_body = await read_artifact(storage, key)
    storyboard = Storyboard.model_validate(_sanitize_storyboard_data(artifact_body["storyboard"]))

    patches: list[dict] = []
    if body.clear_on_screen_text:
        patches += [
            {"scene_id": scene_id, "field": "on_screen_text", "value": None},
            {"scene_id": scene_id, "field": "on_screen_text_type", "value": None},
        ]
    else:
        if body.on_screen_text is not None:
            patches.append({"scene_id": scene_id, "field": "on_screen_text", "value": body.on_screen_text})
        if body.on_screen_text_type is not None:
            patches.append({"scene_id": scene_id, "field": "on_screen_text_type", "value": body.on_screen_text_type})
    if body.primary_stk is not None:
        patches.append({"scene_id": scene_id, "field": "primary_stk", "value": body.primary_stk})
    if body.context_stk is not None:
        patches.append({"scene_id": scene_id, "field": "context_stk", "value": body.context_stk})
    if body.concept_stk is not None:
        patches.append({"scene_id": scene_id, "field": "concept_stk", "value": body.concept_stk})

    if not patches:
        raise HTTPException(status_code=400, detail="No patchable fields provided.")

    patched_storyboard = _apply_patches_and_render_options(storyboard, patches)

    new_artifact = VerifiedStoryboardArtifact(
        prompt_version=artifact_body.get("prompt_version", "patched"),
        scene_count=len(patched_storyboard.scenes),
        storyboard=patched_storyboard.model_dump(by_alias=True, mode="json"),
        generated_at=datetime.now(),
    )
    lineage = LineageEnvelope(
        run_id=run_id,
        worker="studio_patch",
        worker_version="1.0.0",
        prompt_version="manual",
        model="none",
        created_at=datetime.now(),
    )
    record = await write_artifact(
        storage, new_artifact,
        name="verified_storyboard", stage="storyboard",
        run_id=run_id, user_id=PLATFORM_USER_ID, lineage=lineage,
    )
    return {"artifact_key": record.r2_key, "scene_count": new_artifact.scene_count}


# ── Per-scene asset override endpoints (P10-S2) ───────────────────────────────


class SceneReacquireRequest(BaseModel):
    """Request body for POST /studio/runs/{run_id}/scenes/{scene_n}/reacquire."""

    query: str


@router.post("/studio/runs/{run_id}/scenes/{scene_n}/reacquire")
async def studio_reacquire_scene(
    run_id: str,
    scene_n: str,
    body: SceneReacquireRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
) -> dict:
    """Re-acquire a single scene's asset using a custom query.

    Reads the latest verified_storyboard and asset_manifest. Overrides the scene's
    primary_stk with the supplied query, re-runs acquisition for that one scene, writes
    a new asset_manifest artifact version, emits an operator_asset_override TraceEvent,
    and returns the updated entry with a 1-hour presigned preview URL.
    """
    import time

    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope, TraceEvent
    from cf_platform.workers.acquisition_worker import (
        ACQUISITION_WORKER_REGISTRATION,
        AssetManifestArtifact,
        _acquire_single_scene,
        _compute_footage_summary,
    )
    from cf_platform.workers.storyboard_worker import VerifiedStoryboardArtifact, _sanitize_storyboard_data
    from src.models import AssetManifest, ManifestEntry, Storyboard
    from src.pexels import PexelsClient
    from src.pixabay_client import PixabayClient
    from src.wikimedia_client import WikimediaClient

    if not body.query.strip():
        raise HTTPException(status_code=422, detail="query must not be empty")

    # Load storyboard
    sb_key = await _latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard")
    if not sb_key:
        raise HTTPException(status_code=404, detail="No storyboard found for this run.")
    _, sb_body = await read_artifact(storage, sb_key)
    sb_artifact = VerifiedStoryboardArtifact.model_validate(sb_body)
    storyboard = Storyboard.model_validate(_sanitize_storyboard_data(sb_artifact.storyboard))

    scene = next((s for s in storyboard.scenes if str(s.scene) == scene_n), None)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_n!r} not found in storyboard.")

    # Load manifest
    mf_key = await _latest_artifact_key(storage, run_id, "acquisition", "asset_manifest")
    if not mf_key:
        raise HTTPException(status_code=404, detail="No asset manifest found — run acquisition first.")
    _, mf_body = await read_artifact(storage, mf_key)
    manifest = AssetManifest.model_validate(mf_body["manifest"])

    entry = next((e for e in manifest.entries if str(e.scene_id) == scene_n), None)
    if entry is None:
        # Bootstrap a new entry if the manifest predates this scene
        entry = ManifestEntry(
            scene_id=scene.scene,
            clip_type=scene.clip_type,
            segment_type=scene.segment_type,
            primary_stk=body.query.strip(),
            context_stk=scene.context_stk,
            concept_stk=scene.concept_stk,
            person_name=scene.person_name,
            person_title=scene.person_title,
            duration_s=scene.duration_s,
            historic=scene.historic,
            asset_tier=scene.asset_tier,
        )
        manifest.entries.append(entry)

    original_query = entry.primary_stk
    entry.primary_stk = body.query.strip()

    pexels = PexelsClient(api_key=settings.PEXELS_API_KEY)
    pixabay: PixabayClient | None = PixabayClient(api_key=settings.PIXABAY_API_KEY) if settings.PIXABAY_API_KEY else None
    wikimedia = WikimediaClient()

    t0 = time.monotonic()
    await _acquire_single_scene(scene, entry, pexels, pixabay, wikimedia, storage, run_id)
    latency_ms = int((time.monotonic() - t0) * 1000)

    # Write new manifest artifact version
    footage_summary = _compute_footage_summary(manifest.entries)
    acquired = sum(1 for e in manifest.entries if e.status == "acquired")
    new_artifact = AssetManifestArtifact(
        scene_count=len(manifest.entries),
        acquired=acquired,
        failed=len(manifest.entries) - acquired,
        footage_summary=footage_summary,
        manifest=manifest.model_dump(mode="json"),
        generated_at=datetime.now(),
    )
    lineage = LineageEnvelope(
        run_id=run_id,
        worker="studio_reacquire",
        worker_version=ACQUISITION_WORKER_REGISTRATION.worker_version,
        prompt_version="manual",
        model="none",
        created_at=datetime.now(),
    )
    await write_artifact(
        storage, new_artifact,
        name="asset_manifest", stage="acquisition",
        run_id=run_id, user_id=PLATFORM_USER_ID, lineage=lineage,
    )

    # Emit operator override trace event. Best-effort: Studio run_ids are generated
    # client-side and never inserted into the Postgres `runs` table (Studio bypasses the
    # legacy block-execution path that's the only place PostgresRunRepository writes a
    # `runs` row), so this insert always trips trace_events' FK-on-run_id constraint for
    # a Studio run. That must never turn an already-successful manifest update into a
    # 500 for the operator — trace events are observability, not the deliverable.
    try:
        await trace_events.record(TraceEvent(
            run_id=run_id,
            worker="studio_reacquire",
            source="operator",
            op="operator_asset_override",
            latency_ms=latency_ms,
            status="ok" if entry.status == "acquired" else "error",
            meta={
                "scene_n": scene_n,
                "reason": "reacquire",
                "original_query": original_query,
                "override_query": body.query.strip(),
            },
        ))
    except Exception:
        _logger.warning("studio_reacquire: trace_events.record failed for run %s scene %s", run_id, scene_n, exc_info=True)

    preview_url: str | None = None
    if entry.file_key:
        try:
            preview_url = await storage.generate_presigned_url(entry.file_key, expires_in=3600)
        except Exception:
            pass

    return {
        "scene_n": scene_n,
        "file_key": entry.file_key,
        "source": entry.source,
        "qa_passed": entry.qa_passed,
        "preview_url": preview_url,
    }


@router.post("/studio/runs/{run_id}/scenes/{scene_n}/upload")
async def studio_upload_scene_asset(
    run_id: str,
    scene_n: str,
    file: UploadFile,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
) -> dict:
    """Upload an operator-supplied asset for a single scene.

    Validates MIME type and size (≤200 MB), stores to R2, patches the asset_manifest
    entry for this scene, writes a new manifest version, and emits an
    operator_asset_override TraceEvent. Returns the updated entry with a presigned URL.
    """
    import time

    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope, TraceEvent
    from cf_platform.workers.acquisition_worker import (
        ACQUISITION_WORKER_REGISTRATION,
        AssetManifestArtifact,
        _compute_footage_summary,
    )
    from src.models import AssetManifest

    _ALLOWED_MIME_TYPES = {
        "video/mp4", "video/webm",
        "image/jpeg", "image/png", "image/webp",
    }
    _MIME_TO_EXT = {
        "video/mp4": ".mp4", "video/webm": ".webm",
        "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    }
    _MAX_BYTES = 200 * 1024 * 1024  # 200 MB

    content_type = (file.content_type or "").split(";")[0].strip()
    if content_type not in _ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported file type: {content_type!r}. Allowed: mp4, webm, jpg, png, webp.")

    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=422, detail=f"File too large ({len(data) // (1024*1024)} MB). Maximum is 200 MB.")

    ext = _MIME_TO_EXT[content_type]
    is_video = content_type.startswith("video/")
    folder = "video" if is_video else "images"
    r2_key = f"runs/{run_id}/{folder}/scene_{scene_n.zfill(2)}_op{ext}"

    await storage.put_bytes(r2_key, data, content_type=content_type)

    # Load and patch manifest
    mf_key = await _latest_artifact_key(storage, run_id, "acquisition", "asset_manifest")
    if not mf_key:
        raise HTTPException(status_code=404, detail="No asset manifest found — run acquisition first.")
    _, mf_body = await read_artifact(storage, mf_key)
    manifest = AssetManifest.model_validate(mf_body["manifest"])

    entry = next((e for e in manifest.entries if str(e.scene_id) == scene_n), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_n!r} not found in manifest.")

    entry.file_key = r2_key
    entry.source = "operator_upload"
    entry.status = "acquired"
    entry.qa_passed = True
    entry.fallback_used = False

    footage_summary = _compute_footage_summary(manifest.entries)
    acquired = sum(1 for e in manifest.entries if e.status == "acquired")
    new_artifact = AssetManifestArtifact(
        scene_count=len(manifest.entries),
        acquired=acquired,
        failed=len(manifest.entries) - acquired,
        footage_summary=footage_summary,
        manifest=manifest.model_dump(mode="json"),
        generated_at=datetime.now(),
    )
    lineage = LineageEnvelope(
        run_id=run_id,
        worker="studio_upload",
        worker_version=ACQUISITION_WORKER_REGISTRATION.worker_version,
        prompt_version="manual",
        model="none",
        created_at=datetime.now(),
    )

    t0 = time.monotonic()
    await write_artifact(
        storage, new_artifact,
        name="asset_manifest", stage="acquisition",
        run_id=run_id, user_id=PLATFORM_USER_ID, lineage=lineage,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    # Best-effort: see the identical comment in studio_reacquire_scene above — Studio
    # run_ids are never inserted into Postgres `runs`, so this always trips trace_events'
    # FK constraint for a Studio run. Must not turn an already-successful upload into a
    # 500 for the operator.
    try:
        await trace_events.record(TraceEvent(
            run_id=run_id,
            worker="studio_upload",
            source="operator",
            op="operator_asset_override",
            latency_ms=latency_ms,
            status="ok",
            meta={"scene_n": scene_n, "reason": "upload", "r2_key": r2_key},
        ))
    except Exception:
        _logger.warning("studio_upload_scene_asset: trace_events.record failed for run %s scene %s", run_id, scene_n, exc_info=True)

    try:
        preview_url = await storage.generate_presigned_url(r2_key, expires_in=3600)
    except Exception:
        preview_url = None

    return {
        "scene_n": scene_n,
        "file_key": r2_key,
        "preview_url": preview_url,
    }


@router.post("/studio/runs/{run_id}/music")
async def studio_upload_music(
    run_id: str,
    file: UploadFile,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Upload background music for a run (Settings stage).

    Validates MIME type and size (≤50 MB), then stores at a fixed key
    (`runs/{run_id}/music/track{ext}`) so a re-upload of the same format
    overwrites the previous track — RenderWorker's `_copy_music_to_run`
    fallback only fires when no track is present. Uploading a different
    audio format after a prior upload leaves both files in place (both get
    mixed in by the render script); operators should stick to one format
    per run.
    """
    _ALLOWED_MIME_TYPES = {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4"}
    _MIME_TO_EXT = {
        "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mp4": ".m4a",
    }
    _MAX_BYTES = 50 * 1024 * 1024  # 50 MB

    content_type = (file.content_type or "").split(";")[0].strip()
    if content_type not in _ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported file type: {content_type!r}. Allowed: mp3, wav, m4a.")

    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=422, detail=f"File too large ({len(data) // (1024*1024)} MB). Maximum is 50 MB.")

    ext = _MIME_TO_EXT[content_type]
    r2_key = f"runs/{run_id}/music/track{ext}"
    await storage.put_bytes(r2_key, data, content_type=content_type)

    return {"run_id": run_id, "file_key": r2_key}
