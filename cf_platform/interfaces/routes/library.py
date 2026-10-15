"""Tenant-wide asset libraries (P-UX build).

    GET /library/{kind}    videos | audio | footage | ai | music — every asset in the
                           tenant, each with its ID, project, run and a download link

Thin wrapper over cf_platform/core/library.py (D040). The listing reads the run
folders in storage; nothing is indexed.
"""

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.library import (
    LIBRARY_KINDS,
    RunRef,
    list_run_assets,
    list_shared_music,
)
from cf_platform.core.projects import ProjectRepository
from cf_platform.core.run_manager import RunRepository
from cf_platform.interfaces.dependencies import (
    current_tenant_id,
    current_user,
    get_artifact_storage,
    get_project_repository,
    get_run_repository,
)
from cf_platform.interfaces.routes._helpers import latest_artifact_key

# The libraries a Basic account has.
BASIC_LIBRARY_KINDS = ("videos", "ai", "images", "music")

router = APIRouter()


async def _manifest_keys(storage: ArtifactStorage, run_id: str) -> set[str]:
    """The file keys the run's current asset manifest points at (empty when it has none)."""
    key = await latest_artifact_key(storage, run_id, "acquisition", "asset_manifest")
    if not key:
        return set()
    _, body = await read_artifact(storage, key)
    entries = (body.get("manifest") or {}).get("entries") or []
    return {e["file_key"] for e in entries if e.get("file_key")}


async def _listing(kind, storage, runs, projects) -> dict:
    """The library as GET returns it (shared by the listing and the delete)."""
    project_list = await projects.list_projects(current_tenant_id(), include_archived=True)
    names = {p.project_id: p.name for p in project_list}
    records = [r for r in await runs.list_runs(current_tenant_id()) if r.archived_at is None]
    refs = [
        RunRef(r.run_id, r.name or "Untitled run", r.project_id, names.get(r.project_id, r.project_id),
               r.created_at.isoformat())
        for r in records
    ]
    if kind == "music":
        return {"kind": kind, "items": await list_shared_music(storage, refs, current_tenant_id()), "projects": []}

    async def manifest_keys(run_id: str) -> set[str]:
        return await _manifest_keys(storage, run_id)

    per_run = await asyncio.gather(*(list_run_assets(kind, ref, storage, manifest_keys) for ref in refs))
    items = [item for run_items in per_run for item in run_items]
    projects_out = [{"project_id": p.project_id, "name": p.name} for p in project_list]
    return {"kind": kind, "items": items, "projects": projects_out}


def _check_kind(kind: str) -> None:
    """404 for an unknown library, 403 for one a Basic account does not have."""
    if kind not in LIBRARY_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown library {kind!r} — expected one of {list(LIBRARY_KINDS)}")
    # Basic has Videos, Images (AI), AI generations and BG music; Audio and Footage are Super's (D118).
    if kind not in BASIC_LIBRARY_KINDS and not current_user().is_super:
        raise HTTPException(status_code=403, detail="This needs a Super account.")


@router.post("/library/music", status_code=201)
async def add_music_track(file: UploadFile, storage: ArtifactStorage = Depends(get_artifact_storage)) -> dict:
    """Add a background-music track to the account's BG music library (mp3, wav or m4a, up to 50 MB)."""
    from cf_platform.core import limits
    from cf_platform.interfaces.routes.studio import _read_upload_capped

    types = {"audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mp4": ".m4a",
             "audio/x-m4a": ".m4a", "audio/m4a": ".m4a"}
    content_type = (file.content_type or "").split(";")[0].strip()
    if content_type not in types:
        raise HTTPException(status_code=422, detail=f"Unsupported file type: {content_type!r}. Allowed: mp3, wav, m4a.")
    data = await _read_upload_capped(file, 50 * 1024 * 1024, "50 MB")
    await limits.reserve_upload(len(data))
    stem = re.sub(r"[^A-Za-z0-9 _.-]+", "", (file.filename or "track").rsplit(".", 1)[0]).strip()[:60] or "track"
    key = f"tenant-music/{current_tenant_id()}/{stem}{types[content_type]}"
    await storage.put_bytes(key, data, content_type=content_type)
    return {"key": key, "name": f"{stem}{types[content_type]}"}


@router.delete("/library/{kind}/{asset_id}", status_code=204)
async def delete_library_item(
    kind: str,
    asset_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    runs: RunRepository = Depends(get_run_repository),
    projects: ProjectRepository = Depends(get_project_repository),
) -> Response:
    """Delete one file from a library the caller owns.

    The item is looked up in the caller's own listing, so another account's file is simply
    absent (404). The platform's shared tracks and images a video still uses are refused.
    """
    _check_kind(kind)
    listing = await _listing(kind, storage, runs, projects)
    item = next((i for i in listing["items"] if i["asset_id"] == asset_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="That item is not in your library.")
    if item.get("facet") == "platform":
        raise HTTPException(status_code=403, detail="The platform's tracks cannot be deleted.")
    if str(item.get("facts", "")).endswith("in use"):
        raise HTTPException(status_code=409, detail="A video still uses this image. Replace it there first.")
    await storage.delete_key(item["key"])
    return Response(status_code=204)


@router.get("/library/{kind}")
async def get_library(
    kind: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    runs: RunRepository = Depends(get_run_repository),
    projects: ProjectRepository = Depends(get_project_repository),
) -> dict:
    """List one library's assets across the tenant, newest run first; 404 for an unknown library."""
    _check_kind(kind)
    return await _listing(kind, storage, runs, projects)
