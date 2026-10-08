"""Studio UI routes — read/patch endpoints backing the Studio operator UI, plus
per-scene asset override endpoints (P10-S2) and music upload."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.config import PlatformSettings
from cf_platform.core.trace_repo import TraceEventRepository
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_artifact_storage,
    get_effective_platform_settings,
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


def _with_effective_strategy(body: dict) -> dict:
    """Add effective_asset_strategy to every scene of a storyboard artifact body.

    The explicit asset_strategy when the operator set one, otherwise the strategy
    derived from asset_tier / clip_type — so the UI never re-derives it (P13-S1).
    """
    from src.models import effective_asset_strategy

    for scene in (body.get("storyboard") or {}).get("scenes", []):
        scene["effective_asset_strategy"] = effective_asset_strategy(
            scene.get("asset_strategy"), scene.get("asset_tier"), scene.get("clip_type") or ""
        )
    return body


@router.get("/studio/runs/{run_id}/storyboard")
async def studio_get_storyboard(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return the latest verified_storyboard artifact body for a Studio run.

    Every scene carries effective_asset_strategy (P13-S1).
    """
    key = await _latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard")
    if not key:
        raise HTTPException(status_code=404, detail="No storyboard artifact found for this run.")
    _, body = await read_artifact(storage, key)
    return _with_effective_strategy(body)


async def _load_storyboard(storage: ArtifactStorage, run_id: str):
    """Return (artifact_body, Storyboard) for a run's latest storyboard, or raise 404."""
    from cf_platform.workers.storyboard_worker import _sanitize_storyboard_data
    from src.models import Storyboard

    key = await _latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard")
    if not key:
        raise HTTPException(status_code=404, detail="No storyboard found — run storyboard generation first.")
    _, artifact_body = await read_artifact(storage, key)
    return artifact_body, Storyboard.model_validate(_sanitize_storyboard_data(artifact_body["storyboard"]))


async def _write_storyboard(storage: ArtifactStorage, run_id: str, artifact_body: dict, storyboard, worker: str):
    """Write a new verified_storyboard version; returns (r2_key, artifact body dict)."""
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope
    from cf_platform.workers.storyboard_worker import VerifiedStoryboardArtifact

    artifact = VerifiedStoryboardArtifact(
        prompt_version=artifact_body.get("prompt_version", "patched"),
        scene_count=len(storyboard.scenes),
        storyboard=storyboard.model_dump(by_alias=True, mode="json"),
        generated_at=datetime.now(),
    )
    record = await write_artifact(
        storage, artifact,
        name="verified_storyboard", stage="storyboard",
        run_id=run_id, user_id=PLATFORM_USER_ID,
        lineage=LineageEnvelope(
            run_id=run_id, worker=worker, worker_version="1.0.0",
            prompt_version="manual", model="none", created_at=datetime.now(),
        ),
    )
    return record.r2_key, artifact.model_dump(mode="json")


async def _apply_scene_edit_to_storyboard(
    storage: ArtifactStorage,
    run_id: str,
    scene_id: str,
    *,
    asset_strategy: str,
    ai_prompt: str | None,
    worker: str,
) -> str:
    """Give one scene an asset strategy (and AI prompt) and write a new storyboard version.

    The scene's asset_tier / clip_type / motion_effect follow the strategy
    (apply_asset_strategy) and render_options are recomputed, exactly as the
    PATCH route does. Returns the new artifact key.
    """
    from cf_platform.workers.storyboard_worker import (
        _apply_patches_and_render_options,
        apply_asset_strategy,
    )

    artifact_body, storyboard = await _load_storyboard(storage, run_id)
    scenes = [
        apply_asset_strategy(sc, asset_strategy).model_copy(update={"ai_prompt": ai_prompt})
        if str(sc.scene) == scene_id else sc
        for sc in storyboard.scenes
    ]
    patched = _apply_patches_and_render_options(storyboard.model_copy(update={"scenes": scenes}), [])
    key, _ = await _write_storyboard(storage, run_id, artifact_body, patched, worker)
    return key


