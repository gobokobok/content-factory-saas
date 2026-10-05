"""Project, shortlist and project-scoped run routes (Sprint P12, D092, D094).

    GET    /projects                                  list projects (+ run counts)
    POST   /projects                                  create a project
    GET    /projects/{id}                             read one
    PATCH  /projects/{id}                             name / niche / config / archive
    GET    /projects/{id}/runs                        the project's runs, newest first
    POST   /projects/{id}/runs                        create a run from shortlist item(s)
    POST   /projects/{id}/runs/import                 register runs known only to a browser
    DELETE /projects/{id}/runs/{run_id}               drop a run from the project's list
    GET    /projects/{id}/shortlist                   the project's shortlist
    POST   /projects/{id}/shortlist                   add an idea by hand
    GET    /projects/{id}/shortlist/{item_id}         read one item, removed or not
    DELETE /projects/{id}/shortlist/{item_id}         remove one item (soft)
    GET    /studio/runs/{run_id}/context              a run's project + source items, for Studio

There is deliberately no route that replaces or clears a shortlist in bulk (D094).
Handlers are thin wrappers over the pure async functions in cf_platform/core
(projects.py, shortlist.py, run_manager.py) — D040.
"""

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from cf_platform.core.projects import (
    Project,
    ProjectNotFoundError,
    ProjectRepository,
    create_project,
    update_project,
)
from cf_platform.core.run_manager import (
    RunNotFoundError,
    RunRepository,
    archive_run,
    create_run,
    register_existing_run,
)
from cf_platform.core.schemas import RunRecord
from cf_platform.core.shortlist import (
    ShortlistItem,
    ShortlistItemNotFoundError,
    ShortlistItemUnavailableError,
    ShortlistRepository,
    add_manual_item,
    build_idea_context,
    remove_item,
    resolve_items_for_run,
)
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_project_repository,
    get_run_repository,
    get_shortlist_repository,
)

router = APIRouter()

# Block name on runs created from the project page or imported from a browser.
STUDIO_BLOCK = "studio"
# A run's list label is cut to this many characters of its idea title.
_RUN_NAME_MAX_CHARS = 120
# Upper bound on one import call — a browser's local history held at most 20 runs.
_IMPORT_MAX_RUNS = 50
_RUN_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


# ── Schemas ──────────────────────────────────────────────────────────────


class ProjectResponse(BaseModel):
    """One project, with how many runs it holds."""

    project_id: str
    name: str
    niche: str
    config: dict[str, Any]
    default_channel_id: str | None
    archived: bool
    created_at: datetime
    updated_at: datetime
    run_count: int = 0


class ProjectCreateRequest(BaseModel):
    """Request body for POST /platform/projects."""

    name: str = Field(min_length=1, max_length=120)
    niche: str = Field(default="", max_length=200)
    config: dict[str, Any] = {}


class ProjectUpdateRequest(BaseModel):
    """Request body for PATCH /platform/projects/{id}. Omitted fields are left unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    niche: str | None = Field(default=None, max_length=200)
    config: dict[str, Any] | None = None
    archived: bool | None = None


class ProjectRunResponse(BaseModel):
    """One run in a project's run list."""

    run_id: str
    name: str
    status: str
    block: str
    created_at: datetime
    updated_at: datetime


class RunFromShortlistRequest(BaseModel):
    """Request body for POST /platform/projects/{id}/runs."""

    item_ids: list[str] = Field(min_length=1)
    # "generated": Script → generated voice (default). "uploaded": the operator
    # uploads the voiceover; Script and Voice stages are skipped (P14b).
    voice_source: Literal["generated", "uploaded"] = "generated"
    # ISO 639-1 language of the video (P14b-S1). Omitted: the project's
    # config.language, else "en". A per-run choice — never locked by the project's
    # earlier runs.
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")


class ImportedRun(BaseModel):
    """One run from a browser's local history (`localStorage.studio_runs`)."""

    id: str = Field(pattern=_RUN_ID_PATTERN)
    name: str = Field(default="", max_length=200)
    ts: float | None = None  # epoch milliseconds, as Studio stored it


