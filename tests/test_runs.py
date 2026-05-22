"""Tests for POST /runs endpoint."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.exceptions import DriveError
from src.main import app


VALID_ENV = {
    "ENVIRONMENT": "dev",
    "GOOGLE_SERVICE_ACCOUNT_JSON": "eyJmYWtlIjoidHJ1ZSJ9",
    "GOOGLE_DRIVE_ROOT_ID": "fake-drive-root-id",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "PEXELS_API_KEY": "fake-pexels-key",
    "REPLICATE_API_TOKEN": "fake-replicate-token",
    "FREESOUND_API_KEY": "fake-freesound-key",
}

FAKE_FOLDER_ID = "drive-folder-abc123"


def _make_settings(**overrides) -> Settings:
    """Build a Settings instance from VALID_ENV with optional field overrides."""
    return Settings.model_validate({**VALID_ENV, **overrides})


@pytest.fixture()
def client():
    """TestClient with settings injected and DriveClient patched."""
    settings = _make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture()
def mock_drive(client):
    """Patch DriveClient so no real Drive calls are made. Returns the mock instance."""
    mock_instance = MagicMock()
    mock_instance.create_run_folder.return_value = (
        f"{date.today().isoformat()}_test-slug",
        FAKE_FOLDER_ID,
    )
    with patch("src.routes.runs.DriveClient", return_value=mock_instance):
        yield mock_instance


class TestCreateRun:
    def test_returns_201_on_success(self, client, mock_drive):
        """POST /runs returns HTTP 201 for a valid slug."""
        response = client.post("/runs", json={"slug": "test-slug"})
        assert response.status_code == 201

    def test_returns_run_id_and_folder_id(self, client, mock_drive):
        """Response body contains run_id and drive_folder_id."""
        response = client.post("/runs", json={"slug": "test-slug"})
        body = response.json()
        assert body["run_id"] == f"{date.today().isoformat()}_test-slug"
        assert body["drive_folder_id"] == FAKE_FOLDER_ID

    def test_passes_slug_and_root_id_to_drive(self, client, mock_drive):
        """DriveClient.create_run_folder is called with the slug and the configured root ID."""
        client.post("/runs", json={"slug": "housing-crisis"})
        mock_drive.create_run_folder.assert_called_once_with(
            "housing-crisis", "fake-drive-root-id"
        )

    def test_drive_error_returns_500(self, client, mock_drive):
        """DriveError from the Drive client maps to HTTP 500."""
        mock_drive.create_run_folder.side_effect = DriveError("quota exceeded")
        response = client.post("/runs", json={"slug": "test-slug"})
        assert response.status_code == 500

    def test_drive_error_detail_in_response(self, client, mock_drive):
        """500 response body contains the DriveError message."""
        mock_drive.create_run_folder.side_effect = DriveError("quota exceeded")
        response = client.post("/runs", json={"slug": "test-slug"})
        assert "quota exceeded" in response.json()["detail"]


class TestCreateRunSlugValidation:
    def test_valid_slug_with_hyphens(self, client, mock_drive):
        """Slugs with hyphens between words are accepted."""
        response = client.post("/runs", json={"slug": "housing-affordability-crisis"})
        assert response.status_code == 201

    def test_valid_single_word_slug(self, client, mock_drive):
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

    def test_invalid_slug_special_chars_returns_422(self, client):
        """Slug with special characters is rejected with HTTP 422."""
        response = client.post("/runs", json={"slug": "my_slug!"})
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