async def _load_manifest(storage: ArtifactStorage, run_id: str):
    """Return the run's latest AssetManifest, or None when there is none to work with.

    None covers: no manifest yet, the emptied manifest left behind when a
    storyboard is regenerated, and a manifest with no entries.
    """
    from src.models import AssetManifest

    key = await _latest_artifact_key(storage, run_id, "acquisition", "asset_manifest")
    if not key:
        return None
    _, body = await read_artifact(storage, key)
    raw = body.get("manifest")
    if not raw or not raw.get("entries"):
        return None
    return AssetManifest.model_validate(raw)


async def _write_manifest(storage: ArtifactStorage, run_id: str, manifest, worker: str) -> str:
    """Write a new asset_manifest version; returns its r2_key."""
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope
    from cf_platform.workers.acquisition_worker import (
        ACQUISITION_WORKER_REGISTRATION,
        build_manifest_artifact,
    )

    record = await write_artifact(
        storage, build_manifest_artifact(manifest, datetime.now()),
        name="asset_manifest", stage="acquisition",
        run_id=run_id, user_id=PLATFORM_USER_ID,
        lineage=LineageEnvelope(
            run_id=run_id, worker=worker,
            worker_version=ACQUISITION_WORKER_REGISTRATION.worker_version,
            prompt_version="manual", model="none", created_at=datetime.now(),
        ),
    )
    return record.r2_key


async def _load_words(storage: ArtifactStorage, run_id: str) -> list:
    """Return the run's voiceover words, normalised exactly as the StoryboardWorker does.

    Scene start_word / end_word index into this list (P9-S9). Raises 409 when the
    run has no voice alignment — boundaries cannot be recomputed without it.
    """
    from cf_platform.workers.storyboard_worker import _normalize_deepgram_words
    from cf_platform.workers.voice_production import VoiceAlignmentArtifact

    key = await _latest_artifact_key(storage, run_id, "voice", "voice_alignment")
    if not key:
        raise HTTPException(
            status_code=409,
            detail="No voiceover for this run — scene boundaries need the voice word timestamps.",
        )
    _, body = await read_artifact(storage, key)
    alignment = VoiceAlignmentArtifact.model_validate(body)
    return _normalize_deepgram_words([w.model_dump() for w in alignment.word_timestamps])


@router.get("/studio/sfx-library")
async def studio_get_sfx_library(
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> list[dict]:
    """Curated SFX options for the storyboard SFX picker (D076).

    Only returns keys that are both in the curated manifest
    (cf_platform.core.sfx_library.SFX_LIBRARY) AND have a backing file in
    sfx-library/ in R2 — so the picker never offers a choice with no audio.
    """
    from cf_platform.workers.render_worker import list_available_sfx

    return await list_available_sfx(storage)


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
                    "language_warning": job.get("language_warning"),
                }
            if job.get("status") == "error":
                return {"status": "error", "error": job.get("error", "Voice generation failed")}
    except Exception:
        pass
    return {"status": "running"}


