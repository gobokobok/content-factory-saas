"""Tests for cf_platform/interfaces/api.py and its fault-isolated mount in src/main.py (P1-S1)."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from cf_platform.core.artifact_manager import InMemoryArtifactRepository
from cf_platform.core.postgres_repos import (
    PostgresArtifactRepository,
    PostgresExecutionRepository,
    PostgresRunRepository,
)
from cf_platform.core.run_manager import InMemoryRunRepository
from cf_platform.core.worker_registry import InMemoryExecutionRepository
from cf_platform.interfaces.api import (
    get_artifact_repository,
    get_execution_repository,
    get_graph_checkpointer,
    get_run_repository,
)
from src.config import Settings, get_settings
from src.main import _mount_platform_router, _run_platform_migrations, _setup_platform_checkpointer, app


@pytest.fixture(autouse=True)
def _clear_settings_override():
    """Remove the get_settings dependency override after each test."""
    yield
    app.dependency_overrides.pop(get_settings, None)

VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "fake-account-id",
    "R2_ACCESS_KEY_ID": "fake-access-key",
    "R2_SECRET_ACCESS_KEY": "fake-secret-key",
    "R2_BUCKET_NAME": "content-factory-dev",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "PEXELS_API_KEY": "fake-pexels-key",
    "REPLICATE_API_TOKEN": "fake-replicate-token",
    "FREESOUND_API_KEY": "fake-freesound-key",
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret-key",
}


def _client_with_settings() -> TestClient:
    """Return a TestClient for the main app with valid settings injected via Depends override."""
    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(VALID_ENV)
    return TestClient(app)


class TestPlatformHealthRoute:
    def test_platform_health_returns_200(self):
        """GET /platform/health returns 200 with status ok and a database field."""
        client = _client_with_settings()

        response = client.get("/platform/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] in ("ok", "unavailable")

    def test_platform_health_ok_when_database_unset(self):
        """GET /platform/health reports status ok and database unavailable when DATABASE_URL is unset (D048)."""
        client = _client_with_settings()

        response = client.get("/platform/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "unavailable"}

    def test_legacy_route_unaffected(self):
        """Mounting the platform router does not break an existing legacy route."""
        client = _client_with_settings()

        response = client.get("/health")

        assert response.status_code == 200


class TestMountPlatformRouterFaultIsolation:
    def test_mount_succeeds_registers_route(self):
        """Normal mount registers /platform/health on a fresh app."""
        fresh_app = FastAPI()

        _mount_platform_router(fresh_app)

        client = TestClient(fresh_app)
        response = client.get("/platform/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_mount_failure_is_swallowed(self):
        """An import failure in cf_platform.interfaces.api does not raise."""
        fresh_app = FastAPI()

        with patch.dict(sys.modules, {"cf_platform.interfaces.api": None}):
            _mount_platform_router(fresh_app)

        client = TestClient(fresh_app)
        response = client.get("/platform/health")
        assert response.status_code == 404


class TestRunPlatformMigrationsFaultIsolation:
    @pytest.mark.asyncio
    async def test_calls_run_migrations_with_database_url(self):
        """_run_platform_migrations calls run_migrations with the platform's DATABASE_URL."""
        with patch(
            "cf_platform.core.migrations.run_migrations", new_callable=AsyncMock
        ) as mock_run_migrations:
            mock_run_migrations.return_value = "unavailable"

            await _run_platform_migrations()

        mock_run_migrations.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_swallows_exception(self):
        """A failure in run_migrations is logged and swallowed — never raised."""
        with patch(
            "cf_platform.core.migrations.run_migrations",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db exploded"),
        ):
            await _run_platform_migrations()  # must not raise

    @pytest.mark.asyncio
    async def test_swallows_import_failure(self):
        """An import failure in cf_platform.core.migrations does not raise."""
        with patch.dict(sys.modules, {"cf_platform.core.migrations": None}):
            await _run_platform_migrations()  # must not raise


class TestRepositoryProviderSelection:
    """get_*_repository() picks Postgres-backed repos when DATABASE_URL is set, else in-memory (D048)."""

    def test_returns_in_memory_repos_when_pool_unset(self):
        """With no Postgres pool (DATABASE_URL unset), provider functions return the in-memory singletons."""
        with patch("cf_platform.interfaces.api.get_pool", return_value=None):
            assert isinstance(get_run_repository(), InMemoryRunRepository)
            assert isinstance(get_execution_repository(), InMemoryExecutionRepository)
            assert isinstance(get_artifact_repository(), InMemoryArtifactRepository)

    def test_returns_postgres_repos_when_pool_set(self):
        """With a Postgres pool available (DATABASE_URL set), provider functions return Postgres-backed repos."""
        with patch("cf_platform.interfaces.api.get_pool", return_value=MagicMock()):
            assert isinstance(get_run_repository(), PostgresRunRepository)
            assert isinstance(get_execution_repository(), PostgresExecutionRepository)
            assert isinstance(get_artifact_repository(), PostgresArtifactRepository)


class TestGetGraphCheckpointer:
    """get_graph_checkpointer() picks a Postgres-backed checkpointer when DATABASE_URL is set (D048, P2-S4)."""

    @pytest.mark.asyncio
    async def test_returns_memory_saver_when_database_url_unset(self):
        """With DATABASE_URL unset, get_graph_checkpointer returns a MemorySaver."""
        checkpointer = await get_graph_checkpointer()

        assert isinstance(checkpointer, MemorySaver)

    @pytest.mark.asyncio
    async def test_returns_postgres_saver_when_database_url_set(self):
        """With DATABASE_URL set, get_graph_checkpointer returns an AsyncPostgresSaver."""
        with patch(
            "cf_platform.interfaces.api.get_platform_settings",
            return_value=MagicMock(DATABASE_URL="postgresql://user:pass@localhost/db"),
        ):
            checkpointer = await get_graph_checkpointer()

        assert isinstance(checkpointer, AsyncPostgresSaver)


class TestSetupPlatformCheckpointerFaultIsolation:
    @pytest.mark.asyncio
    async def test_calls_setup_checkpointer_with_checkpointer(self):
        """_setup_platform_checkpointer calls setup_checkpointer with the platform's checkpointer."""
        with patch(
            "cf_platform.core.db.setup_checkpointer", new_callable=AsyncMock
        ) as mock_setup:
            mock_setup.return_value = "ok"

            await _setup_platform_checkpointer()

        mock_setup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_swallows_exception(self):
        """A failure in setup_checkpointer is logged and swallowed — never raised."""
        with patch(
            "cf_platform.core.db.setup_checkpointer",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db exploded"),
        ):
            await _setup_platform_checkpointer()  # must not raise

    @pytest.mark.asyncio
    async def test_swallows_import_failure(self):
        """An import failure in cf_platform.core.db does not raise."""
        with patch.dict(sys.modules, {"cf_platform.core.db": None}):
            await _setup_platform_checkpointer()  # must not raise
