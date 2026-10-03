"""Postgres-backed repositories for projects and the shortlist (Sprint P12, D092, D094).

Persist the rows defined in cf_platform/db/migrations/0002_projects_shortlist.sql:
`projects`, `shortlist_items`, `run_shortlist_items`. Each implements the Protocol
declared alongside its in-memory counterpart (`ProjectRepository` in projects.py,
`ShortlistRepository` in shortlist.py) so they are drop-in swappable — selected in
cf_platform/interfaces/dependencies.py when `DATABASE_URL` is configured (D048).
"""

from datetime import datetime

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from cf_platform.core.postgres_repos import _ensure_open
from cf_platform.core.projects import Project, ProjectNotFoundError
from cf_platform.core.shortlist import ShortlistItem, ShortlistItemNotFoundError

_PROJECT_COLUMNS = (
    "project_id, tenant_id, name, niche, config, default_channel_id, archived_at, created_at, updated_at"
)

_ITEM_COLUMNS = (
    "item_id, tenant_id, project_id, title, summary, discovery_method, source, evidence, kpis, "
    "research_run_id, discovered_at, removed_at, created_at"
)


def _project_from_row(row: tuple) -> Project:
    """Build a Project from a row selected with _PROJECT_COLUMNS."""
    project_id, tenant_id, name, niche, config, default_channel_id, archived_at, created_at, updated_at = row
    return Project(
        project_id=project_id,
        tenant_id=tenant_id,
        name=name,
        niche=niche,
        config=config,
        default_channel_id=default_channel_id,
        archived_at=archived_at,
        created_at=created_at,
        updated_at=updated_at,
    )


def _item_from_row(row: tuple) -> ShortlistItem:
    """Build a ShortlistItem from a row selected with _ITEM_COLUMNS."""
    (
        item_id,
        tenant_id,
        project_id,
        title,
        summary,
        discovery_method,
        source,
        evidence,
        kpis,
        research_run_id,
        discovered_at,
        removed_at,
        created_at,
    ) = row
    return ShortlistItem(
        item_id=item_id,
        tenant_id=tenant_id,
        project_id=project_id,
        title=title,
        summary=summary,
        discovery_method=discovery_method,
        source=source,
        evidence=evidence,
        kpis=kpis,
        research_run_id=research_run_id,
        discovered_at=discovered_at,
        removed_at=removed_at,
        created_at=created_at,
    )