@router.get("/studio/runs/{run_id}/timeline")
async def studio_get_timeline(
    run_id: str,
    format_track: str = "landscape",
    captions: bool = True,
    caption_style: str = "standard",
    music_enabled: bool = True,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return the run's Timeline (P13b-S1): scenes with resolved timing, assets, text, captions, audio.

    Built fresh from the latest artifacts and not stored — a render or an export
    stores it. 404 without a storyboard or manifest; 409 with the missing-assets
    message while any scene has no file.
    """
    if format_track not in ("portrait", "landscape"):
        raise HTTPException(status_code=422, detail="format_track must be 'portrait' or 'landscape'.")
    if caption_style not in ("standard", "punch"):
        raise HTTPException(status_code=422, detail="caption_style must be 'standard' or 'punch'.")
    from cf_platform.interfaces.routes._helpers import prepare_run_timeline

    timeline, _ = await prepare_run_timeline(
        storage, run_id, format_track=format_track, captions=captions,
        caption_style=caption_style, music_enabled=music_enabled,
    )
    return timeline.model_dump(mode="json")


@router.get("/studio/runs/{run_id}/export/capcut")
async def studio_export_capcut(
    run_id: str,
    format_track: str = "portrait",
    captions: bool = True,
    caption_style: str = "standard",
    music_enabled: bool = True,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
):
    """Stream a zip of the run's timeline and media for the CapCut path (P13b-S2, D100).

    timeline.json plus every file it references, under the relative paths it uses.
    Stores the timeline as a run artifact. 409 while any scene has no file or when
    the run has no voice alignment.
    """
    import time

    from fastapi.responses import StreamingResponse

    from cf_platform.core.schemas import TraceEvent
    from cf_platform.interfaces.routes._helpers import prepare_run_timeline
    from cf_platform.workers.capcut_export import iter_export_zip

    if format_track not in ("portrait", "landscape"):
        raise HTTPException(status_code=422, detail="format_track must be 'portrait' or 'landscape'.")
    if caption_style not in ("standard", "punch"):
        raise HTTPException(status_code=422, detail="caption_style must be 'standard' or 'punch'.")

    t0 = time.monotonic()
    timeline, timeline_key = await prepare_run_timeline(
        storage, run_id, format_track=format_track, captions=captions,
        caption_style=caption_style, music_enabled=music_enabled,
        copy_media=True, write=True, require_alignment=True, existing_media_only=True,
    )
    # Best-effort, like the other Studio trace events: an observability write must never
    # fail the export (Studio runs may have no `runs` row for the FK).
    try:
        await trace_events.record(TraceEvent(
            run_id=run_id, worker="studio_export", source="operator", op="capcut_export",
            latency_ms=int((time.monotonic() - t0) * 1000), status="ok",
            meta={
                "timeline_key": timeline_key, "scenes": len(timeline.scenes),
                "files": len(timeline.referenced_paths()), "format_track": format_track,
            },
        ))
    except Exception:
        _logger.warning("studio_export_capcut: trace_events.record failed for run %s", run_id, exc_info=True)

    return StreamingResponse(
        iter_export_zip(storage, timeline),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="capcut_{run_id[:8]}.zip"'},
    )


_MP4_MIME_TYPES = {"video/mp4"}


@router.post("/studio/runs/{run_id}/output/upload")
async def studio_upload_output(
    run_id: str,
    file: UploadFile,
    confirm_overwrite: bool = False,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_effective_platform_settings),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
) -> dict:
    """Store the video the operator rendered in CapCut as the run's final video (P13b-S4, D100).

    Validates the type (an .mp4, MIME video/mp4, MP4 container) and size
    (OUTPUT_UPLOAD_MAX_MB), then writes runs/{run_id}/output/final.mp4 — the key every
    reader uses — and records that this video came from CapCut. An existing FFmpeg
    render, or a render still marked running, is replaced only with
    confirm_overwrite=true (409 otherwise).
    """
    import time

    from cf_platform.core.final_video import (
        final_video_key,
        final_video_state,
        record_final_source,
    )
    from cf_platform.core.schemas import TraceEvent

    t0 = time.monotonic()
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _MP4_MIME_TYPES or not (file.filename or "").lower().endswith(".mp4"):
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file: {file.filename!r} ({content_type or 'no type'}). Upload an .mp4 video.",
        )

    max_bytes = settings.OUTPUT_UPLOAD_MAX_MB * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(
                status_code=422,
                detail=f"File too large. Maximum is {settings.OUTPUT_UPLOAD_MAX_MB} MB.",
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    del chunks
    if len(data) < 12 or data[4:8] != b"ftyp":
        raise HTTPException(status_code=422, detail="That file is not an MP4 video.")

    if not confirm_overwrite:
        existing = await final_video_state(storage, run_id)
        job = None
        try:
            job = await storage.get_json(f"runs/{run_id}/render/current_job.json")
        except Exception:
            job = None
        if job and job.get("status") == "running":
            raise HTTPException(
                status_code=409,
                detail="A render is marked as running for this run. Uploading now means its result will "
                       "replace this video when it finishes — confirm to upload anyway.",
            )
        if existing["exists"] and existing["source"] == "ffmpeg":
            raise HTTPException(
                status_code=409,
                detail="This run already has an FFmpeg render. Uploading replaces it — confirm to continue.",
            )

    await storage.put_bytes(final_video_key(run_id), data, content_type="video/mp4")
    record = await record_final_source(storage, run_id, "capcut", filename=file.filename, size_bytes=len(data))
    # The render status endpoint reads current_job.json, so a finished upload reads
    # as a finished job — and replaces any stale "running" marker.
    await storage.put_json(f"runs/{run_id}/render/current_job.json", {
        "job_id": "capcut-upload", "status": "complete", "video_key": final_video_key(run_id),
        "source": "capcut", "completed_at": record["at"],
    })

    # Best-effort observability, as for the other Studio operator actions.
    try:
        await trace_events.record(TraceEvent(
            run_id=run_id, worker="studio_output_upload", source="operator", op="capcut_video_upload",
            latency_ms=int((time.monotonic() - t0) * 1000), status="ok",
            meta={"filename": file.filename, "size_bytes": len(data), "replaced_confirmed": confirm_overwrite},
        ))
    except Exception:
        _logger.warning("studio_upload_output: trace_events.record failed for run %s", run_id, exc_info=True)

    try:
        url = await storage.generate_presigned_url(final_video_key(run_id), expires_in=86400)
    except Exception:
        url = None
    return {
        "run_id": run_id, "video_key": final_video_key(run_id), "video_url": url,
        "source": "capcut", "source_at": record["at"], "size_bytes": len(data),
    }


@router.get("/studio/runs/{run_id}/video")
async def studio_get_video_url(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return a 24-hour presigned URL for this run's final.mp4."""
    from cf_platform.core.final_video import final_video_state

    video_key = f"runs/{run_id}/output/final.mp4"
    try:
        url = await storage.generate_presigned_url(video_key, expires_in=86400)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Video not found for this run: {exc}")
    state = await final_video_state(storage, run_id)
    return {"video_url": url, "video_key": video_key, "source": state["source"], "source_at": state["at"]}


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
                    "source": job.get("source", "ffmpeg"),
                    "source_at": job.get("completed_at"),
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
        return {"status": "complete", "video_url": url, "video_key": video_key, "source": "ffmpeg", "source_at": None}
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
    sfx: str | None = None
    motion_effect: str | None = None
    asset_strategy: str | None = None
    ai_prompt: str | None = None
    clear_on_screen_text: bool = False


@router.patch("/studio/runs/{run_id}/storyboard/scenes/{scene_id}")
async def studio_patch_scene(
    run_id: str,
    scene_id: str,
    body: ScenePatchRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_effective_platform_settings),
) -> dict:
    """Patch one scene's editable fields and write a new storyboard artifact version.

    Recomputes render_options for all scenes (cumulative timing must stay coherent)
    using the same _patch_storyboard logic as the StoryboardWorker's internal cycle.

    motion_effect (D081): validated against src.models.MOTION_EFFECTS; unknown values
    are rejected with 422 rather than silently dropped by _PATCHABLE_FIELDS. Affects
    render only — no re-acquisition is needed after changing it.

    sfx (D076): an empty string is normalised to "silence". No copy-into-run side
    effect happens here — that's handled once, in bulk, at render time by
    render_worker._copy_all_scene_sfx_to_run, which covers both an AI-suggested
    SFX the operator never touched and one picked here.

    asset_strategy (D095, P13-S1): validated against src.models.ASSET_STRATEGIES,
    422 otherwise. The scene's asset_tier / clip_type / motion_effect follow the
    strategy (apply_asset_strategy). When the run already has a manifest, an asset
    of the wrong kind is released so the scene is acquired again; the response
    lists the scenes that now need one in needs_acquisition.
    """
    from cf_platform.workers.storyboard_worker import (
        _apply_patches_and_render_options,
        apply_asset_strategy,
    )
    from src.models import ASSET_STRATEGIES, MOTION_EFFECTS

    artifact_body, storyboard = await _load_storyboard(storage, run_id)

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
    if body.sfx is not None:
        patches.append({"scene_id": scene_id, "field": "sfx", "value": body.sfx or "silence"})
    if body.ai_prompt is not None:
        patches.append({"scene_id": scene_id, "field": "ai_prompt", "value": body.ai_prompt.strip() or None})
    if body.motion_effect is not None:
        if body.motion_effect not in MOTION_EFFECTS:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown motion_effect {body.motion_effect!r} — expected one of {list(MOTION_EFFECTS)}",
            )
        patches.append({"scene_id": scene_id, "field": "motion_effect", "value": body.motion_effect})
    if body.asset_strategy is not None:
        if body.asset_strategy not in ASSET_STRATEGIES:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown asset_strategy {body.asset_strategy!r} — expected one of {list(ASSET_STRATEGIES)}",
            )
        # Realign tier / clip type / motion with the strategy before the field
        # patches run, so an explicit motion_effect in the same request still wins.
        storyboard = storyboard.model_copy(update={"scenes": [
            apply_asset_strategy(sc, body.asset_strategy) if str(sc.scene) == scene_id else sc
            for sc in storyboard.scenes
        ]})
        patches.append({"scene_id": scene_id, "field": "asset_strategy", "value": body.asset_strategy})

    if not patches:
        raise HTTPException(status_code=400, detail="No patchable fields provided.")

    patched_storyboard = _apply_patches_and_render_options(storyboard, patches)
    artifact_key, _ = await _write_storyboard(storage, run_id, artifact_body, patched_storyboard, "studio_patch")
    response: dict = {"artifact_key": artifact_key, "scene_count": len(patched_storyboard.scenes)}

    if body.asset_strategy is not None:
        scene = next((sc for sc in patched_storyboard.scenes if str(sc.scene) == scene_id), None)
        manifest = await _load_manifest(storage, run_id)
        if scene is not None and manifest is not None:
            if _sync_entry_with_strategy(manifest, scene):
                response["manifest_key"] = await _write_manifest(storage, run_id, manifest, "studio_patch")
            response["needs_acquisition"] = [
                e.scene_id for e in manifest.entries if not (e.status == "acquired" and e.file_key)
            ]
    return response


