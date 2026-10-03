"""Tests for P12-S1: projects data model + API.

Covers:
- Migration 0002: listed after 0001, creates the tables/columns, idempotent statements only
- create_project / update_project domain functions (happy path + blank-name failure)
- create_run: defaults to the default project; an empty project_id is rejected
- register_existing_run / archive_run
- InMemoryRunRepository.list_for_project / count_by_project
- Postgres repositories: SQL shape and row mapping against a mocked pool
- Routes: project CRUD, project-scoped run list, run import
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import cf_platform.core.migrations as migrations
from cf_platform.core.postgres_project_repos import PostgresProjectRepository
from cf_platform.core.postgres_repos import PostgresRunRepository
from cf_platform.core.projects import (
    InMemoryProjectRepository,
    Project,
    ProjectNotFoundError,
    create_project,
    update_project,
)
from cf_platform.core.run_manager import (
    InMemoryRunRepository,
    RunNotFoundError,
    archive_run,
    create_run,
    register_existing_run,
)
from cf_platform.core.schemas import DEFAULT_PROJECT_ID
from tests.cf_platform.p12_helpers import p12_env

_MIGRATION = "0002_projects_shortlist.sql"


def _mock_pool(fetchone=None, fetchall=None):
    """Build a MagicMock AsyncConnectionPool whose cursor returns fetchone/fetchall."""
    cursor = AsyncMock()
    cursor.fetchone.return_value = fetchone
    cursor.fetchall.return_value = fetchall or []
    conn = MagicMock()
    conn.cursor.return_value.__aenter__.return_value = cursor
    conn.cursor.return_value.__aexit__.return_value = None
    conn.commit = AsyncMock()
    pool = MagicMock()
    pool.closed = False
    pool.connection.return_value.__aenter__.return_value = conn
    pool.connection.return_value.__aexit__.return_value = None
    return pool, cursor, conn


class TestMigration0002:
    def _sql(self) -> str:
        """Return the text of migration 0002."""
        return (migrations.MIGRATIONS_DIR / _MIGRATION).read_text()

    def test_listed_after_init(self):
        """0002 is picked up by the runner and sorts after 0001_init.sql."""
        names = [f.name for f in migrations.list_migrations()]
        assert names.index(_MIGRATION) == names.index("0001_init.sql") + 1

    def test_creates_tables_and_run_columns(self):
        """It creates the three tables and adds the project columns to runs."""
        sql = self._sql()
        for table in ("projects", "shortlist_items", "run_shortlist_items"):
            assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
        for column in ("tenant_id", "project_id", "name", "archived_at"):
            assert f"ALTER TABLE runs ADD COLUMN IF NOT EXISTS {column}" in sql

    def test_every_new_table_carries_tenant_id(self):
        """projects and shortlist_items both declare tenant_id NOT NULL (D092)."""
        sql = self._sql()
        assert sql.count("tenant_id          TEXT NOT NULL") + sql.count("tenant_id        TEXT NOT NULL") == 2

    def test_default_project_backfill(self):
        """A default project is inserted and existing runs default into it."""
        sql = self._sql()
        assert "VALUES ('default', 'operator', 'Default project')" in sql
        assert "ON CONFLICT (project_id) DO NOTHING" in sql
        assert "project_id TEXT NOT NULL DEFAULT 'default'" in sql
        assert DEFAULT_PROJECT_ID == "default"

    def test_statements_are_rerunnable(self):
        """No bare CREATE TABLE / CREATE INDEX / ADD COLUMN — the file can be applied twice."""
        for line in self._sql().splitlines():
            stripped = line.strip()
            if stripped.startswith("CREATE TABLE") or stripped.startswith("CREATE INDEX"):
                assert "IF NOT EXISTS" in stripped, stripped
            if "ADD COLUMN" in stripped:
                assert "ADD COLUMN IF NOT EXISTS" in stripped, stripped

    def test_discovery_method_check_constraint(self):
        """shortlist_items restricts discovery_method to the three known methods."""
        assert "discovery_method IN ('manual', 'trend', 'competitor')" in self._sql()


class TestProjectFunctions:
    @pytest.mark.asyncio
    async def test_in_memory_repo_is_seeded_with_default_project(self):
        """A fresh in-memory repository holds the default project, like a migrated database."""
        repo = InMemoryProjectRepository("operator")
        project = await repo.get(DEFAULT_PROJECT_ID)
        assert project.tenant_id == "operator"

    @pytest.mark.asyncio
    async def test_create_project_persists_and_trims(self):
        """create_project stores a trimmed name/niche under the tenant."""
        repo = InMemoryProjectRepository("operator")
        project = await create_project("operator", "  Housing  ", repo, niche=" housing economics ")
        assert project.name == "Housing"
        assert project.niche == "housing economics"
        assert project.tenant_id == "operator"
        assert await repo.get(project.project_id) == project

    @pytest.mark.asyncio
    async def test_create_project_rejects_blank_name(self):
        """A blank name raises ValueError and nothing is stored."""
        repo = InMemoryProjectRepository("operator")
        with pytest.raises(ValueError):
            await create_project("operator", "   ", repo)
        assert len(await repo.list_projects("operator")) == 1  # only the default project

    @pytest.mark.asyncio
    async def test_update_project_changes_only_supplied_fields(self):
        """update_project leaves omitted fields untouched."""
        repo = InMemoryProjectRepository("operator")
        project = await create_project("operator", "Housing", repo, niche="housing", config={"a": 1})
        updated = await update_project(project.project_id, repo, niche="rents")
        assert updated.niche == "rents"
        assert updated.name == "Housing"
        assert updated.config == {"a": 1}

    @pytest.mark.asyncio
    async def test_update_project_archive_and_unarchive(self):
        """archived=True sets archived_at and hides the project; False restores it."""
        repo = InMemoryProjectRepository("operator")
        project = await create_project("operator", "Housing", repo)
        archived = await update_project(project.project_id, repo, archived=True)
        assert archived.archived_at is not None
        assert project.project_id not in [p.project_id for p in await repo.list_projects("operator")]
        restored = await update_project(project.project_id, repo, archived=False)
        assert restored.archived_at is None

    @pytest.mark.asyncio
    async def test_update_unknown_project_raises(self):
        """update_project raises ProjectNotFoundError for an unknown id."""
        with pytest.raises(ProjectNotFoundError):
            await update_project("missing", InMemoryProjectRepository("operator"), name="x")


class TestRunsBelongToProjects:
    @pytest.mark.asyncio
    async def test_create_run_defaults_to_default_project(self):
        """Existing callers that name no project get the default project and a tenant."""
        run = await create_run("operator", "idea_to_script", {}, InMemoryRunRepository())
        assert run.project_id == DEFAULT_PROJECT_ID
        assert run.tenant_id == "operator"

    @pytest.mark.asyncio
    async def test_create_run_without_project_is_rejected(self):
        """An empty project_id raises ValueError and stores nothing."""
        repo = InMemoryRunRepository()
        with pytest.raises(ValueError):
            await create_run("operator", "studio", {}, repo, project_id="")
        assert await repo.list_runs() == []

    @pytest.mark.asyncio
    async def test_list_for_project_excludes_other_projects_and_archived(self):
        """A project's run list holds only its own, non-archived runs."""
        repo = InMemoryRunRepository()
        mine = await create_run("operator", "studio", {}, repo, project_id="p1", name="mine")
        gone = await create_run("operator", "studio", {}, repo, project_id="p1")
        await create_run("operator", "studio", {}, repo, project_id="p2")
        await archive_run(gone.run_id, repo)

        assert [r.run_id for r in await repo.list_for_project("p1")] == [mine.run_id]
        assert await repo.count_by_project() == {"p1": 1, "p2": 1}

    @pytest.mark.asyncio
    async def test_archive_unknown_run_raises(self):
        """archive_run raises RunNotFoundError for an unknown id."""
        with pytest.raises(RunNotFoundError):
            await archive_run("missing", InMemoryRunRepository())

    @pytest.mark.asyncio
    async def test_register_existing_run_creates_once(self):
        """A browser-only run gets a row; registering it again changes nothing."""
        repo = InMemoryRunRepository()
        created_at = datetime(2026, 7, 1, tzinfo=UTC)
        run, created = await register_existing_run(
            "abc-123", "operator", DEFAULT_PROJECT_ID, repo, name="Old run", created_at=created_at
        )
        assert created is True
        assert (run.block, run.name, run.created_at) == ("studio", "Old run", created_at)

        again, created_again = await register_existing_run("abc-123", "operator", "other-project", repo)
        assert created_again is False
        assert again.project_id == DEFAULT_PROJECT_ID  # never moved between projects


