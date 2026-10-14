"""Studio routes for an Animation storyboard's continuity bible (P-AN1-S4, D108).

    POST   /studio/runs/{run_id}/storyboard/continuity               add an entry
    PATCH  /studio/runs/{run_id}/storyboard/continuity/{entry_id}    edit an entry
    DELETE /studio/runs/{run_id}/storyboard/continuity/{entry_id}    remove an unused entry
    POST   /studio/runs/{run_id}/storyboard/scenes/{scene_id}/write-prompt
                                                                     the Visual Director writes one scene's prompt

Thin wrappers over cf_platform/workers/continuity_edit.py. Every edit writes a
new storyboard version under the run's lock, so it cannot collide with images
being generated. Editing a description flags the scenes that use the entry and
already have an image; the response lists them so Studio can offer to regenerate
exactly those (the bulk job, which shows the cost first).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cf_platform.core import limits
from cf_platform.core.artifact_manager import ArtifactStorage
from cf_platform.core.moderation import moderate
from cf_platform.core.config import PlatformSettings
from cf_platform.core.run_visuals import load_run_visuals
from cf_platform.interfaces.dependencies import get_artifact_storage, get_effective_platform_settings
from cf_platform.interfaces.routes.studio import (
    _load_manifest,
    _load_storyboard,
    _with_effective_strategy,
    _write_storyboard,
)
from cf_platform.workers.continuity_edit import (
    ContinuityEditError,
    ContinuityEntryInUseError,
    ContinuityEntryNotFoundError,
    add_entry,
    edit_entry,
    remove_entry,
)
from cf_platform.workers.scene_images import run_lock, scene_has_image, stale_scene_ids
from cf_platform.workers.scene_prompt_writer import ScenePrompt, ScenePromptError, write_scene_prompt
from src.models import ANIMATION_MODE, SCENE_FLAG_IMAGE_STALE, SceneShot

router = APIRouter()


class ContinuityAddRequest(BaseModel):
    """Request body for POST …/storyboard/continuity."""

    kind: str = "prop"
    name: str
    description: str


class ContinuityPatchRequest(BaseModel):
    """Request body for PATCH …/storyboard/continuity/{entry_id}; only the fields given change."""

    kind: str | None = None
    name: str | None = None
    description: str | None = None


async def _load_animation_storyboard(storage: ArtifactStorage, run_id: str):
    """Return (artifact_body, Storyboard) of an Animation run; 409 for any other storyboard."""
    artifact_body, storyboard = await _load_storyboard(storage, run_id)
    if storyboard.visual_mode != ANIMATION_MODE:
        raise HTTPException(status_code=409, detail="Only an Animation storyboard has a continuity bible.")
    return artifact_body, storyboard


def _http_error(exc: ContinuityEditError) -> HTTPException:
    """Map a bible edit error to its HTTP status: 404 unknown entry, 409 in use, 422 otherwise."""
    if isinstance(exc, ContinuityEntryNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ContinuityEntryInUseError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


async def _respond(storage: ArtifactStorage, run_id: str, artifact_body: dict, storyboard, **extra) -> dict:
    """Write the edited storyboard and return it with the scenes whose image is out of date."""
    _, body = await _write_storyboard(storage, run_id, artifact_body, storyboard, "studio_continuity")
    return {**_with_effective_strategy(body), "out_of_date": stale_scene_ids(storyboard), **extra}


@router.post("/studio/runs/{run_id}/storyboard/continuity")
async def studio_add_continuity_entry(
    run_id: str,
    body: ContinuityAddRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Add a character, prop or setting to the bible. Attach it to scenes in their edit dialog."""
    limits.check_character(body.description, "The description")
    await moderate(f"{body.name}. {body.description}", "continuity", run_id=run_id)
    async with run_lock(run_id):
        artifact_body, storyboard = await _load_animation_storyboard(storage, run_id)
        try:
            storyboard, entry = add_entry(storyboard, kind=body.kind, name=body.name, description=body.description)
        except ContinuityEditError as exc:
            raise _http_error(exc) from exc
        return await _respond(storage, run_id, artifact_body, storyboard, entry_id=entry.id)


