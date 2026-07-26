"""Tests for P-UX1-S3: Metadata stage backend — youtube_metadata worker wired
into Studio's step-by-step flow (previously only reachable via the Telegram
full_pipeline graph).

Covers:
- POST /platform/workers/metadata — happy path, missing-script 404
- GET /platform/studio/runs/{run_id}/metadata — present, absent (404)
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.interfaces.api import get_artifact_storage
from src.config import Settings, get_settings
from src.main import app

_VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "fake",
    "R2_ACCESS_KEY_ID": "fake",
    "R2_SECRET_ACCESS_KEY": "fake",
    "R2_BUCKET_NAME": "fake-bucket",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "PEXELS_API_KEY": "fake-pexels",
    "REPLICATE_API_TOKEN": "fake-replicate",
    "FREESOUND_API_KEY": "fake-freesound",
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret",
}


class TestMetadataWorkerEndpoint:
    """POST /platform/workers/metadata"""

    @pytest.fixture
    def storage(self):
        return InMemoryArtifactStorage()

    @pytest.fixture
    def client(self, storage):
        app.dependency_overrides[get_settings] = lambda: Settings.model_validate(_VALID_ENV)
        app.dependency_overrides[get_artifact_storage] = lambda: storage
        yield TestClient(app, raise_server_exceptions=True)
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_artifact_storage, None)

    @pytest.mark.asyncio
    async def test_happy_path_generates_and_persists_metadata(self, client, storage):
        from cf_platform.workers.script_packager import ScriptArtifact

        script_key = "users/operator/runs/run1/script/script@v1.json"
        await storage.put_json(
            script_key,
            ScriptArtifact(
                idea_title="Why rents keep rising",
                niche="housing economics",
                script="Rents rose again this year.",
                word_count=5,
                generated_at=datetime.now(UTC),
            ).model_dump(mode="json"),
        )

        from cf_platform.core.schemas import WorkerOutput
        from cf_platform.workers.youtube_metadata import YoutubeMetadataArtifact

        fake_artifact = YoutubeMetadataArtifact(
            title="Why Rents Keep Rising",
            description="A look at the data behind rising rents.",
            tags=["housing", "rent"],
            generated_at=datetime.now(UTC),
        )

        async def _fake_worker(state):
            assert state.artifacts["script"] == script_key
            return WorkerOutput(artifact=fake_artifact)

        with patch("cf_platform.workers.youtube_metadata.build_youtube_metadata_worker", return_value=_fake_worker):
            r = client.post("/platform/workers/metadata", json={"run_id": "run1"})

        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "Why Rents Keep Rising"
        assert data["tags"] == ["housing", "rent"]

        get_r = client.get("/platform/studio/runs/run1/metadata")
        assert get_r.status_code == 200
        assert get_r.json()["title"] == "Why Rents Keep Rising"

    def test_missing_script_returns_404(self, client):
        r = client.post("/platform/workers/metadata", json={"run_id": "no-such-run"})
        assert r.status_code == 404
        assert "script" in r.json()["detail"].lower()

    def test_get_metadata_absent_returns_404(self, client):
        r = client.get("/platform/studio/runs/never-generated/metadata")
        assert r.status_code == 404
