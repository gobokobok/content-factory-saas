"""Studio routes for an Animation storyboard's continuity bible (P-AN1-S4, D108).

    POST   /studio/runs/{run_id}/storyboard/continuity               add an entry
    PATCH  /studio/runs/{run_id}/storyboard/continuity/{entry_id}    edit an entry
    DELETE /studio/runs/{run_id}/storyboard/continuity/{entry_id}    remove an unused entry

Thin wrappers over cf_platform/workers/continuity_edit.py. Every edit writes a
new storyboard version under the run's lock, so it cannot collide with images
being generated. Editing a description flags the scenes that use the entry and
already have an image; the response lists them so Studio can offer to regenerate
exactly those (the bulk job, which shows the cost first).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage
from cf_platform.interfaces.dependencies import get_artifact_storage
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
from cf_platform.workers.scene_images import run_lock, stale_scene_ids
from src.models import ANIMATION_MODE

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