def _sync_entry_with_strategy(manifest, scene) -> bool:
    """Bring one manifest entry in line with its scene's new asset strategy.

    Returns True when the entry changed. An asset that no longer fits is released,
    so the scene shows as needing one and the next acquisition fetches it:
    a still on a stock_video scene (or the reverse), a stock asset on an upload
    scene, an operator upload on a stock scene. An asset that already fits stays.
    """
    from cf_platform.workers.storyboard_edit import _is_video_file
    from src.models import (
        AI_GENERATED_SOURCE,
        AWAITING_UPLOAD_STATUS,
        OPERATOR_SOURCES,
        OPERATOR_UPLOAD_SOURCE,
    )

    entry = next((e for e in manifest.entries if str(e.scene_id) == str(scene.scene)), None)
    if entry is None:
        return False
    before = entry.model_dump()

    entry.asset_strategy = scene.asset_strategy
    entry.ai_prompt = scene.ai_prompt
    entry.asset_tier = scene.asset_tier
    entry.clip_type = scene.clip_type

    has_file = entry.status == "acquired" and bool(entry.file_key)
    uploaded = entry.source in OPERATOR_SOURCES
    if scene.asset_strategy == "upload":
        fits = has_file and entry.source == OPERATOR_UPLOAD_SOURCE
        empty_status = AWAITING_UPLOAD_STATUS
    elif scene.asset_strategy == "ai_image":
        fits = has_file and entry.source == AI_GENERATED_SOURCE
        empty_status = AWAITING_UPLOAD_STATUS
    else:
        wants_video = scene.asset_strategy == "stock_video"
        fits = has_file and not uploaded and _is_video_file(entry.file_key) == wants_video
        empty_status = "pending"
    if not fits:
        entry.status = empty_status
        entry.file_key = None
        entry.source = None
        entry.attribution = None
        entry.qa_passed = entry.qa_resolution_ok = entry.qa_duration_ok = entry.qa_clip_score = None
        entry.fallback_used = False
    return entry.model_dump() != before