class TestPostgresRepositories:
    @pytest.mark.asyncio
    async def test_run_save_writes_project_columns(self):
        """PostgresRunRepository.save persists tenant_id (falling back to user_id) and project_id."""
        pool, cursor, _ = _mock_pool()
        run = await create_run("operator", "studio", {}, InMemoryRunRepository(), project_id="p1", name="n")
        await PostgresRunRepository(pool).save(run.model_copy(update={"tenant_id": None}))

        sql, params = cursor.execute.call_args[0]
        assert "tenant_id, project_id, name, archived_at" in sql
        assert params[8:] == ("operator", "p1", "n", None)

    @pytest.mark.asyncio
    async def test_run_list_for_project_filters_in_sql(self):
        """list_for_project scopes by project_id and drops archived rows, newest first."""
        pool, cursor, _ = _mock_pool(fetchall=[])
        assert await PostgresRunRepository(pool).list_for_project("p1") == []
        sql, params = cursor.execute.call_args[0]
        assert "WHERE project_id = %s AND archived_at IS NULL" in sql
        assert "ORDER BY created_at DESC" in sql
        assert params == ("p1",)

    @pytest.mark.asyncio
    async def test_project_save_upserts(self):
        """PostgresProjectRepository.save issues an INSERT .. ON CONFLICT (project_id) DO UPDATE."""
        pool, cursor, conn = _mock_pool()
        now = datetime.now(UTC)
        project = Project(project_id="p1", tenant_id="operator", name="Housing", created_at=now, updated_at=now)
        assert await PostgresProjectRepository(pool).save(project) == project
        sql = cursor.execute.call_args[0][0]
        assert "INSERT INTO projects" in sql
        assert "ON CONFLICT (project_id) DO UPDATE" in sql
        conn.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_project_get_maps_row_and_raises_when_missing(self):
        """get() maps a row into a Project and raises ProjectNotFoundError on no row."""
        now = datetime.now(UTC)
        row = ("p1", "operator", "Housing", "housing", {"a": 1}, None, None, now, now)
        pool, _, _ = _mock_pool(fetchone=row)
        project = await PostgresProjectRepository(pool).get("p1")
        assert (project.name, project.config) == ("Housing", {"a": 1})

        pool, _, _ = _mock_pool(fetchone=None)
        with pytest.raises(ProjectNotFoundError):
            await PostgresProjectRepository(pool).get("missing")


