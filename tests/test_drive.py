"""Tests for DriveClient — all Drive API calls are mocked."""

import base64
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.drive import DriveClient, _SUBFOLDERS, _build_run_log
from src.exceptions import DriveError
from src.models import PIPELINE_STEPS, StepStatus


FAKE_SA_JSON = {"type": "service_account", "project_id": "test-project"}
FAKE_SA_B64 = base64.b64encode(json.dumps(FAKE_SA_JSON).encode()).decode()
FAKE_FOLDER_ID = "fake-folder-id"
FAKE_ROOT_ID = "fake-root-id"


@pytest.fixture()
def mock_drive_service():
    """Patch Drive auth and service build; configure mock to return empty folder lists and stable IDs."""
    mock_service = MagicMock()
    mock_service.files().list().execute.return_value = {"files": []}
    mock_service.files().create().execute.return_value = {"id": FAKE_FOLDER_ID}

    with (
        patch("src.drive.service_account.Credentials.from_service_account_info"),
        patch("src.drive.build", return_value=mock_service),
    ):
        yield mock_service


class TestDriveClientInit:
    def test_bad_base64_raises_drive_error(self):
        """Non-base64 input raises DriveError on init."""
        with pytest.raises(DriveError, match="Failed to decode"):
            DriveClient("!!!not-base64!!!")

    def test_invalid_json_after_decode_raises_drive_error(self):
        """Valid base64 that decodes to non-JSON raises DriveError on init."""
        bad_b64 = base64.b64encode(b"not-json").decode()
        with pytest.raises(DriveError, match="Failed to decode"):
            DriveClient(bad_b64)

    def test_build_failure_raises_drive_error(self):
        """If the Drive API build() call fails, DriveError is raised."""
        with (
            patch("src.drive.service_account.Credentials.from_service_account_info"),
            patch("src.drive.build", side_effect=Exception("network error")),
        ):
            with pytest.raises(DriveError, match="Failed to build Drive service"):
                DriveClient(FAKE_SA_B64)

    def test_successful_init(self, mock_drive_service):
        """Valid b64 SA JSON produces a DriveClient without error."""
        client = DriveClient(FAKE_SA_B64)
        assert client is not None


class TestCreateRunFolder:
    def test_returns_correct_run_id(self, mock_drive_service):
        """run_id is {today}_{slug}."""
        client = DriveClient(FAKE_SA_B64)
        run_id, _ = client.create_run_folder("test-slug", FAKE_ROOT_ID)
        assert run_id == f"{date.today().isoformat()}_test-slug"

    def test_returns_folder_id(self, mock_drive_service):
        """Returned folder_id matches what the Drive API returns."""
        client = DriveClient(FAKE_SA_B64)
        _, folder_id = client.create_run_folder("test-slug", FAKE_ROOT_ID)
        assert folder_id == FAKE_FOLDER_ID

    def test_creates_all_subfolders(self, mock_drive_service):
        """All six subfolders are created under the run folder."""
        client = DriveClient(FAKE_SA_B64)
        client.create_run_folder("test-slug", FAKE_ROOT_ID)

        created_names = [
            call.kwargs["body"]["name"]
            for call in mock_drive_service.files().create.call_args_list
            if call.kwargs.get("body", {}).get("mimeType") == "application/vnd.google-apps.folder"
        ]
        for subfolder in _SUBFOLDERS:
            assert subfolder in created_names, f"Missing subfolder: {subfolder}"

    def test_creates_runs_parent_folder(self, mock_drive_service):
        """A 'runs' folder is sought/created under the root before the run folder."""
        client = DriveClient(FAKE_SA_B64)
        client.create_run_folder("test-slug", FAKE_ROOT_ID)

        created_names = [
            call.kwargs["body"]["name"]
            for call in mock_drive_service.files().create.call_args_list
            if call.kwargs.get("body", {}).get("mimeType") == "application/vnd.google-apps.folder"
        ]
        assert "runs" in created_names

    def test_uploads_run_log_json(self, mock_drive_service):
        """run_log.json is uploaded as part of folder creation."""
        client = DriveClient(FAKE_SA_B64)
        client.create_run_folder("test-slug", FAKE_ROOT_ID)

        uploaded_names = [
            call.kwargs["body"]["name"]
            for call in mock_drive_service.files().create.call_args_list
            if "media_body" in call.kwargs
        ]
        assert "run_log.json" in uploaded_names

    def test_reuses_existing_folder(self, mock_drive_service):
        """If 'runs' folder already exists in Drive, it is reused and not re-created."""
        existing_id = "existing-runs-folder-id"
        mock_drive_service.files().list().execute.return_value = {
            "files": [{"id": existing_id}]
        }
        client = DriveClient(FAKE_SA_B64)
        client.create_run_folder("test-slug", FAKE_ROOT_ID)

        # No folder create calls should have been made for 'runs'
        folder_creates = [
            call.kwargs["body"]["name"]
            for call in mock_drive_service.files().create.call_args_list
            if call.kwargs.get("body", {}).get("mimeType") == "application/vnd.google-apps.folder"
        ]
        assert "runs" not in folder_creates

    def test_drive_list_error_raises_drive_error(self, mock_drive_service):
        """Drive list() failure propagates as DriveError."""
        mock_drive_service.files().list().execute.side_effect = Exception("quota exceeded")
        client = DriveClient(FAKE_SA_B64)
        with pytest.raises(DriveError, match="Drive list failed"):
            client.create_run_folder("test-slug", FAKE_ROOT_ID)

    def test_drive_create_error_raises_drive_error(self, mock_drive_service):
        """Drive create() failure propagates as DriveError."""
        mock_drive_service.files().create().execute.side_effect = Exception("permission denied")
        client = DriveClient(FAKE_SA_B64)
        with pytest.raises(DriveError):
            client.create_run_folder("test-slug", FAKE_ROOT_ID)


class TestBuildRunLog:
    def test_all_steps_present(self):
        """run_log.json contains all five pipeline steps."""
        log = _build_run_log("2026-05-22_test-slug")
        assert set(log.steps.keys()) == set(PIPELINE_STEPS)

    def test_all_steps_pending(self):
        """All steps are initialized to pending status."""
        log = _build_run_log("2026-05-22_test-slug")
        for step, entry in log.steps.items():
            assert entry.status == StepStatus.pending, f"{step} should be pending"

    def test_no_completed_at_or_error(self):
        """All steps have null completed_at and error on init."""
        log = _build_run_log("2026-05-22_test-slug")
        for entry in log.steps.values():
            assert entry.completed_at is None
            assert entry.error is None

    def test_run_id_preserved(self):
        """run_id matches the slug passed in."""
        log = _build_run_log("2026-05-22_my-slug")
        assert log.run_id == "2026-05-22_my-slug"

    def test_created_at_is_set(self):
        """created_at is a non-empty ISO timestamp."""
        log = _build_run_log("2026-05-22_my-slug")
        assert log.created_at
        assert "T" in log.created_at