# ── Scene boundary edits (P13-S2, P13-S4) ─────────────────────────────────────


class SceneSplitRequest(BaseModel):
    """Request body for POST …/storyboard/scenes/{scene_id}/split."""

    # Index of the word that becomes the first word of the new second scene.
    at_word: int


class BoundariesRequest(BaseModel):
    """Request body for PUT …/storyboard/boundaries.

    Give either start_words (the first word index of every scene) or script_text
    (the voiceover with one paragraph per scene — the Script view). dry_run
    reports what would change without writing anything.
    """

    start_words: list[int] | None = None
    script_text: str | None = None
    dry_run: bool = False


def _boundary_summary(edit) -> str:
    """One operator-facing sentence describing a boundary edit."""
    parts = [f"{edit.scenes_before} scenes → {edit.scenes_after}"]
    if edit.manifest is not None:
        n = len(edit.needs_acquisition)
        parts.append(f"{n} scene{'' if n == 1 else 's'} need{'s' if n == 1 else ''} acquisition")
    if edit.dropped:
        parts.append(
            "on-screen text / SFX dropped from merged scene(s) "
            + ", ".join(d["scene"] for d in edit.dropped)
        )
    return "; ".join(parts)


async def _run_boundary_edit(storage: ArtifactStorage, run_id: str, worker: str, edit_fn, dry_run: bool = False) -> dict:
    """Load a run's storyboard, words and manifest, apply one boundary edit, persist it.

    edit_fn(storyboard, words, manifest) returns a storyboard_edit.BoundaryEdit.
    Writes a new storyboard version and, when the run has a manifest, a new
    manifest version aligned with the renumbered scenes. A rejected edit is a 422
    (409 for merging the last scene, 404 for an unknown scene) and writes nothing.
    """
    from cf_platform.workers.storyboard_edit import LastSceneMergeError, StoryboardEditError

    artifact_body, storyboard = await _load_storyboard(storage, run_id)
    words = await _load_words(storage, run_id)
    manifest = await _load_manifest(storage, run_id)

    try:
        edit = edit_fn(storyboard, words, manifest)
    except LastSceneMergeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StoryboardEditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Scene {exc.args[0]!r} not found in storyboard.") from exc

    response: dict = {
        "scenes_before": edit.scenes_before,
        "scene_count": edit.scenes_after,
        "dropped": edit.dropped,
        "needs_acquisition": edit.needs_acquisition if edit.manifest is not None else None,
        "summary": _boundary_summary(edit),
        "dry_run": dry_run,
    }
    if dry_run:
        return response

    artifact_key, new_body = await _write_storyboard(storage, run_id, artifact_body, edit.storyboard, worker)
    response["artifact_key"] = artifact_key
    if edit.manifest is not None:
        response["manifest_key"] = await _write_manifest(storage, run_id, edit.manifest, worker)
    response.update(_with_effective_strategy(new_body))
    return response