@router.patch("/studio/runs/{run_id}/storyboard/continuity/{entry_id}")
async def studio_edit_continuity_entry(
    run_id: str,
    entry_id: str,
    body: ContinuityPatchRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Edit a bible entry. `newly_out_of_date` lists the scenes this edit flagged."""
    if body.description is not None:
        limits.check_character(body.description, "The description")
    await moderate(f"{body.name or ''}. {body.description or ''}", "continuity", run_id=run_id)
    async with run_lock(run_id):
        artifact_body, storyboard = await _load_animation_storyboard(storage, run_id)
        manifest = await _load_manifest(storage, run_id)
        try:
            storyboard, stale = edit_entry(
                storyboard, manifest, entry_id, name=body.name, description=body.description, kind=body.kind
            )
        except ContinuityEditError as exc:
            raise _http_error(exc) from exc
        return await _respond(storage, run_id, artifact_body, storyboard, newly_out_of_date=stale)


@router.delete("/studio/runs/{run_id}/storyboard/continuity/{entry_id}")
async def studio_remove_continuity_entry(
    run_id: str,
    entry_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Remove a bible entry no scene uses; 409 names the scenes that still use it."""
    async with run_lock(run_id):
        artifact_body, storyboard = await _load_animation_storyboard(storage, run_id)
        try:
            storyboard = remove_entry(storyboard, entry_id)
        except ContinuityEditError as exc:
            raise _http_error(exc) from exc
        return await _respond(storage, run_id, artifact_body, storyboard)


def apply_scene_prompt(storyboard, scene_id: str, written: ScenePrompt, manifest):
    """The storyboard with one scene's prompt, entities, shot and concept replaced.

    The scene's flags are recomputed: it no longer needs a prompt, and an image it
    already had is out of date. Returns None when the scene is gone (merged or split
    while the director was writing).
    """
    from cf_platform.workers.animation_storyboard_worker import animation_scene_flags

    scenes, found = [], False
    for scene in storyboard.scenes:
        if str(scene.scene) != scene_id:
            scenes.append(scene)
            continue
        found = True
        flags = animation_scene_flags(scene.duration_s, written.ai_prompt, scene.flags)
        if scene_has_image(scene, manifest) and SCENE_FLAG_IMAGE_STALE not in flags:
            flags.append(SCENE_FLAG_IMAGE_STALE)
        update = {"ai_prompt": written.ai_prompt, "entities": written.entities, "flags": flags}
        if written.visual_concept:
            update["visual_concept"] = written.visual_concept
        if written.shot_size or written.shot_angle:
            update["shot"] = SceneShot(size=written.shot_size, angle=written.shot_angle)
        scenes.append(scene.model_copy(update=update))
    return storyboard.model_copy(update={"scenes": scenes}) if found else None


@router.post("/studio/runs/{run_id}/storyboard/scenes/{scene_id}/write-prompt")
async def studio_write_scene_prompt(
    run_id: str,
    scene_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_effective_platform_settings),
) -> dict:
    """Ask the Visual Director for one scene's image prompt, with its usual rules, and save it.

    For a scene made by splitting another (it has no prompt), or one whose prompt the
    user wants rewritten, without re-cutting the whole storyboard. One model call; the
    storyboard is read again under the run's lock before it is written, so an edit made
    while the director was writing is kept. 404 unknown scene, 409 not an Animation
    storyboard or the scene was merged meanwhile, 502 when no usable prompt came back.
    """
    _, storyboard = await _load_animation_storyboard(storage, run_id)
    if not any(str(s.scene) == scene_id for s in storyboard.scenes):
        raise HTTPException(status_code=404, detail=f"Scene {scene_id} is not in the storyboard.")
    visuals = await load_run_visuals(storage, run_id)
    format_track = "landscape" if visuals.aspect_ratio == "16:9" else "portrait"
    await limits.spend_gate(getattr(settings, "EST_LLM_CALL_USD", 0.05), "the director", settings)
    try:
        written = await write_scene_prompt(
            storyboard, scene_id, settings.ANTHROPIC_API_KEY,
            master_style=visuals.master_style or "", format_track=format_track,
        )
    except ScenePromptError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    async with run_lock(run_id):
        artifact_body, storyboard = await _load_animation_storyboard(storage, run_id)
        updated = apply_scene_prompt(storyboard, scene_id, written, await _load_manifest(storage, run_id))
        if updated is None:
            raise HTTPException(status_code=409, detail="The scene changed while the prompt was written. Try again.")
        return await _respond(storage, run_id, artifact_body, updated, ai_prompt=written.ai_prompt)
