"""Project, shortlist and project-scoped run routes (Sprint P12, D092, D094).

    GET    /projects                                  list projects (+ run counts)
    POST   /projects                                  create a project
    GET    /projects/{id}                             read one
    PATCH  /projects/{id}                             name / niche / config / archive
    GET    /projects/{id}/runs                        the project's runs, newest first, with progress
    POST   /projects/{id}/runs                        create a run from idea(s) or from a title alone
    POST   /projects/{id}/runs/import                 register runs known only to a browser
    DELETE /projects/{id}/runs/{run_id}               drop a run from the project's list
    GET    /projects/{id}/shortlist                   the project's shortlist
    POST   /projects/{id}/shortlist                   add an idea by hand
    PATCH  /projects/{id}/shortlist/{item_id}         edit an idea
    GET    /projects/{id}/shortlist/{item_id}         read one item, removed or not
    DELETE /projects/{id}/shortlist/{item_id}         remove one item (soft)
    GET    /studio/runs/{run_id}/context              a run's project + source items, for Studio

There is deliberately no route that replaces or clears a shortlist in bulk (D094).
Handlers are thin wrappers over the pure async functions in cf_platform/core
(projects.py, shortlist.py, run_manager.py) — D040.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from cf_platform.core.artifact_manager import ArtifactRepository, ArtifactStorage
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.integrations import resolve_defaults, resolve_run_values
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
from cf_platform.core.run_progress import collect_run_progress
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
    update_item,
)
from cf_platform.core.tenant_settings import TenantSettingsRepository
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_artifact_repository,
    get_artifact_storage,
    get_project_repository,
    get_run_repository,
    get_shortlist_repository,
    get_tenant_settings_repository,
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
    last_activity: datetime | None = None


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
    voice_source: Literal["generated", "uploaded"] = "generated"
    language: str = "en"
    format: str | None = None
    # Derived from what the run has produced (core/run_progress.py): how many of the
    # five steps are done, the first one that is not, and whether a final video exists.
    steps_done: int = 0
    current_step: str | None = None
    has_video: bool = False


class RunFromShortlistRequest(BaseModel):
    """Request body for POST /platform/projects/{id}/runs."""

    # Ideas the run is made from. May be empty: a run can start from a title alone.
    item_ids: list[str] = Field(default_factory=list)
    # The run's title and an optional brief. Required when there are no ideas; with
    # ideas, a title replaces the ideas' combined title and the brief is added to the
    # points the script covers.
    title: str | None = Field(default=None, max_length=300)
    brief: str | None = Field(default=None, max_length=2000)
    # Format (aspect ratio) of the video, decides which footage is acquired. Omitted:
    # the project's default, else the tenant's.
    aspect_ratio: Literal["9:16", "16:9"] | None = None
    # "generated" (default) or "uploaded". The Script step now chooses the source;
    # this stays accepted so existing callers keep working.
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


class ShortlistUpdateRequest(BaseModel):
    """Request body for PATCH /platform/projects/{id}/shortlist/{item_id} — only supplied fields change."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    summary: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


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
    format: str | None = None
    brief: str = ""
    tenant_defaults: dict[str, Any] = {}


# ── Helpers ──────────────────────────────────────────────────────────────


def _project_response(
    project: Project, run_count: int = 0, last_activity: datetime | None = None
) -> ProjectResponse:
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
        last_activity=last_activity,
    )


def _run_response(
    run: RunRecord, progress: tuple[int, str | None, bool] | None = None
) -> ProjectRunResponse:
    """Map a RunRecord to its run-list response model."""
    return ProjectRunResponse(
        run_id=run.run_id,
        name=run.name,
        status=run.status,
        block=run.block,
        created_at=run.created_at,
        updated_at=run.updated_at,
        voice_source="uploaded" if run.inputs.get("voice_source") == "uploaded" else "generated",
        language=str(run.inputs.get("language") or "en"),
        format=run.inputs.get("aspect_ratio"),
        steps_done=progress[0] if progress else 0,
        current_step=progress[1] if progress else None,
        has_video=progress[2] if progress else False,
    )