class TestProjectRoutes:
    def test_list_contains_default_project(self):
        """GET /platform/projects returns the default project on a fresh install."""
        with p12_env() as env:
            r = env.client.get("/platform/projects")
            assert r.status_code == 200
            assert [p["project_id"] for p in r.json()] == [DEFAULT_PROJECT_ID]

    def test_create_read_update(self):
        """POST, GET and PATCH round-trip name, niche and config."""
        with p12_env() as env:
            pid = env.create_project("Housing", "housing economics")
            assert env.client.get(f"/platform/projects/{pid}").json()["niche"] == "housing economics"

            r = env.client.patch(
                f"/platform/projects/{pid}", json={"name": "Housing 2", "config": {"run_defaults": {"aspect_ratio": "16:9"}}}
            )
            assert r.status_code == 200
            body = r.json()
            assert body["name"] == "Housing 2"
            assert body["niche"] == "housing economics"  # untouched
            assert body["config"]["run_defaults"]["aspect_ratio"] == "16:9"

    def test_archive_hides_project_from_list(self):
        """PATCH archived=true removes the project from the default list."""
        with p12_env() as env:
            pid = env.create_project()
            assert env.client.patch(f"/platform/projects/{pid}", json={"archived": True}).json()["archived"] is True
            assert pid not in [p["project_id"] for p in env.client.get("/platform/projects").json()]
            listed = env.client.get("/platform/projects", params={"include_archived": True}).json()
            assert pid in [p["project_id"] for p in listed]

    def test_blank_name_rejected(self):
        """A blank or whitespace-only name is a 422."""
        with p12_env() as env:
            assert env.client.post("/platform/projects", json={"name": ""}).status_code == 422
            assert env.client.post("/platform/projects", json={"name": "   "}).status_code == 422

    def test_unknown_project_is_404(self):
        """Reading, updating or listing runs of an unknown project is a 404."""
        with p12_env() as env:
            assert env.client.get("/platform/projects/nope").status_code == 404
            assert env.client.patch("/platform/projects/nope", json={"name": "x"}).status_code == 404
            assert env.client.get("/platform/projects/nope/runs").status_code == 404

    @pytest.mark.asyncio
    async def test_project_run_list_is_scoped_and_newest_first(self):
        """GET /projects/{id}/runs returns only that project's runs, newest first, with status + date."""
        with p12_env() as env:
            pid = env.create_project()
            other = env.create_project("Other")
            older = await create_run("operator", "studio", {}, env.runs, project_id=pid, name="older")
            newer = await create_run("operator", "studio", {}, env.runs, project_id=pid, name="newer")
            await create_run("operator", "studio", {}, env.runs, project_id=other)

            runs = env.client.get(f"/platform/projects/{pid}/runs").json()
            assert [r["run_id"] for r in runs] == [newer.run_id, older.run_id]
            assert runs[0]["status"] == "created" and runs[0]["created_at"]

            counts = {p["project_id"]: p["run_count"] for p in env.client.get("/platform/projects").json()}
            assert counts[pid] == 2 and counts[other] == 1

    def test_run_cannot_be_created_without_a_project(self):
        """There is no project-less creation route, and an unknown project is rejected."""
        with p12_env() as env:
            assert env.client.post("/platform/projects/nope/runs", json={"item_ids": ["x"]}).status_code == 404
            assert env.client.post("/platform/runs", json={"item_ids": ["x"]}).status_code == 405

    def test_import_registers_local_runs_once(self):
        """Browser-only runs land in the project; a second import adds nothing."""
        with p12_env() as env:
            payload = {"runs": [{"id": "aaaa-1111", "name": "Old A", "ts": 1750000000000}, {"id": "bbbb-2222"}]}
            first = env.client.post(f"/platform/projects/{DEFAULT_PROJECT_ID}/runs/import", json=payload)
            assert first.json() == {"imported": 2, "already_known": 0}
            second = env.client.post(f"/platform/projects/{DEFAULT_PROJECT_ID}/runs/import", json=payload)
            assert second.json() == {"imported": 0, "already_known": 2}

            runs = env.client.get(f"/platform/projects/{DEFAULT_PROJECT_ID}/runs").json()
            assert {r["run_id"]: r["name"] for r in runs} == {"aaaa-1111": "Old A", "bbbb-2222": ""}

    def test_import_rejects_malformed_run_id(self):
        """A run id that could not have come from Studio is a 422."""
        with p12_env() as env:
            r = env.client.post(
                f"/platform/projects/{DEFAULT_PROJECT_ID}/runs/import", json={"runs": [{"id": "../etc/passwd"}]}
            )
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_archive_run_drops_it_from_the_list(self):
        """DELETE /projects/{id}/runs/{run_id} hides the run; another project's run is a 404."""
        with p12_env() as env:
            pid = env.create_project()
            run = await create_run("operator", "studio", {}, env.runs, project_id=pid)
            foreign = await create_run("operator", "studio", {}, env.runs, project_id=DEFAULT_PROJECT_ID)

            assert env.client.delete(f"/platform/projects/{pid}/runs/{foreign.run_id}").status_code == 404
            assert env.client.delete(f"/platform/projects/{pid}/runs/{run.run_id}").status_code == 204
            assert env.client.get(f"/platform/projects/{pid}/runs").json() == []
            assert (await env.runs.get(run.run_id)).archived_at is not None  # row kept
