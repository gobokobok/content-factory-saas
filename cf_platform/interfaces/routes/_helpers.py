"""Small helpers shared by multiple route modules (not a route module itself)."""

from cf_platform.core.artifact_manager import ArtifactStorage, latest_version_key
from cf_platform.interfaces.dependencies import PLATFORM_USER_ID

DISCARDED_STORYBOARD_MARKER = "runs/{run_id}/storyboard/discarded.json"


async def latest_artifact_key(storage: ArtifactStorage, run_id: str, stage: str, name: str) -> str | None:
    """Return the R2 key for the latest version of an artifact, or None if absent.

    Resolution is numeric, not lexicographic — see artifact_manager.latest_version_key.
    A storyboard the operator discarded by re-uploading the voiceover (P14b-S4) counts
    as absent until a newer version is generated.
    """
    prefix = f"users/{PLATFORM_USER_ID}/runs/{run_id}/{stage}/{name}@v"
    keys = await storage.list_keys(prefix)
    key = latest_version_key(keys)
    if key and stage == "storyboard" and name == "verified_storyboard":
        try:
            marker = await storage.get_json(DISCARDED_STORYBOARD_MARKER.format(run_id=run_id))
        except Exception:
            marker = None
        if marker and marker.get("key") == key:
            return None
    return key


async def prepare_run_timeline(
    storage: ArtifactStorage,
    run_id: str,
    *,
    format_track: str = "landscape",
    captions: bool = True,
    caption_style: str = "standard",
    music_enabled: bool = True,
    copy_media: bool = False,
    write: bool = False,
    require_alignment: bool = False,
    existing_media_only: bool = False,
):
    """Build a run's Timeline from its latest artifacts (P13b-S1).

    Returns (Timeline, artifact_key_or_None). Raises HTTPException: 404 when the run
    has no storyboard or manifest, 409 (with the operator-facing message) while any
    scene has no file.

    copy_media copies the shared-library music (when music_enabled) and each scene's
    curated SFX into the run folder first, exactly as a render does, so the timeline
    can point at them. write stores the Timeline as a versioned run artifact
    (stage "render", name "timeline") and returns its key.

    require_alignment answers 409 when the run has no voice alignment (the export
    needs the voiceover and its word timing). existing_media_only checks the run's
    files in storage: optional music / SFX that are absent are dropped from the
    timeline, a missing scene file or voiceover is a 409.
    """
    from datetime import datetime

    from fastapi import HTTPException

    from cf_platform.core.artifact_manager import read_artifact, write_artifact
    from cf_platform.core.schemas import LineageEnvelope
    from cf_platform.workers.capcut_export import prune_missing_media
    from cf_platform.workers.render_worker import _copy_all_scene_sfx_to_run, _copy_music_to_run
    from cf_platform.workers.storyboard_worker import _sanitize_storyboard_data
    from cf_platform.workers.timeline import (
        MissingAssetsError,
        TimelineArtifact,
        build_run_timeline,
    )
    from cf_platform.workers.voice_production import VoiceAlignmentArtifact
    from src.models import AssetManifest, Storyboard

    sb_key = await latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard")
    if not sb_key:
        raise HTTPException(status_code=404, detail="No storyboard found — run storyboard generation first.")
    mf_key = await latest_artifact_key(storage, run_id, "acquisition", "asset_manifest")
    if not mf_key:
        raise HTTPException(status_code=404, detail="No asset manifest — acquire assets first.")
    _, sb_body = await read_artifact(storage, sb_key)
    _, mf_body = await read_artifact(storage, mf_key)
    storyboard = Storyboard.model_validate(_sanitize_storyboard_data(sb_body["storyboard"]))
    raw_manifest = mf_body.get("manifest") or {}
    if not raw_manifest.get("entries"):
        raise HTTPException(status_code=404, detail="No asset manifest — acquire assets first.")
    manifest = AssetManifest.model_validate(raw_manifest)

    alignment = None
    va_key = await latest_artifact_key(storage, run_id, "voice", "voice_alignment")
    if va_key:
        try:
            _, va_body = await read_artifact(storage, va_key)
            alignment = VoiceAlignmentArtifact.model_validate(va_body)
        except Exception:
            alignment = None

    if require_alignment and alignment is None:
        raise HTTPException(
            status_code=409,
            detail="No voiceover for this run — generate or upload the voiceover before exporting.",
        )

    if copy_media:
        if music_enabled:
            await _copy_music_to_run(run_id, storage)
        await _copy_all_scene_sfx_to_run(run_id, storyboard, storage)

    try:
        timeline = await build_run_timeline(
            storage, run_id, storyboard, manifest, alignment,
            format_track=format_track, captions=captions, caption_style=caption_style,
        )
        if existing_media_only:
            timeline = prune_missing_media(timeline, set(await storage.list_keys(f"runs/{run_id}/")))
    except MissingAssetsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    key = None
    if write:
        record = await write_artifact(
            storage, TimelineArtifact(timeline=timeline, generated_at=datetime.now()),
            name="timeline", stage="render", run_id=run_id, user_id=PLATFORM_USER_ID,
            lineage=LineageEnvelope(
                run_id=run_id, worker="timeline_builder", worker_version="1.0.0",
                prompt_version="none", model="none", created_at=datetime.now(),
            ),
        )
        key = record.r2_key
    return timeline, key
