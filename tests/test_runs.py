"""Tests for POST /runs endpoint."""

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