async def _activity_by_project(runs: RunRepository) -> dict[str, datetime]:
    """Latest run activity (updated_at) per project, ignoring archived runs."""
    latest: dict[str, datetime] = {}
    for run in await runs.list_runs():
        if run.archived_at is None and (run.project_id not in latest or run.updated_at > latest[run.project_id]):
            latest[run.project_id] = run.updated_at
    return latest


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
    activity = await _activity_by_project(runs)
    return [
        _project_response(project, counts.get(project.project_id, 0), activity.get(project.project_id))
        for project in records
    ]


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
    activity = await _activity_by_project(runs)
    return _project_response(project, counts.get(project_id, 0), activity.get(project_id))


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
    artifacts: ArtifactRepository = Depends(get_artifact_repository),
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> list[ProjectRunResponse]:
    """Return the project's runs, newest first, each with its mode, language and progress."""
    await _project_or_404(project_id, projects)
    records = await runs.list_for_project(project_id)
    progress = await asyncio.gather(*(collect_run_progress(run.run_id, artifacts, storage) for run in records))
    return [_run_response(run, prog) for run, prog in zip(records, progress, strict=True)]


@router.post("/projects/{project_id}/runs", response_model=ProjectRunResponse, status_code=201)
async def create_run_from_shortlist(
    project_id: str,
    body: RunFromShortlistRequest,
    projects: ProjectRepository = Depends(get_project_repository),
    runs: RunRepository = Depends(get_run_repository),
    shortlist: ShortlistRepository = Depends(get_shortlist_repository),
    tenant_repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> ProjectRunResponse:
    """Create a run in the project from idea(s), or from a title alone, and link the ideas.

    A run needs at least one idea or a title (422 otherwise). The run's language and
    format are its own choice, else the project's default, else the tenant's. Returns
    404 for an unknown project or idea id, and 409 for an idea that was removed from
    the shortlist or belongs to another project.
    """
    project = await _project_or_404(project_id, projects)
    title = (body.title or "").strip()
    brief = (body.brief or "").strip()
    if not body.item_ids and not title:
        raise HTTPException(status_code=422, detail="Give the run a title, or start it from an idea.")
    items: list[ShortlistItem] = []
    if body.item_ids:
        try:
            items = await resolve_items_for_run(project_id, body.item_ids, shortlist)
        except ShortlistItemNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ShortlistItemUnavailableError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    context = build_idea_context(items)
    if title:
        context["idea_title"] = title
    if brief:
        context["supporting_points"] = [*context["supporting_points"], brief]
    item_ids = [item.item_id for item in items]
    try:
        tenant_defaults = await resolve_defaults(tenant_repo, PLATFORM_USER_ID, settings)
    except Exception:
        tenant_defaults = {"language": "en", "format": "9:16"}
    values = resolve_run_values(
        tenant_defaults, project.config, language=body.language, aspect_ratio=body.aspect_ratio
    )
    run = await create_run(
        PLATFORM_USER_ID,
        STUDIO_BLOCK,
        {
            "item_ids": item_ids,
            "voice_source": body.voice_source,
            "language": values["language"],
            "aspect_ratio": values["format"],
            **context,
        },
        runs,
        project_id=project_id,
        name=context["idea_title"][:_RUN_NAME_MAX_CHARS],
    )
    if item_ids:
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


@router.patch("/projects/{project_id}/shortlist/{item_id}", response_model=ShortlistItemResponse)
async def patch_shortlist_item(
    project_id: str,
    item_id: str,
    body: ShortlistUpdateRequest,
    projects: ProjectRepository = Depends(get_project_repository),
    shortlist: ShortlistRepository = Depends(get_shortlist_repository),
) -> ShortlistItemResponse:
    """Edit an idea's title, summary, source or notes. 404 unknown item, 409 removed item, 422 blank title."""
    await _project_or_404(project_id, projects)
    try:
        item = await update_item(project_id, item_id, shortlist, **body.model_dump(exclude_unset=True))
    except ShortlistItemNotFoundError:
        raise HTTPException(status_code=404, detail=f"Shortlist item not found: {item_id}")
    except ShortlistItemUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
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
    tenant_repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
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
    try:
        tenant_defaults = await resolve_defaults(tenant_repo, PLATFORM_USER_ID, settings)
    except Exception:
        tenant_defaults = {}
    return RunContextResponse(
        run_id=run.run_id,
        name=run.name,
        status=run.status,
        created_at=run.created_at,
        project=_project_response(project),
        items=[_item_response(item) for item in items],
        # The run's own stored title and points win: they hold a title typed at creation,
        # and are all there is for a run started without an idea.
        idea_title=str(run.inputs.get("idea_title") or context["idea_title"]),
        supporting_points=list(run.inputs.get("supporting_points") or context["supporting_points"]),
        voice_source="uploaded" if run.inputs.get("voice_source") == "uploaded" else "generated",
        language=str(run.inputs.get("language") or "en"),
        format=run.inputs.get("aspect_ratio"),
        brief="; ".join(run.inputs.get("supporting_points") or []),
        tenant_defaults=tenant_defaults,
    )
