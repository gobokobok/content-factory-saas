"""Projects — the container runs and the shortlist belong to (Sprint P12, D092).

Hierarchy: Tenant -> Project -> Run. A project holds the niche, content/style
defaults (`config`) and, from P15/P16, research configuration and a default
publishing channel. There is one tenant for now — the single operator — but
every row carries `tenant_id` so multi-tenancy is not a later schema migration.

Persistence sits behind the `ProjectRepository` Protocol, mirroring
cf_platform/core/run_manager.py: `InMemoryProjectRepository` is the fallback when
DATABASE_URL is unset (D048), `PostgresProjectRepository` (postgres_project_repos.py)
the durable implementation. The functions below are pure async and take their
repository explicitly (D040).
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel

from cf_platform.core.schemas import DEFAULT_PROJECT_ID

DEFAULT_PROJECT_NAME = "Default project"

# Sentinel for "field not supplied" in update_project, so None stays a real value.
_UNSET: Any = object()


class ProjectNotFoundError(Exception):
    """Raised when a project_id has no corresponding Project in the repository."""


class Project(BaseModel):
    """One project: niche, defaults for new runs, and the owner of a shortlist and runs."""

    project_id: str
    tenant_id: str
    name: str
    niche: str = ""
    config: dict[str, Any] = {}
    default_channel_id: str | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProjectRepository(Protocol):
    """Persistence interface for Project storage — in-memory or Postgres (D048)."""

    async def save(self, project: Project) -> Project:
        """Insert or overwrite the Project for project.project_id. Returns the stored record."""
        ...

    async def get(self, project_id: str) -> Project:
        """Return the Project for project_id. Raises ProjectNotFoundError if absent."""
        ...

    async def list_projects(self, tenant_id: str, include_archived: bool = False) -> list[Project]:
        """Return tenant_id's projects, most recently created first."""
        ...


def build_default_project(tenant_id: str) -> Project:
    """Return the default project record — the home of every run created before P12."""
    now = datetime.now(UTC)
    return Project(
        project_id=DEFAULT_PROJECT_ID,
        tenant_id=tenant_id,
        name=DEFAULT_PROJECT_NAME,
        created_at=now,
        updated_at=now,
    )


class InMemoryProjectRepository:
    """In-memory ProjectRepository — process-local, not durable.

    Seeded with the default project so it matches a migrated database, where
    migration 0002 always creates one.
    """

    def __init__(self, tenant_id: str) -> None:
        """Initialize the store holding only the default project for tenant_id."""
        default = build_default_project(tenant_id)
        self._projects: dict[str, Project] = {default.project_id: default}

    async def save(self, project: Project) -> Project:
        """Insert or overwrite the Project for project.project_id. Returns the stored record."""
        self._projects[project.project_id] = project
        return project

    async def get(self, project_id: str) -> Project:
        """Return the Project for project_id. Raises ProjectNotFoundError if absent."""
        try:
            return self._projects[project_id]
        except KeyError:
            raise ProjectNotFoundError(f"Project not found: {project_id}") from None

    async def list_projects(self, tenant_id: str, include_archived: bool = False) -> list[Project]:
        """Return tenant_id's projects, most recently created first."""
        projects = [
            project
            for project in self._projects.values()
            if project.tenant_id == tenant_id and (include_archived or project.archived_at is None)
        ]
        return sorted(projects, key=lambda project: project.created_at, reverse=True)


async def create_project(
    tenant_id: str,
    name: str,
    repository: ProjectRepository,
    *,
    niche: str = "",
    config: dict[str, Any] | None = None,
) -> Project:
    """Create a project for tenant_id, persist it via repository, and return it.

    Raises ValueError when name is blank.
    """
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("A project needs a name")
    now = datetime.now(UTC)
    project = Project(
        project_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=clean_name,
        niche=niche.strip(),
        config=config or {},
        created_at=now,
        updated_at=now,
    )
    return await repository.save(project)


async def update_project(
    project_id: str,
    repository: ProjectRepository,
    *,
    name: str = _UNSET,
    niche: str = _UNSET,
    config: dict[str, Any] = _UNSET,
    archived: bool = _UNSET,
) -> Project:
    """Apply the supplied fields to the project and persist it. Omitted fields are untouched.

    `config` replaces the stored config wholesale. `archived` sets or clears
    `archived_at`. Raises ProjectNotFoundError for an unknown project_id and
    ValueError when name is supplied but blank.
    """
    project = await repository.get(project_id)
    changes: dict[str, Any] = {}
    if name is not _UNSET:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("A project needs a name")
        changes["name"] = clean_name
    if niche is not _UNSET:
        changes["niche"] = niche.strip()
    if config is not _UNSET:
        changes["config"] = config
    if archived is not _UNSET:
        if archived and project.archived_at is None:
            changes["archived_at"] = datetime.now(UTC)
        elif not archived:
            changes["archived_at"] = None
    if not changes:
        return project
    changes["updated_at"] = datetime.now(UTC)
    return await repository.save(project.model_copy(update=changes))
