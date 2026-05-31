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

FAKE_PROJECT_NAME = "Test Slug"
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
        """POST /runs returns HTTP 201 for a valid project name."""
        response = client.post("/runs", json={"project_name": FAKE_PROJECT_NAME})
        assert response.status_code == 201

    def test_returns_run_id_and_storage_prefix(self, client, mock_r2):
        """Response body contains run_id, project_name, and storage_prefix."""
        response = client.post("/runs", json={"project_name": FAKE_PROJECT_NAME})
        body = response.json()
        assert body["run_id"] == FAKE_RUN_ID
        assert body["project_name"] == FAKE_PROJECT_NAME
        assert body["storage_prefix"] == FAKE_PREFIX

    def test_no_drive_folder_id_in_response(self, client, mock_r2):
        """Response does not contain the old drive_folder_id field."""
        response = client.post("/runs", json={"project_name": FAKE_PROJECT_NAME})
        assert "drive_folder_id" not in response.json()

    def test_create_run_folder_called_with_run_id_and_project_name(self, client, mock_r2):
        """R2Client.create_run_folder is called with the constructed run_id and project_name."""
        client.post("/runs", json={"project_name": FAKE_PROJECT_NAME})
        mock_r2.create_run_folder.assert_called_once_with(
            FAKE_RUN_ID, project_name=FAKE_PROJECT_NAME
        )

    def test_r2_client_instantiated_with_settings(self, client):
        """R2Client is constructed with the four R2 ENV vars from settings."""
        mock_instance = MagicMock()
        mock_instance.create_run_folder.return_value = FAKE_PREFIX
        with patch("src.routes.runs.R2Client", return_value=mock_instance) as mock_cls:
            client.post("/runs", json={"project_name": FAKE_PROJECT_NAME})
            mock_cls.assert_called_once_with(
                "fake-account-id", "fake-access-key", "fake-secret-key", "content-factory-dev"
            )

    def test_storage_error_returns_500(self, client, mock_r2):
        """StorageError from R2Client maps to HTTP 500."""
        mock_r2.create_run_folder.side_effect = StorageError("bucket not found")
        response = client.post("/runs", json={"project_name": FAKE_PROJECT_NAME})
        assert response.status_code == 500

    def test_storage_error_detail_in_response(self, client, mock_r2):
        """500 response body contains the StorageError message."""
        mock_r2.create_run_folder.side_effect = StorageError("bucket not found")
        response = client.post("/runs", json={"project_name": FAKE_PROJECT_NAME})
        assert "bucket not found" in response.json()["detail"]

    def test_slug_generated_from_project_name(self, client, mock_r2):
        """run_id slug is derived from project_name (lowercased, non-alnum → hyphen)."""
        response = client.post("/runs", json={"project_name": "Housing Crisis Explained!"})
        assert response.status_code == 201
        run_id = response.json()["run_id"]
        assert run_id.endswith("_housing-crisis-explained")

    def test_project_name_echoed_in_response(self, client, mock_r2):
        """project_name in response matches what was submitted."""
        name = "My Housing Video"
        response = client.post("/runs", json={"project_name": name})
        assert response.json()["project_name"] == name


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
                "project_name": "Housing Crisis",
                "steps": {"storyboard": "complete", "asset_manifest": "pending"},
            }
        ]
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            response = client.get("/runs")
        assert response.status_code == 200
        runs = response.json()["runs"]
        assert len(runs) == 1
        assert runs[0]["run_id"] == "2026-05-24_housing-crisis"
        assert runs[0]["project_name"] == "Housing Crisis"
        assert runs[0]["steps"]["storyboard"] == "complete"

    def test_legacy_run_without_project_name_returns_none(self, client):
        """GET /runs returns project_name=null for legacy runs that lack the field."""
        mock_instance = MagicMock()
        mock_instance.list_runs.return_value = [
            {
                "run_id": "2026-05-20_old-run",
                "created_at": "2026-05-20T08:00:00+00:00",
                "project_name": None,
                "steps": {"storyboard": "complete"},
            }
        ]
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            response = client.get("/runs")
        runs = response.json()["runs"]
        assert runs[0]["project_name"] is None

    def test_returns_multiple_runs_sorted(self, client):
        """GET /runs returns multiple runs (order delegated to list_runs)."""
        mock_instance = MagicMock()
        mock_instance.list_runs.return_value = [
            {
                "run_id": "2026-05-24_run-b",
                "created_at": "2026-05-24T12:00:00+00:00",
                "project_name": "Run B",
                "steps": {"storyboard": "complete"},
            },
            {
                "run_id": "2026-05-23_run-a",
                "created_at": "2026-05-23T08:00:00+00:00",
                "project_name": None,
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


class TestCreateRunNameValidation:
    def test_valid_project_name_accepted(self, client, mock_r2):
        """Normal project name with letters and spaces is accepted."""
        response = client.post("/runs", json={"project_name": "Housing Affordability Crisis"})
        assert response.status_code == 201

    def test_project_name_with_special_chars_accepted(self, client, mock_r2):
        """Project name with punctuation is accepted (slugified by backend)."""
        response = client.post("/runs", json={"project_name": "Why Rents Are So High!"})
        assert response.status_code == 201

    def test_project_name_at_max_length_accepted(self, client, mock_r2):
        """Project name exactly 120 chars is accepted."""
        response = client.post("/runs", json={"project_name": "a" * 120})
        assert response.status_code == 201

    def test_project_name_too_long_returns_422(self, client):
        """Project name over 120 chars is rejected with HTTP 422."""
        response = client.post("/runs", json={"project_name": "a" * 121})
        assert response.status_code == 422

    def test_empty_project_name_returns_422(self, client):
        """Empty project name is rejected with HTTP 422."""
        response = client.post("/runs", json={"project_name": ""})
        assert response.status_code == 422

    def test_whitespace_only_project_name_returns_422(self, client):
        """Whitespace-only project name is rejected after strip."""
        response = client.post("/runs", json={"project_name": "   "})
        assert response.status_code == 422

    def test_missing_project_name_returns_422(self, client):
        """Request body without project_name field returns HTTP 422."""
        response = client.post("/runs", json={})
        assert response.status_code == 422

    def test_old_slug_field_returns_422(self, client):
        """Sending old 'slug' field (without project_name) returns HTTP 422."""
        response = client.post("/runs", json={"slug": "housing-crisis"})
        assert response.status_code == 422


class TestSaveDraft:
    """Tests for POST /runs/{run_id}/draft."""

    RUN_ID = "2026-05-29_housing-crisis"
    _SCRIPT = "Scene one: houses are expensive. Scene two: nobody can afford them."

    def _run_log(self, storyboard_status: str = "pending") -> dict:
        return {
            "run_id": self.RUN_ID,
            "created_at": "2026-05-29T10:00:00+00:00",
            "project_name": "Housing Crisis",
            "steps": {"storyboard": {"status": storyboard_status}},
        }

    def _mock_r2(self, storyboard_status: str = "pending") -> MagicMock:
        m = MagicMock()
        m.get_json.return_value = self._run_log(storyboard_status)
        return m

    def test_returns_200_on_success(self, client):
        """POST /runs/{run_id}/draft returns HTTP 200 when storyboard is not complete."""
        m = self._mock_r2()
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(
                f"/runs/{self.RUN_ID}/draft",
                json={"project_name": "Housing Crisis", "script": self._SCRIPT},
            )
        assert res.status_code == 200

    def test_returns_saved_status(self, client):
        """Response body contains status='saved' and the saved script."""
        m = self._mock_r2()
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(
                f"/runs/{self.RUN_ID}/draft",
                json={"project_name": "Housing Crisis", "script": self._SCRIPT},
            )
        body = res.json()
        assert body["status"] == "saved"
        assert body["script"] == self._SCRIPT

    def test_stores_script_txt_in_r2(self, client):
        """upload_text is called with the correct R2 key and script content."""
        m = self._mock_r2()
        with patch("src.routes.runs.R2Client", return_value=m):
            client.post(
                f"/runs/{self.RUN_ID}/draft",
                json={"project_name": "Housing Crisis", "script": self._SCRIPT},
            )
        m.upload_text.assert_called_once_with(f"runs/{self.RUN_ID}/script.txt", self._SCRIPT)

    def test_rejected_when_storyboard_complete(self, client):
        """POST /draft returns 409 if the storyboard step is already complete."""
        m = self._mock_r2(storyboard_status="complete")
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(
                f"/runs/{self.RUN_ID}/draft",
                json={"project_name": "Housing Crisis", "script": self._SCRIPT},
            )
        assert res.status_code == 409
        assert "storyboard" in res.json()["detail"].lower()

    def test_run_not_found_returns_404(self, client):
        """StorageError when reading run_log.json maps to HTTP 404."""
        m = MagicMock()
        m.get_json.side_effect = StorageError("NoSuchKey")
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(
                f"/runs/{self.RUN_ID}/draft",
                json={"project_name": "Housing Crisis", "script": self._SCRIPT},
            )
        assert res.status_code == 404

    def test_storage_error_on_upload_returns_500(self, client):
        """StorageError from upload_text maps to HTTP 500."""
        m = self._mock_r2()
        m.upload_text.side_effect = StorageError("bucket full")
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(
                f"/runs/{self.RUN_ID}/draft",
                json={"project_name": "Housing Crisis", "script": self._SCRIPT},
            )
        assert res.status_code == 500

    def test_missing_script_field_returns_422(self, client):
        """Request body missing script field returns HTTP 422."""
        m = self._mock_r2()
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(f"/runs/{self.RUN_ID}/draft", json={"project_name": "Test"})
        assert res.status_code == 422


class TestGetDraft:
    """Tests for GET /runs/{run_id}/draft."""

    RUN_ID = "2026-05-29_housing-crisis"
    _SCRIPT = "Housing prices are too high."

    def _run_log(self) -> dict:
        return {
            "run_id": self.RUN_ID,
            "created_at": "2026-05-29T10:00:00+00:00",
            "project_name": "Housing Crisis",
            "steps": {"storyboard": {"status": "pending"}},
        }

    def test_returns_200_with_script(self, client):
        """GET /runs/{run_id}/draft returns script from script.txt."""
        m = MagicMock()
        m.get_json.return_value = self._run_log()
        m.get_bytes.return_value = self._SCRIPT.encode("utf-8")
        m.list_keys.return_value = []
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.get(f"/runs/{self.RUN_ID}/draft")
        assert res.status_code == 200
        body = res.json()
        assert body["script"] == self._SCRIPT
        assert body["project_name"] == "Housing Crisis"

    def test_returns_vo_filename_when_present(self, client):
        """vo_filename is populated from the first .mp3 key in voiceover prefix."""
        m = MagicMock()
        m.get_json.return_value = self._run_log()
        m.get_bytes.return_value = self._SCRIPT.encode("utf-8")
        m.list_keys.return_value = [f"runs/{self.RUN_ID}/voiceover/narration.mp3"]
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.get(f"/runs/{self.RUN_ID}/draft")
        assert res.json()["vo_filename"] == "narration.mp3"

    def test_vo_filename_none_when_no_voiceover(self, client):
        """vo_filename is null when no audio files exist in voiceover prefix."""
        m = MagicMock()
        m.get_json.return_value = self._run_log()
        m.get_bytes.return_value = self._SCRIPT.encode("utf-8")
        m.list_keys.return_value = []
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.get(f"/runs/{self.RUN_ID}/draft")
        assert res.json()["vo_filename"] is None

    def test_empty_script_when_no_draft_saved(self, client):
        """script is empty string when script.txt does not exist yet."""
        m = MagicMock()
        m.get_json.return_value = self._run_log()
        m.get_bytes.side_effect = StorageError("NoSuchKey")
        m.list_keys.return_value = []
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.get(f"/runs/{self.RUN_ID}/draft")
        assert res.status_code == 200
        assert res.json()["script"] == ""

    def test_run_not_found_returns_404(self, client):
        """StorageError reading run_log.json returns HTTP 404."""
        m = MagicMock()
        m.get_json.side_effect = StorageError("NoSuchKey")
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.get(f"/runs/{self.RUN_ID}/draft")
        assert res.status_code == 404


class TestGetAssetLink:
    RUN_ID = "2026-05-29_test-run"
    VALID_KEY = f"runs/{RUN_ID}/images/scene_01.jpeg"
    PRESIGNED = "https://r2.example.com/signed?token=abc"

    def test_returns_presigned_url(self, client):
        """Valid key within run prefix returns a presigned URL and expires_in."""
        mock_instance = MagicMock()
        mock_instance.generate_presigned_url.return_value = self.PRESIGNED
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            res = client.get(f"/runs/{self.RUN_ID}/asset-link", params={"key": self.VALID_KEY})
        assert res.status_code == 200
        body = res.json()
        assert body["url"] == self.PRESIGNED
        assert body["expires_in"] == 3600

    def test_calls_correct_r2_key(self, client):
        """R2Client.generate_presigned_url is called with the exact key."""
        mock_instance = MagicMock()
        mock_instance.generate_presigned_url.return_value = self.PRESIGNED
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            client.get(f"/runs/{self.RUN_ID}/asset-link", params={"key": self.VALID_KEY})
        mock_instance.generate_presigned_url.assert_called_once_with(self.VALID_KEY)

    def test_key_outside_run_prefix_returns_403(self, client):
        """Key that does not start with runs/{run_id}/ is rejected with 403."""
        bad_key = "runs/other-run/images/scene_01.jpeg"
        res = client.get(f"/runs/{self.RUN_ID}/asset-link", params={"key": bad_key})
        assert res.status_code == 403

    def test_traversal_attempt_returns_403(self, client):
        """Path traversal key is rejected with 403."""
        traversal_key = f"runs/{self.RUN_ID}/../secret.txt"
        res = client.get(f"/runs/{self.RUN_ID}/asset-link", params={"key": traversal_key})
        assert res.status_code == 403

    def test_storage_error_returns_500(self, client):
        """StorageError from R2 maps to HTTP 500."""
        mock_instance = MagicMock()
        mock_instance.generate_presigned_url.side_effect = StorageError("R2 down")
        with patch("src.routes.runs.R2Client", return_value=mock_instance):
            res = client.get(f"/runs/{self.RUN_ID}/asset-link", params={"key": self.VALID_KEY})
        assert res.status_code == 500
        assert "R2 down" in res.json()["detail"]

    def test_missing_key_param_returns_422(self, client):
        """Request without key query param returns HTTP 422."""
        res = client.get(f"/runs/{self.RUN_ID}/asset-link")
        assert res.status_code == 422


class TestVideoSettings:
    """Tests for POST/GET /runs/{run_id}/settings."""

    RUN_ID = "2026-05-31_settings-test"
    SETTINGS_KEY = f"runs/{RUN_ID}/settings.json"
    DEFAULT_PAYLOAD = {
        "aspect_ratio": "9:16",
        "visual_style": "Realistic",
        "subtitles": "TikTok",
    }

    def test_post_saves_settings_and_returns_saved(self, client):
        """POST /runs/{run_id}/settings stores settings.json and returns status='saved'."""
        m = MagicMock()
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(f"/runs/{self.RUN_ID}/settings", json=self.DEFAULT_PAYLOAD)
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "saved"
        assert body["settings"]["aspect_ratio"] == "9:16"
        assert body["settings"]["visual_style"] == "Realistic"
        assert body["settings"]["subtitles"] == "TikTok"

    def test_post_calls_upload_json_with_correct_key(self, client):
        """POST stores settings at runs/{run_id}/settings.json."""
        m = MagicMock()
        with patch("src.routes.runs.R2Client", return_value=m):
            client.post(f"/runs/{self.RUN_ID}/settings", json=self.DEFAULT_PAYLOAD)
        m.upload_json.assert_called_once()
        key_arg = m.upload_json.call_args[0][0]
        assert key_arg == self.SETTINGS_KEY

    def test_post_stores_all_fields(self, client):
        """POST stores the full settings dict in R2."""
        m = MagicMock()
        payload = {
            "aspect_ratio": "16:9",
            "visual_style": "Cinematic",
            "subtitles": "Classic",
        }
        with patch("src.routes.runs.R2Client", return_value=m):
            client.post(f"/runs/{self.RUN_ID}/settings", json=payload)
        stored = m.upload_json.call_args[0][1]
        assert stored["aspect_ratio"] == "16:9"
        assert stored["visual_style"] == "Cinematic"
        assert stored["subtitles"] == "Classic"

    def test_post_subtitles_none_accepted(self, client):
        """POST with subtitles='none' (disabled) is valid."""
        m = MagicMock()
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(
                f"/runs/{self.RUN_ID}/settings",
                json={**self.DEFAULT_PAYLOAD, "subtitles": "none"},
            )
        assert res.status_code == 200
        assert res.json()["settings"]["subtitles"] == "none"

    def test_post_invalid_aspect_ratio_returns_422(self, client):
        """POST with unknown aspect_ratio value returns HTTP 422."""
        m = MagicMock()
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(
                f"/runs/{self.RUN_ID}/settings",
                json={**self.DEFAULT_PAYLOAD, "aspect_ratio": "4:3"},
            )
        assert res.status_code == 422

    def test_post_invalid_visual_style_returns_422(self, client):
        """POST with unknown visual_style value returns HTTP 422."""
        m = MagicMock()
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(
                f"/runs/{self.RUN_ID}/settings",
                json={**self.DEFAULT_PAYLOAD, "visual_style": "Watercolour"},
            )
        assert res.status_code == 422

    def test_post_invalid_subtitles_value_returns_422(self, client):
        """POST with unknown subtitles value returns HTTP 422."""
        m = MagicMock()
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(
                f"/runs/{self.RUN_ID}/settings",
                json={**self.DEFAULT_PAYLOAD, "subtitles": "Fancy"},
            )
        assert res.status_code == 422

    def test_post_storage_error_returns_500(self, client):
        """StorageError from upload_json maps to HTTP 500."""
        m = MagicMock()
        m.upload_json.side_effect = StorageError("R2 write failed")
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(f"/runs/{self.RUN_ID}/settings", json=self.DEFAULT_PAYLOAD)
        assert res.status_code == 500
        assert "R2 write failed" in res.json()["detail"]

    def test_get_returns_stored_settings(self, client):
        """GET /runs/{run_id}/settings returns stored values from R2."""
        stored = {
            "aspect_ratio": "1:1",
            "visual_style": "Documentary",
            "subtitles": "Classic",
        }
        m = MagicMock()
        m.get_json.return_value = stored
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.get(f"/runs/{self.RUN_ID}/settings")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        s = body["settings"]
        assert s["aspect_ratio"] == "1:1"
        assert s["visual_style"] == "Documentary"
        assert s["subtitles"] == "Classic"

    def test_get_returns_defaults_when_settings_absent(self, client):
        """GET returns default VideoSettings (9:16 / Realistic / TikTok) when no file exists."""
        m = MagicMock()
        m.get_json.side_effect = StorageError("NoSuchKey")
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.get(f"/runs/{self.RUN_ID}/settings")
        assert res.status_code == 200
        s = res.json()["settings"]
        assert s["aspect_ratio"] == "9:16"
        assert s["visual_style"] == "Realistic"
        assert s["subtitles"] == "TikTok"

    def test_get_calls_correct_r2_key(self, client):
        """GET fetches runs/{run_id}/settings.json from R2."""
        m = MagicMock()
        m.get_json.side_effect = StorageError("NoSuchKey")
        with patch("src.routes.runs.R2Client", return_value=m):
            client.get(f"/runs/{self.RUN_ID}/settings")
        m.get_json.assert_called_once_with(self.SETTINGS_KEY)

    def test_get_returns_200_even_when_no_settings_file(self, client):
        """GET returns HTTP 200 with defaults when settings.json does not exist (never a 404)."""
        m = MagicMock()
        m.get_json.side_effect = StorageError("NoSuchKey")
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.get(f"/runs/{self.RUN_ID}/settings")
        assert res.status_code == 200


class TestDeleteRun:
    RUN_ID = "2026-05-30_delete-me"

    def test_returns_204_on_success(self, client):
        """DELETE /runs/{run_id} returns HTTP 204 when keys are deleted."""
        m = MagicMock()
        m.delete_run.return_value = 5
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.delete(f"/runs/{self.RUN_ID}")
        assert res.status_code == 204

    def test_calls_delete_run_with_correct_run_id(self, client):
        """R2Client.delete_run is called with the run_id from the URL."""
        m = MagicMock()
        m.delete_run.return_value = 3
        with patch("src.routes.runs.R2Client", return_value=m):
            client.delete(f"/runs/{self.RUN_ID}")
        m.delete_run.assert_called_once_with(self.RUN_ID)

    def test_returns_404_when_run_not_found(self, client):
        """StorageError with 'not found' maps to HTTP 404."""
        m = MagicMock()
        m.delete_run.side_effect = StorageError(f"Run not found: {self.RUN_ID}")
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.delete(f"/runs/{self.RUN_ID}")
        assert res.status_code == 404
        assert self.RUN_ID in res.json()["detail"]

    def test_returns_500_on_r2_error(self, client):
        """Non-404 StorageError maps to HTTP 500."""
        m = MagicMock()
        m.delete_run.side_effect = StorageError("R2 connection error")
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.delete(f"/runs/{self.RUN_ID}")
        assert res.status_code == 500
        assert "R2 connection error" in res.json()["detail"]


class TestDeleteVoiceover:
    """Tests for DELETE /runs/{run_id}/voiceover."""

    RUN_ID = "2026-05-31_vo-delete-test"

    def test_returns_204_when_files_deleted(self, client):
        """DELETE /runs/{run_id}/voiceover returns HTTP 204 on success."""
        m = MagicMock()
        m.list_keys.return_value = [f"runs/{self.RUN_ID}/voiceover/narration.mp3"]
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.delete(f"/runs/{self.RUN_ID}/voiceover")
        assert res.status_code == 204

    def test_returns_204_when_no_voiceover_exists(self, client):
        """DELETE is a no-op when no voiceover files exist — still returns 204."""
        m = MagicMock()
        m.list_keys.return_value = []
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.delete(f"/runs/{self.RUN_ID}/voiceover")
        assert res.status_code == 204

    def test_storage_error_listing_returns_500(self, client):
        """StorageError from list_keys maps to HTTP 500."""
        m = MagicMock()
        m.list_keys.side_effect = StorageError("R2 unreachable")
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.delete(f"/runs/{self.RUN_ID}/voiceover")
        assert res.status_code == 500


class TestMusicUploadUrl:
    """Tests for POST /runs/{run_id}/music-upload-url."""

    RUN_ID = "2026-05-31_music-test"

    def test_returns_upload_url_and_key(self, client):
        """Endpoint returns presigned PUT URL and the R2 key for the music file."""
        m = MagicMock()
        m.generate_presigned_put_url.return_value = "https://r2.example.com/upload?sig=xyz"
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(
                f"/runs/{self.RUN_ID}/music-upload-url",
                json={"filename": "track.mp3"},
            )
        assert res.status_code == 200
        body = res.json()
        assert body["upload_url"] == "https://r2.example.com/upload?sig=xyz"
        assert body["key"] == f"runs/{self.RUN_ID}/music/track.mp3"

    def test_calls_correct_r2_key(self, client):
        """R2Client receives the correct key composed from run_id and filename."""
        m = MagicMock()
        m.generate_presigned_put_url.return_value = "https://example.com/upload"
        with patch("src.routes.runs.R2Client", return_value=m):
            client.post(
                f"/runs/{self.RUN_ID}/music-upload-url",
                json={"filename": "bg.wav"},
            )
        m.generate_presigned_put_url.assert_called_once_with(
            f"runs/{self.RUN_ID}/music/bg.wav"
        )

    def test_storage_error_returns_500(self, client):
        """StorageError from R2 maps to HTTP 500."""
        m = MagicMock()
        m.generate_presigned_put_url.side_effect = StorageError("R2 unreachable")
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.post(
                f"/runs/{self.RUN_ID}/music-upload-url",
                json={"filename": "bg.mp3"},
            )
        assert res.status_code == 500
        assert "R2 unreachable" in res.json()["detail"]

    def test_missing_filename_returns_422(self, client):
        """Request body without filename field returns HTTP 422."""
        res = client.post(f"/runs/{self.RUN_ID}/music-upload-url", json={})
        assert res.status_code == 422


class TestDeleteMusic:
    """Tests for DELETE /runs/{run_id}/music."""

    RUN_ID = "2026-05-31_music-delete-test"

    def test_returns_204_when_files_deleted(self, client):
        """DELETE /runs/{run_id}/music returns HTTP 204 on success."""
        m = MagicMock()
        m.list_keys.return_value = [f"runs/{self.RUN_ID}/music/bg.mp3"]
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.delete(f"/runs/{self.RUN_ID}/music")
        assert res.status_code == 204

    def test_returns_204_when_no_music_exists(self, client):
        """DELETE is a no-op when no music files exist — still returns 204."""
        m = MagicMock()
        m.list_keys.return_value = []
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.delete(f"/runs/{self.RUN_ID}/music")
        assert res.status_code == 204

    def test_storage_error_listing_returns_500(self, client):
        """StorageError from list_keys maps to HTTP 500."""
        m = MagicMock()
        m.list_keys.side_effect = StorageError("R2 unreachable")
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.delete(f"/runs/{self.RUN_ID}/music")
        assert res.status_code == 500


class TestGetDraftMusicFilename:
    """Tests for music_filename field in GET /runs/{run_id}/draft."""

    RUN_ID = "2026-05-31_music-draft-test"

    def _run_log(self) -> dict:
        return {
            "run_id": self.RUN_ID,
            "created_at": "2026-05-31T10:00:00+00:00",
            "project_name": "Music Test",
            "steps": {"storyboard": {"status": "pending"}},
        }

    def test_music_filename_populated_when_present(self, client):
        """music_filename is returned when a music file exists in the music prefix."""
        m = MagicMock()
        m.get_json.return_value = self._run_log()
        m.get_bytes.return_value = b""
        # First call = voiceover prefix (empty), second call = music prefix
        m.list_keys.side_effect = [[], [f"runs/{self.RUN_ID}/music/bg.mp3"]]
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.get(f"/runs/{self.RUN_ID}/draft")
        assert res.status_code == 200
        assert res.json()["music_filename"] == "bg.mp3"

    def test_music_filename_none_when_no_music(self, client):
        """music_filename is null when no audio files exist in music prefix."""
        m = MagicMock()
        m.get_json.return_value = self._run_log()
        m.get_bytes.return_value = b""
        m.list_keys.return_value = []
        with patch("src.routes.runs.R2Client", return_value=m):
            res = client.get(f"/runs/{self.RUN_ID}/draft")
        assert res.status_code == 200
        assert res.json()["music_filename"] is None