class RunImportRequest(BaseModel):
    """Request body for POST /platform/projects/{id}/runs/import."""

    runs: list[ImportedRun] = Field(max_length=_IMPORT_MAX_RUNS)


class RunImportResponse(BaseModel):
    """How many of the submitted runs were newly registered vs already known."""

    imported: int
    already_known: int


class ShortlistItemResponse(BaseModel):
    """One shortlist item with its origin fields and how many runs it has fed."""

    item_id: str
    project_id: str
    title: str
    summary: str
    discovery_method: str
    source: str | None
    evidence: dict[str, Any]
    kpis: dict[str, Any]
    research_run_id: str | None
    discovered_at: datetime
    removed_at: datetime | None
    run_count: int = 0


class ShortlistAddRequest(BaseModel):
    """Request body for POST /platform/projects/{id}/shortlist — a hand-entered idea."""

    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=2000)
    source: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class RunContextResponse(BaseModel):
    """What Studio needs to open a run inside its project."""

    run_id: str
    name: str
    status: str
    created_at: datetime
    project: ProjectResponse
    items: list[ShortlistItemResponse]
    idea_title: str
    supporting_points: list[str]
    voice_source: Literal["generated", "uploaded"] = "generated"
    language: str = "en"


# ── Helpers ──────────────────────────────────────────────────────────────


def _project_response(project: Project, run_count: int = 0) -> ProjectResponse:
    """Map a Project to its response model."""
    return ProjectResponse(
        project_id=project.project_id,
        name=project.name,
        niche=project.niche,
        config=project.config,
        default_channel_id=project.default_channel_id,
        archived=project.archived_at is not None,
        created_at=project.created_at,
        updated_at=project.updated_at,
        run_count=run_count,
    )


