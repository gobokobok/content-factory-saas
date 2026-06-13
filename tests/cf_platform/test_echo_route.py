"""Tests for POST /platform/echo — end-to-end smoke (P1-S6)."""

import pytest
from fastapi.testclient import TestClient

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, read_artifact
from cf_platform.interfaces.api import (
    get_artifact_storage,
    get_execution_repository,
    get_run_repository,
)
from src.config import Settings, get_settings
from src.main import app

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


@pytest.fixture
def client():
    """TestClient with valid legacy settings and an in-memory ArtifactStorage for /platform/echo."""
    storage = InMemoryArtifactStorage()
    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(VALID_ENV)
    app.dependency_overrides[get_artifact_storage] = lambda: storage
    test_client = TestClient(app)
    test_client.echo_storage = storage
    yield test_client
    app.dependency_overrides.pop(get_settings, None)
    app.dependency_overrides.pop(get_artifact_storage, None)


class TestEchoRoute:
    def test_returns_run_id_and_artifact_key(self, client):
        """POST /platform/echo returns a run_id and an R2 artifact key for the echo worker."""
        response = client.post("/platform/echo", json={"text": "hello"})

        assert response.status_code == 200
        body = response.json()
        assert "run_id" in body
        assert body["artifact_key"].startswith(f"users/operator/runs/{body['run_id']}/echo/echo@v")

    @pytest.mark.asyncio
    async def test_artifact_body_and_lineage_match_input(self, client):
        """The persisted artifact body echoes the request text and carries echo worker lineage."""
        response = client.post("/platform/echo", json={"text": "hello world"})
        body = response.json()

        artifact, artifact_body = await read_artifact(client.echo_storage, body["artifact_key"])

        assert artifact_body == {"message": "hello world"}
        assert artifact.lineage.worker == "echo"
        assert artifact.lineage.run_id == body["run_id"]

    @pytest.mark.asyncio
    async def test_records_exactly_one_worker_execution(self, client):
        """Exactly one WorkerExecution is recorded for the echo run, with the artifact's r2_key."""
        response = client.post("/platform/echo", json={"text": "hello"})
        body = response.json()

        executions_repo = get_execution_repository()
        executions = await executions_repo.list_for_run(body["run_id"])

        assert len(executions) == 1
        assert executions[0].worker == "echo"
        assert executions[0].artifact_r2_key == body["artifact_key"]

    @pytest.mark.asyncio
    async def test_run_record_transitions_to_complete(self, client):
        """The RunRecord for the echo run reaches status 'complete'."""
        response = client.post("/platform/echo", json={"text": "hello"})
        body = response.json()

        run_repo = get_run_repository()
        run = await run_repo.get(body["run_id"])

        assert run.status == "complete"
        assert run.block == "echo"