@router.post("/studio/runs/{run_id}/storyboard/scenes/{scene_id}/split")
async def studio_split_scene(
    run_id: str,
    scene_id: str,
    body: SceneSplitRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_effective_platform_settings),
) -> dict:
    """Split a scene in two at a word (P13-S2).

    at_word becomes the first word of the new second scene; 422 unless
    start_word < at_word <= end_word, or when either half would be shorter than
    STORYBOARD_MIN_SCENE_S. The first half keeps every field and its asset; the
    second copies the visual fields, has no on-screen text or SFX, and needs an
    asset. Returns the new storyboard so the table can re-render from it.
    """
    from cf_platform.workers.storyboard_edit import split_scene

    return await _run_boundary_edit(
        storage, run_id, "studio_split",
        lambda sb, words, manifest: split_scene(
            sb, words, scene_id, body.at_word, manifest, settings.STORYBOARD_MIN_SCENE_S
        ),
    )


@router.post("/studio/runs/{run_id}/storyboard/scenes/{scene_id}/merge")
async def studio_merge_scene(
    run_id: str,
    scene_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_effective_platform_settings),
) -> dict:
    """Merge a scene with the one after it (P13-S2); 409 on the last scene.

    The first scene's fields and asset win. The second scene's on-screen text and
    SFX are dropped and listed in the response's `dropped`.
    """
    from cf_platform.workers.storyboard_edit import merge_scene

    return await _run_boundary_edit(
        storage, run_id, "studio_merge",
        lambda sb, words, manifest: merge_scene(
            sb, words, scene_id, manifest, settings.STORYBOARD_MIN_SCENE_S
        ),
    )


