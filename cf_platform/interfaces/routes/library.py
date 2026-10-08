"""Tenant-wide asset libraries (P-UX build).

    GET /library/{kind}    videos | audio | footage | ai | music — every asset in the
                           tenant, each with its ID, project, run and a download link

Thin wrapper over cf_platform/core/library.py (D040). The listing reads the run
folders in storage; nothing is indexed.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

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
    PLATFORM_USER_ID,
    get_artifact_storage,
    get_project_repository,
    get_run_repository,
)
from cf_platform.interfaces.routes._helpers import latest_artifact_key

router = APIRouter()


async def _manifest_keys(storage: ArtifactStorage, run_id: str) -> set[str]:
    """The file keys the run's current asset manifest points at (empty when it has none)."""
    key = await latest_artifact_key(storage, run_id, "acquisition", "asset_manifest")
    if not key:
        return set()
    _, body = await read_artifact(storage, key)
    entries = (body.get("manifest") or {}).get("entries") or []
    return {e["file_key"] for e in entries if e.get("file_key")}


@router.get("/library/{kind}")
async def get_library(
    kind: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    runs: RunRepository = Depends(get_run_repository),
    projects: ProjectRepository = Depends(get_project_repository),
) -> dict:
    """List one library's assets across the tenant, newest run first; 404 for an unknown library."""
    if kind not in LIBRARY_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown library {kind!r} — expected one of {list(LIBRARY_KINDS)}")
    project_list = await projects.list_projects(PLATFORM_USER_ID, include_archived=True)
    names = {p.project_id: p.name for p in project_list}
    if kind == "music":
        from cf_platform.workers.render_worker import list_available_sfx

        items = await list_shared_music(storage, await list_available_sfx(storage))
        return {"kind": kind, "items": items, "projects": []}

    records = [r for r in await runs.list_runs() if r.archived_at is None]
    refs = [
        RunRef(r.run_id, r.name or "Untitled run", r.project_id, names.get(r.project_id, r.project_id),
               r.created_at.isoformat())
        for r in records
    ]

    async def manifest_keys(run_id: str) -> set[str]:
        return await _manifest_keys(storage, run_id)

    per_run = await asyncio.gather(*(list_run_assets(kind, ref, storage, manifest_keys) for ref in refs))
    items = [item for run_items in per_run for item in run_items]
    projects_out = [{"project_id": p.project_id, "name": p.name} for p in project_list]
    return {"kind": kind, "items": items, "projects": projects_out}