class PostgresProjectRepository:
    """Postgres-backed ProjectRepository — upserts into the `projects` table by `project_id`."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Store the shared connection pool."""
        self._pool = pool

    async def save(self, project: Project) -> Project:
        """Upsert the Project row keyed on project_id. Returns the stored record."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO projects (project_id, tenant_id, name, niche, config, default_channel_id,
                                          archived_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (project_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        niche = EXCLUDED.niche,
                        config = EXCLUDED.config,
                        default_channel_id = EXCLUDED.default_channel_id,
                        archived_at = EXCLUDED.archived_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        project.project_id,
                        project.tenant_id,
                        project.name,
                        project.niche,
                        Jsonb(project.config),
                        project.default_channel_id,
                        project.archived_at,
                        project.created_at,
                        project.updated_at,
                    ),
                )
            await conn.commit()
        return project

    async def get(self, project_id: str) -> Project:
        """Return the Project for project_id. Raises ProjectNotFoundError if absent."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT {_PROJECT_COLUMNS} FROM projects WHERE project_id = %s", (project_id,)
                )
                row = await cur.fetchone()
        if row is None:
            raise ProjectNotFoundError(f"Project not found: {project_id}")
        return _project_from_row(row)

    async def list_projects(self, tenant_id: str, include_archived: bool = False) -> list[Project]:
        """Return tenant_id's projects, most recently created first."""
        archived_clause = "" if include_archived else "AND archived_at IS NULL"
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    SELECT {_PROJECT_COLUMNS} FROM projects
                    WHERE tenant_id = %s {archived_clause}
                    ORDER BY created_at DESC
                    """,
                    (tenant_id,),
                )
                rows = await cur.fetchall()
        return [_project_from_row(row) for row in rows]


class PostgresShortlistRepository:
    """Postgres-backed ShortlistRepository — `shortlist_items` plus the `run_shortlist_items` links.

    Exposes no bulk replace or clear (D094): items are inserted one at a time and
    removed one at a time via a soft delete.
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Store the shared connection pool."""
        self._pool = pool

    async def add(self, item: ShortlistItem) -> ShortlistItem:
        """Insert item. Returns the stored record."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    INSERT INTO shortlist_items ({_ITEM_COLUMNS})
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        item.item_id,
                        item.tenant_id,
                        item.project_id,
                        item.title,
                        item.summary,
                        item.discovery_method,
                        item.source,
                        Jsonb(item.evidence),
                        Jsonb(item.kpis),
                        item.research_run_id,
                        item.discovered_at,
                        item.removed_at,
                        item.created_at,
                    ),
                )
            await conn.commit()
        return item

    async def get(self, item_id: str) -> ShortlistItem:
        """Return the item for item_id, removed or not. Raises ShortlistItemNotFoundError if absent."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"SELECT {_ITEM_COLUMNS} FROM shortlist_items WHERE item_id = %s", (item_id,))
                row = await cur.fetchone()
        if row is None:
            raise ShortlistItemNotFoundError(f"Shortlist item not found: {item_id}")
        return _item_from_row(row)

    async def list_for_project(self, project_id: str, include_removed: bool = False) -> list[ShortlistItem]:
        """Return project_id's items, most recently discovered first."""
        removed_clause = "" if include_removed else "AND removed_at IS NULL"
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    SELECT {_ITEM_COLUMNS} FROM shortlist_items
                    WHERE project_id = %s {removed_clause}
                    ORDER BY discovered_at DESC
                    """,
                    (project_id,),
                )
                rows = await cur.fetchall()
        return [_item_from_row(row) for row in rows]

    async def mark_removed(self, item_id: str, removed_at: datetime) -> ShortlistItem:
        """Set removed_at on the item. Raises ShortlistItemNotFoundError if absent."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    UPDATE shortlist_items SET removed_at = %s
                    WHERE item_id = %s
                    RETURNING {_ITEM_COLUMNS}
                    """,
                    (removed_at, item_id),
                )
                row = await cur.fetchone()
            await conn.commit()
        if row is None:
            raise ShortlistItemNotFoundError(f"Shortlist item not found: {item_id}")
        return _item_from_row(row)

    async def link_run(self, run_id: str, item_ids: list[str]) -> None:
        """Record that run_id was created from item_ids, keeping their order."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                for position, item_id in enumerate(item_ids):
                    await cur.execute(
                        """
                        INSERT INTO run_shortlist_items (run_id, item_id, position)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (run_id, item_id) DO NOTHING
                        """,
                        (run_id, item_id, position),
                    )
            await conn.commit()

    async def items_for_run(self, run_id: str) -> list[ShortlistItem]:
        """Return the items run_id was created from, in the order they were selected."""
        columns = ", ".join(f"i.{column.strip()}" for column in _ITEM_COLUMNS.split(","))
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    SELECT {columns} FROM run_shortlist_items l
                    JOIN shortlist_items i ON i.item_id = l.item_id
                    WHERE l.run_id = %s
                    ORDER BY l.position
                    """,
                    (run_id,),
                )
                rows = await cur.fetchall()
        return [_item_from_row(row) for row in rows]

    async def run_counts(self, project_id: str) -> dict[str, int]:
        """Return {item_id: number of runs created from it} for project_id's items that have runs."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT l.item_id, COUNT(*) FROM run_shortlist_items l
                    JOIN shortlist_items i ON i.item_id = l.item_id
                    WHERE i.project_id = %s
                    GROUP BY l.item_id
                    """,
                    (project_id,),
                )
                rows = await cur.fetchall()
        return {item_id: count for item_id, count in rows}