@router.put("/studio/runs/{run_id}/storyboard/boundaries")
async def studio_replace_boundaries(
    run_id: str,
    body: BoundariesRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_effective_platform_settings),
) -> dict:
    """Replace all scene boundaries at once (P13-S4, the Script view).

    Validated: starts at word 0, strictly increasing, within the voiceover, and no
    new scene shorter than STORYBOARD_MIN_SCENE_S. With script_text the words must
    equal the voiceover's — only paragraph breaks may differ; otherwise 422, and
    the wording has to be changed in the Script stage (it forces re-voicing).
    A scene whose start word is unchanged keeps its fields and asset.
    """
    from cf_platform.workers.storyboard_edit import replace_boundaries, start_words_from_text

    if (body.start_words is None) == (body.script_text is None):
        raise HTTPException(status_code=422, detail="Provide exactly one of start_words or script_text.")

    def _edit(sb, words, manifest):
        """Resolve the requested boundaries and apply them."""
        starts = body.start_words if body.start_words is not None else start_words_from_text(words, body.script_text or "")
        return replace_boundaries(sb, words, starts, manifest, settings.STORYBOARD_MIN_SCENE_S)

    return await _run_boundary_edit(storage, run_id, "studio_boundaries", _edit, dry_run=body.dry_run)


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
    settings: PlatformSettings = Depends(get_effective_platform_settings),
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
        _acquire_single_scene,
        asset_file_stem,
        assign_free_asset_slot,
        build_manifest_artifact,
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
    # Scene ids are renumbered by split / merge (P13-S2), so this scene's default
    # file name may belong to another scene's kept asset.
    assign_free_asset_slot(
        entry,
        {stem for e in manifest.entries if e is not entry and (stem := asset_file_stem(e.file_key))},
        scene.start_word,
    )

    pexels = PexelsClient(api_key=settings.PEXELS_API_KEY)
    pixabay: PixabayClient | None = PixabayClient(api_key=settings.PIXABAY_API_KEY) if settings.PIXABAY_API_KEY else None
    wikimedia = WikimediaClient()

    t0 = time.monotonic()
    await _acquire_single_scene(scene, entry, pexels, pixabay, wikimedia, storage, run_id)
    latency_ms = int((time.monotonic() - t0) * 1000)

    # Write new manifest artifact version
    new_artifact = build_manifest_artifact(manifest, datetime.now())
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


async def _rederive_scene_media_contract(
    storage: ArtifactStorage,
    run_id: str,
    scene_n: str,
    *,
    is_video: bool,
) -> str | None:
    """Realign one storyboard scene's asset_tier/clip_type/motion_effect with its asset.

    Called after an operator supplies a scene's asset by hand, because the three
    fields were derived from scene *duration* at storyboard time and the operator
    has just overruled that guess (D089).  Returns the new artifact key, or None
    when the scene already described the uploaded media kind — an unchanged
    storyboard must not burn a version, since every reader resolves "latest" and
    the history is the operator's audit trail.

    Raises 404 if the run has no storyboard or no such scene: both mean the caller
    patched a manifest entry that nothing downstream can render.
    """
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope
    from cf_platform.workers.storyboard_worker import (
        VerifiedStoryboardArtifact,
        _apply_patches_and_render_options,
        _sanitize_storyboard_data,
        rederive_scene_visual_contract,
    )
    from src.models import Storyboard

    key = await _latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard")
    if not key:
        raise HTTPException(status_code=404, detail="No storyboard found — run storyboard generation first.")

    _, artifact_body = await read_artifact(storage, key)
    storyboard = Storyboard.model_validate(_sanitize_storyboard_data(artifact_body["storyboard"]))

    target = next((sc for sc in storyboard.scenes if str(sc.scene) == scene_n), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_n!r} not found in storyboard.")

    tier, clip_type, motion_effect = rederive_scene_visual_contract(
        target.duration_s, is_video, target.motion_effect
    )
    if (target.asset_tier, target.clip_type, target.motion_effect) == (tier, clip_type, motion_effect):
        return None

    _logger.info(
        "studio_upload: scene %s of run %s re-derived %s/%s/%s → %s/%s/%s (is_video=%s)",
        scene_n, run_id,
        target.asset_tier, target.clip_type, target.motion_effect,
        tier, clip_type, motion_effect, is_video,
    )

    updated = target.model_copy(update={
        "asset_tier": tier, "clip_type": clip_type, "motion_effect": motion_effect,
    })
    scenes = [updated if sc is target else sc for sc in storyboard.scenes]
    # Empty patch list: the scene is already replaced above — this call is here to
    # recompute render_options, which the patch endpoint also relies on to keep the
    # cumulative on-screen-text enable_expr offsets coherent.
    patched = _apply_patches_and_render_options(
        storyboard.model_copy(update={"scenes": scenes}), []
    )

    record = await write_artifact(
        storage,
        VerifiedStoryboardArtifact(
            prompt_version=artifact_body.get("prompt_version", "patched"),
            scene_count=len(patched.scenes),
            storyboard=patched.model_dump(by_alias=True, mode="json"),
            generated_at=datetime.now(),
        ),
        name="verified_storyboard", stage="storyboard",
        run_id=run_id, user_id=PLATFORM_USER_ID,
        lineage=LineageEnvelope(
            run_id=run_id,
            worker="studio_upload",
            worker_version="1.0.0",
            prompt_version="manual",
            model="none",
            created_at=datetime.now(),
        ),
    )
    return record.r2_key


