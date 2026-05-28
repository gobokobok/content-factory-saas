"""Tests for /runs endpoints."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.exceptions import StorageError
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

FAKE_RUN_ID = f"{date.today().isoformat()}_test-slug"
FAKE_PREFIX = f"runs/{FAKE_RUN_ID}/"


def _make_settings(**overrides) -> Settings:
    """Build a Settings instance from VALID_ENV with optional field overrides."""
    return Settings.model_validate({**VALID_ENV, **overrides})


@pytest.fixture()
def client():
    """TestClient with settings injected."""
    settings = _make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture()
def mock_r2(client):
    """Patch R2Client so no real R2 calls are made. Returns the mock instance."""
    mock_instance = MagicMock()
    mock_instance.create_run_folder.return_value = FAKE_PREFIX
    with patch("src.routes.runs.R2Client", return_value=mock_instance):
        yield mock_instance


class TestCreateRun:
    def test_returns_201_on_success(self, client, mock_r2):
        """POST /runs returns HTTP 201 for a valid slug."""
        response = client.post("/runs", json={"slug": "test-slug"})
        assert response.status_code == 201

    def test_returns_run_id_and_storage_prefix(self, client, mock_r2):
        """Response body contains run_id and storage_prefix."""
        response = client.post("/runs", json={"slug": "test-slug"})
        body = response.json()
        assert body["run_id"] == FAKE_RUN_ID
        assert body["storage_prefix"] == FAKE_PREFIX

    def test_no_drive_folder_id_in_response(self, client, mock_r2):
        """Response does not contain the old drive_folder_id field."""
        response = client.post("/runs", json={"slug": "test-slug"})
        assert "drive_folder_id" not in response.json()

    def test_create_run_folder_called_with_run_id(self, client, mock_r2):
        """R2Client.create_run_folder is called with the constructed run_id."""
        client.post("/runs", json={"slug": "test-slug"})
        mock_r2.create_run_folder.assert_called_once_with(FAKE_RUN_ID)

    def test_r2_client_instantiated_with_settings(self, client):
        """R2Client is constructed with the four R2 ENV vars from settings."""
        mock_instance = MagicMock()
        mock_instance.create_run_folder.return_value = FAKE_PREFIX
        with patch("src.routes.runs.R2Client", return_value=mock_instance) as mock_cls:
            client.post("/runs", json={"slug": "test-slug"})
            mock_cls.assert_called_once_with(
                "fake-account-id", "fake-access-key", "fake-secret-key", "content-factory-dev"
            )

    def test_storage_error_returns_500(self, client, mock_r2):
        """StorageError from R2Client maps to HTTP 500."""
        mock_r2.create_run_folder.side_effect = StorageError("bucket not found")
        response = client.post("/runs", json={"slug": "test-slug"})
        assert response.status_code == 500

    def test_storage_error_detail_in_response(self, client, mock_r2):
        """500 response body contains the StorageError message."""
        mock_r2.create_run_folder.side_effect = StorageError("bucket not found")
        response = client.post("/runs", json={"slug": "test-slug"})
        assert "bucket not found" in response.json()["detail"]


class TestListRuns:
    def test_returns_200_with_empty_list(self, client):
        """GET /runs returns HTTP 200 with empty runs list when no runs exist."""
        mock_instance = MagicMock()
        mock_instance.list_runs.return_value = []
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            response = client.get("/runs")
        assert response.status_code == 200
        assert response.json() == {"runs": []}

    def test_returns_run_summaries(self, client):
        """GET /runs returns RunSummary objects from list_runs."""
        mock_instance = MagicMock()
        mock_instance.list_runs.return_value = [
            {
                "run_id": "2026-05-24_housing-crisis",
                "created_at": "2026-05-24T10:00:00+00:00",
                "steps": {"storyboard": "complete", "asset_manifest": "pending"},
            }
        ]
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            response = client.get("/runs")
        assert response.status_code == 200
        runs = response.json()["runs"]
        assert len(runs) == 1
        assert runs[0]["run_id"] == "2026-05-24_housing-crisis"
        assert runs[0]["steps"]["storyboard"] == "complete"

    def test_returns_multiple_runs_sorted(self, client):
        """GET /runs returns multiple runs (order delegated to list_runs)."""
        mock_instance = MagicMock()
        mock_instance.list_runs.return_value = [
            {
                "run_id": "2026-05-24_run-b",
                "created_at": "2026-05-24T12:00:00+00:00",
                "steps": {"storyboard": "complete"},
            },
            {
                "run_id": "2026-05-23_run-a",
                "created_at": "2026-05-23T08:00:00+00:00",
                "steps": {"storyboard": "pending"},
            },
        ]
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            response = client.get("/runs")
        assert response.status_code == 200
        assert len(response.json()["runs"]) == 2

    def test_storage_error_returns_500(self, client):
        """StorageError from list_runs maps to HTTP 500."""
        mock_instance = MagicMock()
        mock_instance.list_runs.side_effect = StorageError("R2 unreachable")
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            response = client.get("/runs")
        assert response.status_code == 500
        assert "R2 unreachable" in response.json()["detail"]


class TestGetArtifact:
    def _mock_r2(self, client, **method_returns):
        """Patch R2Client and configure method return values."""
        mock_instance = MagicMock()
        for method, value in method_returns.items():
            getattr(mock_instance, method).return_value = value
        return patch("src.routes.runs.R2Client", return_value=mock_instance)

    def test_storyboard_returns_json_content(self, client):
        """storyboard artifact returns JSON content inline."""
        payload = {"scenes": [], "summary": {}}
        mock_instance = MagicMock()
        mock_instance.get_json.return_value = payload
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            response = client.get("/runs/2026-05-24_test/artifact/storyboard")
        assert response.status_code == 200
        body = response.json()
        assert body["step"] == "storyboard"
        assert body["content_type"] == "application/json"
        assert body["content"] == payload
        assert body["url"] is None

    def test_manifest_returns_json_content(self, client):
        """manifest artifact returns JSON content inline."""
        payload = {"run_id": "test", "entries": []}
        mock_instance = MagicMock()
        mock_instance.get_json.return_value = payload
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            response = client.get("/runs/2026-05-24_test/artifact/manifest")
        assert response.status_code == 200
        body = response.json()
        assert body["step"] == "manifest"
        assert body["content_type"] == "application/json"
        assert body["content"] == payload

    def test_ffmpeg_script_returns_text_content(self, client):
        """ffmpeg_script artifact returns text content inline."""
        script_text = "#!/bin/bash\nset -euo pipefail\n"
        mock_instance = MagicMock()
        mock_instance.get_bytes.return_value = script_text.encode("utf-8")
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            response = client.get("/runs/2026-05-24_test/artifact/ffmpeg_script")
        assert response.status_code == 200
        body = response.json()
        assert body["step"] == "ffmpeg_script"
        assert body["content_type"] == "text/plain"
        assert body["content"] == script_text

    def test_render_returns_presigned_url(self, client):
        """render artifact returns a presigned URL and no inline content."""
        presigned = "https://r2.example.com/signed?token=abc"
        mock_instance = MagicMock()
        mock_instance.generate_presigned_url.return_value = presigned
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            response = client.get("/runs/2026-05-24_test/artifact/render")
        assert response.status_code == 200
        body = response.json()
        assert body["step"] == "render"
        assert body["content_type"] == "video/mp4"
        assert body["url"] == presigned
        assert body["content"] is None

    def test_render_calls_correct_r2_key(self, client):
        """render step generates presigned URL for runs/{run_id}/output/final.mp4."""
        mock_instance = MagicMock()
        mock_instance.generate_presigned_url.return_value = "https://example.com/signed"
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            client.get("/runs/2026-05-24_test/artifact/render")
        mock_instance.generate_presigned_url.assert_called_once_with(
            "runs/2026-05-24_test/output/final.mp4"
        )

    def test_storyboard_calls_correct_r2_key(self, client):
        """storyboard step fetches runs/{run_id}/storyboard.json."""
        mock_instance = MagicMock()
        mock_instance.get_json.return_value = {}
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            client.get("/runs/2026-05-24_test/artifact/storyboard")
        mock_instance.get_json.assert_called_once_with(
            "runs/2026-05-24_test/storyboard.json"
        )

    def test_missing_artifact_returns_404(self, client):
        """StorageError when fetching artifact maps to HTTP 404."""
        mock_instance = MagicMock()
        mock_instance.get_json.side_effect = StorageError("NoSuchKey")
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            response = client.get("/runs/2026-05-24_test/artifact/storyboard")
        assert response.status_code == 404

    def test_invalid_step_returns_422(self, client):
        """Unrecognised step name returns HTTP 422."""
        response = client.get("/runs/2026-05-24_test/artifact/unknown-step")
        assert response.status_code == 422
        assert "unknown-step" in response.json()["detail"]


class TestVoiceoverUploadUrl:
    def test_returns_upload_url_and_key(self, client):
        """Endpoint returns presigned PUT URL and the R2 key for the voiceover file."""
        mock_instance = MagicMock()
        mock_instance.generate_presigned_put_url.return_value = "https://r2.example.com/upload?sig=abc"
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            res = client.post(
                "/runs/2026-05-24_test/voiceover-upload-url",
                json={"filename": "voiceover.mp3"},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["upload_url"] == "https://r2.example.com/upload?sig=abc"
        assert body["key"] == "runs/2026-05-24_test/voiceover/voiceover.mp3"

    def test_calls_correct_r2_key(self, client):
        """R2Client receives the correct key composed from run_id and filename."""
        mock_instance = MagicMock()
        mock_instance.generate_presigned_put_url.return_value = "https://example.com/upload"
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            client.post(
                "/runs/my-run/voiceover-upload-url",
                json={"filename": "audio.mp3"},
            )
        mock_instance.generate_presigned_put_url.assert_called_once_with(
            "runs/my-run/voiceover/audio.mp3"
        )

    def test_storage_error_returns_500(self, client):
        """StorageError from R2 maps to HTTP 500."""
        mock_instance = MagicMock()
        mock_instance.generate_presigned_put_url.side_effect = StorageError("R2 unreachable")
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            res = client.post(
                "/runs/2026-05-24_test/voiceover-upload-url",
                json={"filename": "vo.mp3"},
            )
        assert res.status_code == 500
        assert "R2 unreachable" in res.json()["detail"]

    def test_missing_filename_returns_422(self, client):
        """Request body without filename field returns HTTP 422."""
        res = client.post("/runs/2026-05-24_test/voiceover-upload-url", json={})
        assert res.status_code == 422


class TestCreateRunSlugValidation:
    def test_valid_slug_with_hyphens(self, client, mock_r2):
        """Slugs with hyphens between words are accepted."""
        response = client.post("/runs", json={"slug": "housing-affordability-crisis"})
        assert response.status_code == 201

    def test_valid_single_word_slug(self, client, mock_r2):
        """Single-word slugs are accepted."""
        response = client.post("/runs", json={"slug": "housing"})
        assert response.status_code == 201

    def test_invalid_slug_with_spaces_returns_422(self, client):
        """Slug with spaces is rejected with HTTP 422."""
        response = client.post("/runs", json={"slug": "my slug"})
        assert response.status_code == 422

    def test_invalid_slug_uppercase_returns_422(self, client):
        """Uppercase slug is rejected with HTTP 422."""
        response = client.post("/runs", json={"slug": "MySlug"})
        assert response.status_code == 422

    def test_invalid_slug_leading_hyphen_returns_422(self, client):
        """Slug starting with a hyphen is rejected with HTTP 422."""
        response = client.post("/runs", json={"slug": "-test-slug"})
        assert response.status_code == 422

    def test_invalid_slug_trailing_hyphen_returns_422(self, client):
        """Slug ending with a hyphen is rejected with HTTP 422."""
        response = client.post("/runs", json={"slug": "test-slug-"})
        assert response.status_code == 422

    def test_missing_slug_returns_422(self, client):
        """Request body without slug field returns HTTP 422."""
        response = client.post("/runs", json={})
        assert response.status_code == 422
