"""Integration tests for P12 against a real Postgres (excluded from CI: `-m "not integration"`).

Mocks cannot tell whether the SQL in migration 0002 or the P12 repositories is valid,
so these run it for real. Set CF_TEST_DATABASE_URL to a throwaway database, e.g.

    createdb cf_p12_test
    CF_TEST_DATABASE_URL=postgresql:///cf_p12_test pytest tests/integration/test_p12_migration_postgres.py -m integration

Each test works inside its own schema, dropped afterwards, so the database is left clean.

Covers:
- 0002 applies on an empty database (after 0001) and is re-runnable
- 0002 applies on a populated database: existing runs land in the default project
- A run cannot be stored with an unknown project
- Project, shortlist and run repositories round-trip through real SQL
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import psycopg
import pytest
import pytest_asyncio
from psycopg_pool import AsyncConnectionPool

from cf_platform.core.migrations import MIGRATIONS_DIR
from cf_platform.core.postgres_project_repos import PostgresProjectRepository, PostgresShortlistRepository
from cf_platform.core.postgres_repos import PostgresRunRepository
from cf_platform.core.projects import create_project
from cf_platform.core.run_manager import archive_run, create_run
from cf_platform.core.schemas import DEFAULT_PROJECT_ID
from cf_platform.core.shortlist import add_manual_item, remove_item

DATABASE_URL = os.environ.get("CF_TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DATABASE_URL, reason="CF_TEST_DATABASE_URL is not set"),
]

_INIT = (MIGRATIONS_DIR / "0001_init.sql").read_text()
_P12 = (MIGRATIONS_DIR / "0002_projects_shortlist.sql").read_text()


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[AsyncConnectionPool]:
    """Yield a pool whose connections live in a fresh, private schema with 0001 applied."""
    schema = f"p12_{uuid.uuid4().hex[:12]}"
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as admin:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
    test_pool = AsyncConnectionPool(
        conninfo=DATABASE_URL, open=False, kwargs={"options": f"-c search_path={schema}"}
    )
    await test_pool.open()
    try:
        async with test_pool.connection() as conn:
            await conn.execute(_INIT)
            await conn.commit()
        yield test_pool
    finally:
        await test_pool.close()
        async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as admin:
            await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')


async def _apply_p12(pool: AsyncConnectionPool) -> None:
    """Apply migration 0002 the way the runner does: one execute, then commit."""
    async with pool.connection() as conn:
        await conn.execute(_P12)
        await conn.commit()


@pytest.mark.asyncio
async def test_applies_on_empty_database_and_is_rerunnable(pool):
    """0002 creates the default project on an empty database and can be applied twice."""
    await _apply_p12(pool)
    await _apply_p12(pool)

    projects = await PostgresProjectRepository(pool).list_projects("operator")
    assert [p.project_id for p in projects] == [DEFAULT_PROJECT_ID]
    assert await PostgresRunRepository(pool).list_runs() == []


@pytest.mark.asyncio
async def test_applies_on_populated_database_and_backfills_runs(pool):
    """Runs that existed before 0002 are assigned to the default project and keep their data."""
    async with pool.connection() as conn:
        for run_id in ("old-1", "old-2"):
            await conn.execute(
                "INSERT INTO runs (run_id, user_id, block, status) VALUES (%s, 'operator', 'idea_to_script', 'complete')",
                (run_id,),
            )
        await conn.commit()

    await _apply_p12(pool)
    await _apply_p12(pool)

    runs = await PostgresRunRepository(pool).list_for_project(DEFAULT_PROJECT_ID)
    assert {r.run_id for r in runs} == {"old-1", "old-2"}
    assert all(r.tenant_id == "operator" and r.status == "complete" for r in runs)
    assert await PostgresRunRepository(pool).count_by_project() == {DEFAULT_PROJECT_ID: 2}


@pytest.mark.asyncio
async def test_run_with_unknown_project_is_rejected(pool):
    """The foreign key refuses a run whose project does not exist."""
    await _apply_p12(pool)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await create_run("operator", "studio", {}, PostgresRunRepository(pool), project_id="no-such-project")


@pytest.mark.asyncio
async def test_repositories_round_trip(pool):
    """Projects, shortlist items, run links and archiving all work through real SQL."""
    await _apply_p12(pool)
    projects, runs, shortlist = (
        PostgresProjectRepository(pool),
        PostgresRunRepository(pool),
        PostgresShortlistRepository(pool),
    )

    project = await create_project(
        "operator", "Housing", projects, niche="housing economics", config={"run_defaults": {"aspect_ratio": "9:16"}}
    )
    assert await projects.get(project.project_id) == project

    first = await add_manual_item("operator", project.project_id, "Rents", shortlist, summary="Supply", notes="timely")
    second = await add_manual_item("operator", project.project_id, "Zoning", shortlist)
    assert [i.item_id for i in await shortlist.list_for_project(project.project_id)] == [second.item_id, first.item_id]
    assert (await shortlist.get(first.item_id)).evidence == {"notes": "timely"}

    run = await create_run(
        "operator", "studio", {"item_ids": [second.item_id, first.item_id]}, runs,
        project_id=project.project_id, name="Zoning + Rents",
    )
    await shortlist.link_run(run.run_id, [second.item_id, first.item_id])
    await shortlist.link_run(run.run_id, [second.item_id])  # duplicate link is a no-op
    assert [i.item_id for i in await shortlist.items_for_run(run.run_id)] == [second.item_id, first.item_id]
    assert await shortlist.run_counts(project.project_id) == {first.item_id: 1, second.item_id: 1}

    await remove_item(project.project_id, first.item_id, shortlist)
    assert [i.item_id for i in await shortlist.list_for_project(project.project_id)] == [second.item_id]
    assert len(await shortlist.items_for_run(run.run_id)) == 2  # the link outlives the removal

    stored = await runs.get(run.run_id)
    assert (stored.project_id, stored.name, stored.tenant_id) == (project.project_id, "Zoning + Rents", "operator")
    assert [r.run_id for r in await runs.list_for_project(project.project_id)] == [run.run_id]
    await archive_run(run.run_id, runs)
    assert await runs.list_for_project(project.project_id) == []


@pytest.mark.asyncio
async def test_discovery_method_is_constrained(pool):
    """An unknown discovery_method is refused by the CHECK constraint."""
    await _apply_p12(pool)
    now = datetime.now(UTC)
    with pytest.raises(psycopg.errors.CheckViolation):
        async with pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO shortlist_items (item_id, tenant_id, project_id, title, discovery_method, discovered_at)
                VALUES ('i1', 'operator', 'default', 'x', 'guess', %s)
                """,
                (now,),
            )
