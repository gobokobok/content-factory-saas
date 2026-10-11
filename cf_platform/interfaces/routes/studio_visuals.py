"""Studio route for a run's look and image source (P-PROJ1-S1, D111).

    GET /studio/runs/{run_id}/visuals    the run's look, image source and whether they are locked
    PUT /studio/runs/{run_id}/visuals    change them; asks before discarding an existing storyboard

Two independent choices: the **look** (realistic / animated — what the prompts and
the master style aim for) and the **image source** (stock footage / AI-generated —
what assets the run has, which decides the storyboard worker and whether the
continuity bible exists). Both are locked once a storyboard exists, because the
storyboard was cut for them; unlocking is an explicit reset that discards the
storyboard and its acquired assets, the same rule as re-uploading a voiceover.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage
from cf_platform.core.run_visuals import LOOKS, read_run_settings, settings_key
from cf_platform.interfaces.dependencies import get_artifact_storage
from cf_platform.interfaces.routes._helpers import latest_artifact_key
from cf_platform.interfaces.routes.studio_voice import discard_storyboard

router = APIRouter()

_SOURCE_TO_MODE = {"stock": "stock", "ai": "ai_animation"}
_MODE_TO_SOURCE = {"stock": "stock", "ai_animation": "ai"}


class VisualsRequest(BaseModel):
    """Request body for PUT …/visuals; only the fields given change."""

    look: Literal["realistic", "animated"] | None = None
    image_source: Literal["stock", "ai"] | None = None
    confirm_reset: bool = False


def _current(settings: dict) -> dict[str, str]:
    """The run's look and image source from its settings.json, with the defaults."""
    source = _MODE_TO_SOURCE.get(settings.get("visual_mode"), "stock")
    look = settings.get("look") if settings.get("look") in LOOKS else ("animated" if source == "ai" else "realistic")
    return {"look": look, "image_source": source}


async def _storyboard_exists(storage: ArtifactStorage, run_id: str) -> bool:
    """True when the run has a live (not discarded) storyboard."""
    return bool(await latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard"))


@router.get("/studio/runs/{run_id}/visuals")
async def studio_get_visuals(run_id: str, storage: ArtifactStorage = Depends(get_artifact_storage)) -> dict:
    """The run's look and image source, and whether a storyboard locks them."""
    current = _current(await read_run_settings(storage, run_id))
    return {**current, "locked": await _storyboard_exists(storage, run_id)}


@router.put("/studio/runs/{run_id}/visuals", response_model=None)
async def studio_put_visuals(
    run_id: str,
    body: VisualsRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
):
    """Change the look and/or image source.

    With a storyboard in place a real change answers 409 `needs_confirmation`, naming
    what a reset discards; repeating the request with `confirm_reset` discards the
    storyboard and its acquired assets, then applies the change. Setting what the run
    already has changes nothing and never asks.
    """
    settings = await read_run_settings(storage, run_id)
    current = _current(settings)
    wanted = {
        "look": body.look or current["look"],
        "image_source": body.image_source or current["image_source"],
    }
    changed = wanted != current
    locked = await _storyboard_exists(storage, run_id)
    discarded: list[str] = []
    if changed and locked:
        discarded = ["the storyboard", "the acquired assets, generated images and scene edits that came with it"]
        if not body.confirm_reset:
            return JSONResponse(status_code=409, content={
                "detail": "This run already has a storyboard, which was cut for its current look and image "
                "source. Changing them discards " + " and ".join(discarded) + ".",
                "needs_confirmation": True,
                "discards": discarded,
            })
        key = await latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard")
        if key is None:
            raise HTTPException(status_code=409, detail="The storyboard changed while you were deciding — try again.")
        await discard_storyboard(storage, run_id, key)
    if changed:
        settings["look"] = wanted["look"]
        settings["visual_mode"] = _SOURCE_TO_MODE[wanted["image_source"]]
        await storage.put_json(settings_key(run_id), settings)
    return {**wanted, "changed": changed, "discarded": discarded, "locked": False if discarded else locked}