@router.post("/studio/runs/{run_id}/scenes/{scene_n}/upload")
async def studio_upload_scene_asset(
    run_id: str,
    scene_n: str,
    file: UploadFile,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_effective_platform_settings),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
) -> dict:
    """Upload an operator-supplied asset for a single scene.

    Validates MIME type and size (≤200 MB), stores to R2, patches the asset_manifest
    entry for this scene (starting a manifest from the storyboard when the run has
    none yet — P13-S3), writes a new manifest version, re-derives the storyboard
    scene's visual contract from the uploaded media kind, and emits an
    operator_asset_override TraceEvent. Returns the updated entry with a presigned URL.

    The storyboard write is what keeps asset_tier / clip_type / motion_effect
    describing the file that is actually on disk (D089).  Those three are derived
    once, from scene duration, at storyboard time; without this step an uploaded
    MP4 leaves a short scene still labelled a still, so Studio keeps offering it a
    motion dropdown and the renderer keeps treating it as an image.
    """
    import hashlib
    import time

    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope, TraceEvent
    from cf_platform.workers.acquisition_worker import (
        ACQUISITION_WORKER_REGISTRATION,
        build_manifest_artifact,
        manifest_entry_for_scene,
    )
    from src.models import AWAITING_UPLOAD_STATUS, OPERATOR_SUPPLIED_STRATEGIES, AssetManifest

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

    # Load the manifest. Before the first acquisition there is none: an "upload"
    # scene is filled at the storyboard gate (P13-S3), so start one from the
    # storyboard with every other scene still to be acquired.
    manifest = await _load_manifest(storage, run_id)
    if manifest is None:
        try:
            _, storyboard = await _load_storyboard(storage, run_id)
        except HTTPException:
            raise HTTPException(
                status_code=404, detail="No asset manifest found — run acquisition first."
            ) from None
        entries = [manifest_entry_for_scene(sc) for sc in storyboard.scenes]
        for e in entries:
            if e.asset_strategy in OPERATOR_SUPPLIED_STRATEGIES:
                e.status = AWAITING_UPLOAD_STATUS
        manifest = AssetManifest(run_id=run_id, entries=entries)

    entry = next((e for e in manifest.entries if str(e.scene_id) == scene_n), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_n!r} not found in manifest.")

    # Scene ids are renumbered by split / merge (P13-S2): another scene may still
    # be using this file name for its own upload. Never write over it.
    if any(e is not entry and e.file_key == r2_key for e in manifest.entries):
        digest = hashlib.sha1(data).hexdigest()[:8]
        r2_key = f"runs/{run_id}/{folder}/scene_{scene_n.zfill(2)}_op_{digest}{ext}"

    await storage.put_bytes(r2_key, data, content_type=content_type)

    entry.file_key = r2_key
    entry.source = "operator_upload"
    entry.status = "acquired"
    entry.qa_passed = True
    entry.fallback_used = False

    new_artifact = build_manifest_artifact(manifest, datetime.now())
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

    # Re-derive the storyboard scene's visual contract from what was actually
    # uploaded.  Deliberately NOT best-effort: leaving the storyboard describing a
    # still while an MP4 sits in the manifest is the exact inconsistency this
    # endpoint used to create, so a failure here must surface rather than hide.
    await _rederive_scene_media_contract(storage, run_id, scene_n, is_video=is_video)

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