def _run_response(run: RunRecord) -> ProjectRunResponse:
    """Map a RunRecord to its run-list response model."""
    return ProjectRunResponse(
        run_id=run.run_id,
        name=run.name,
        status=run.status,
        block=run.block,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _item_response(item: ShortlistItem, run_count: int = 0) -> ShortlistItemResponse:
    """Map a ShortlistItem to its response model."""
    return ShortlistItemResponse(
        item_id=item.item_id,
        project_id=item.project_id,
        title=item.title,
        summary=item.summary,
        discovery_method=item.discovery_method,
        source=item.source,
        evidence=item.evidence,
        kpis=item.kpis,
        research_run_id=item.research_run_id,
        discovered_at=item.discovered_at,
        removed_at=item.removed_at,
        run_count=run_count,
    )


async def _project_or_404(project_id: str, projects: ProjectRepository) -> Project:
    """Return the operator's project, or raise 404 if it is unknown or another tenant's."""
    try:
        project = await projects.get(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    if project.tenant_id != PLATFORM_USER_ID:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return project


# ── Projects ─────────────────────────────────────────────────────────────


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    include_archived: bool = False,
    projects: ProjectRepository = Depends(get_project_repository),
    runs: RunRepository = Depends(get_run_repository),
) -> list[ProjectResponse]:
    """Return the operator's projects, newest first, each with its run count."""
    records = await projects.list_projects(PLATFORM_USER_ID, include_archived=include_archived)
    counts = await runs.count_by_project()
    return [_project_response(project, counts.get(project.project_id, 0)) for project in records]


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project_route(
    body: ProjectCreateRequest,
    projects: ProjectRepository = Depends(get_project_repository),
) -> ProjectResponse:
    """Create a project. Returns 422 when the name is blank."""
    try:
        project = await create_project(
            PLATFORM_USER_ID, body.name, projects, niche=body.niche, config=body.config
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _project_response(project)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    projects: ProjectRepository = Depends(get_project_repository),
    runs: RunRepository = Depends(get_run_repository),
) -> ProjectResponse:
    """Return one project with its run count. Raises 404 if project_id is unknown."""
    project = await _project_or_404(project_id, projects)
    counts = await runs.count_by_project()
    return _project_response(project, counts.get(project_id, 0))


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def patch_project(
    project_id: str,
    body: ProjectUpdateRequest,
    projects: ProjectRepository = Depends(get_project_repository),
    runs: RunRepository = Depends(get_run_repository),
) -> ProjectResponse:
    """Update a project's name, niche, config or archived flag. Only supplied fields change."""
    await _project_or_404(project_id, projects)
    try:
        project = await update_project(project_id, projects, **body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    counts = await runs.count_by_project()
    return _project_response(project, counts.get(project_id, 0))


# ── Project runs ─────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/runs", response_model=list[ProjectRunResponse])
async def list_project_runs(
    project_id: str,
    projects: ProjectRepository = Depends(get_project_repository),
    runs: RunRepository = Depends(get_run_repository),
) -> list[ProjectRunResponse]:
    """Return the project's runs, newest first, with status and created date."""
    await _project_or_404(project_id, projects)
    return [_run_response(run) for run in await runs.list_for_project(project_id)]


@router.post("/projects/{project_id}/runs", response_model=ProjectRunResponse, status_code=201)
async def create_run_from_shortlist(
    project_id: str,
    body: RunFromShortlistRequest,
    projects: ProjectRepository = Depends(get_project_repository),
    runs: RunRepository = Depends(get_run_repository),
    shortlist: ShortlistRepository = Depends(get_shortlist_repository),
) -> ProjectRunResponse:
    """Create a run in the project from one or more shortlist items and link them.

    Returns 404 for an unknown project or item id, and 409 for an item that was
    removed from the shortlist or belongs to another project.
    """
    project = await _project_or_404(project_id, projects)
    try:
        items = await resolve_items_for_run(project_id, body.item_ids, shortlist)
    except ShortlistItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ShortlistItemUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    context = build_idea_context(items)
    item_ids = [item.item_id for item in items]
    run = await create_run(
        PLATFORM_USER_ID,
        STUDIO_BLOCK,
        {
            "item_ids": item_ids,
            "voice_source": body.voice_source,
            "language": body.language or str((project.config or {}).get("language") or "en"),
            **context,
        },
        runs,
        project_id=project_id,
        name=context["idea_title"][:_RUN_NAME_MAX_CHARS],
    )
    await shortlist.link_run(run.run_id, item_ids)
    return _run_response(run)


@router.post("/projects/{project_id}/runs/import", response_model=RunImportResponse)
async def import_local_runs(
    project_id: str,
    body: RunImportRequest,
    projects: ProjectRepository = Depends(get_project_repository),
    runs: RunRepository = Depends(get_run_repository),
) -> RunImportResponse:
    """Register runs that exist only in a browser's local history into the project.

    Before P12 Studio kept its run list in `localStorage` and a pasted-script run
    never got a `runs` row. A run that already has a row is left exactly where it
    is, so calling this repeatedly — or from several browsers — is safe.
    """
    await _project_or_404(project_id, projects)
    imported = 0
    for entry in body.runs:
        created_at = datetime.fromtimestamp(entry.ts / 1000, tz=UTC) if entry.ts else None
        _, created = await register_existing_run(
            entry.id, PLATFORM_USER_ID, project_id, runs, name=entry.name.strip(), created_at=created_at
        )
        imported += int(created)
    return RunImportResponse(imported=imported, already_known=len(body.runs) - imported)


@router.delete("/projects/{project_id}/runs/{run_id}", status_code=204)
async def archive_project_run(
    project_id: str,
    run_id: str,
    projects: ProjectRepository = Depends(get_project_repository),
    runs: RunRepository = Depends(get_run_repository),
) -> Response:
    """Drop a run from the project's run list. The row is kept (archived), so lineage survives."""
    await _project_or_404(project_id, projects)
    try:
        run = await runs.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    if run.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    await archive_run(run_id, runs)
    return Response(status_code=204)


# ── Shortlist ────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/shortlist", response_model=list[ShortlistItemResponse])
async def list_shortlist(
    project_id: str,
    projects: ProjectRepository = Depends(get_project_repository),
    shortlist: ShortlistRepository = Depends(get_shortlist_repository),
) -> list[ShortlistItemResponse]:
    """Return the project's shortlist, newest first, without removed items."""
    await _project_or_404(project_id, projects)
    items = await shortlist.list_for_project(project_id)
    counts = await shortlist.run_counts(project_id)
    return [_item_response(item, counts.get(item.item_id, 0)) for item in items]


@router.post("/projects/{project_id}/shortlist", response_model=ShortlistItemResponse, status_code=201)
async def add_shortlist_item(
    project_id: str,
    body: ShortlistAddRequest,
    projects: ProjectRepository = Depends(get_project_repository),
    shortlist: ShortlistRepository = Depends(get_shortlist_repository),
) -> ShortlistItemResponse:
    """Add a hand-entered idea to the project's shortlist."""
    await _project_or_404(project_id, projects)
    try:
        item = await add_manual_item(
            PLATFORM_USER_ID,
            project_id,
            body.title,
            shortlist,
            summary=body.summary,
            source=body.source,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _item_response(item)


@router.get("/projects/{project_id}/shortlist/{item_id}", response_model=ShortlistItemResponse)
async def get_shortlist_item(
    project_id: str,
    item_id: str,
    projects: ProjectRepository = Depends(get_project_repository),
    shortlist: ShortlistRepository = Depends(get_shortlist_repository),
) -> ShortlistItemResponse:
    """Return one shortlist item by id — including a removed one, so run links stay resolvable."""
    await _project_or_404(project_id, projects)
    try:
        item = await shortlist.get(item_id)
    except ShortlistItemNotFoundError:
        raise HTTPException(status_code=404, detail=f"Shortlist item not found: {item_id}")
    if item.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"Shortlist item not found: {item_id}")
    counts = await shortlist.run_counts(project_id)
    return _item_response(item, counts.get(item_id, 0))


@router.delete("/projects/{project_id}/shortlist/{item_id}", status_code=204)
async def remove_shortlist_item(
    project_id: str,
    item_id: str,
    projects: ProjectRepository = Depends(get_project_repository),
    shortlist: ShortlistRepository = Depends(get_shortlist_repository),
) -> Response:
    """Remove one item from the shortlist (soft delete — runs created from it keep their link)."""
    await _project_or_404(project_id, projects)
    try:
        await remove_item(project_id, item_id, shortlist)
    except ShortlistItemNotFoundError:
        raise HTTPException(status_code=404, detail=f"Shortlist item not found: {item_id}")
    return Response(status_code=204)


# ── Run context (Studio) ─────────────────────────────────────────────────


@router.get("/studio/runs/{run_id}/context", response_model=RunContextResponse)
async def get_run_context(
    run_id: str,
    projects: ProjectRepository = Depends(get_project_repository),
    runs: RunRepository = Depends(get_run_repository),
    shortlist: ShortlistRepository = Depends(get_shortlist_repository),
) -> RunContextResponse:
    """Return a run's project, the shortlist items it came from, and the combined idea context.

    Studio uses this to show the project in the pipeline header, pre-fill the
    Script stage and list the source items in the info panel. Raises 404 when
    the run has no row — a pre-P12 run not yet imported into a project.
    """
    try:
        run = await runs.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    project = await _project_or_404(run.project_id, projects)
    items = await shortlist.items_for_run(run_id)
    context = build_idea_context(items)
    return RunContextResponse(
        run_id=run.run_id,
        name=run.name,
        status=run.status,
        created_at=run.created_at,
        project=_project_response(project),
        items=[_item_response(item) for item in items],
        idea_title=context["idea_title"],
        supporting_points=context["supporting_points"],
        voice_source="uploaded" if run.inputs.get("voice_source") == "uploaded" else "generated",
        language=str(run.inputs.get("language") or "en"),
    )
