"""Tests for DriveClient — all Drive API calls are mocked."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.drive import DriveClient, _SUBFOLDERS, _build_run_log
from src.exceptions import DriveError
from src.models import PIPELINE_STEPS, StepStatus


FAKE_CLIENT_ID = "fake-client-id"
FAKE_CLIENT_SECRET = "fake-client-secret"
FAKE_REFRESH_TOKEN = "fake-refresh-token"
FAKE_FOLDER_ID = "fake-folder-id"
FAKE_ROOT_ID = "fake-root-id"


def _make_client(mock_service: MagicMock) -> DriveClient:
    """Return a DriveClient with auth and Drive service fully mocked."""
    with (
        patch("src.drive.OAuthCredentials"),
        patch("src.drive.build", return_value=mock_service),
    ):
        return DriveClient(FAKE_CLIENT_ID, FAKE_CLIENT_SECRET, FAKE_REFRESH_TOKEN)


@pytest.fixture()
def mock_service() -> MagicMock:
    """Drive service mock: list returns empty, create returns a stable folder ID.

    Uses .return_value chains instead of invocations so no calls are recorded
    during fixture setup — call_args_list[0] is always the first real test call.
    """
    svc = MagicMock()
    svc.files.return_value.list.return_value.execute.return_value = {"files": []}
    svc.files.return_value.create.return_value.execute.return_value = {"id": FAKE_FOLDER_ID}
    return svc


@pytest.fixture()
def client(mock_service: MagicMock) -> DriveClient:
    """DriveClient with mocked auth and service."""
    return _make_client(mock_service)


class TestDriveClientInit:
    def test_successful_init(self, mock_service):
        """Valid credentials produce a DriveClient without error."""
        c = _make_client(mock_service)
        assert c is not None

    def test_build_failure_raises_drive_error(self):
        """If build() raises, DriveError is surfaced."""
        with (
            patch("src.drive.OAuthCredentials"),
            patch("src.drive.build", side_effect=Exception("network error")),
        ):
            with pytest.raises(DriveError, match="Failed to build Drive service"):
                DriveClient(FAKE_CLIENT_ID, FAKE_CLIENT_SECRET, FAKE_REFRESH_TOKEN)

    def test_credentials_constructed_with_correct_params(self):
        """OAuthCredentials is called with the supplied client_id, secret, refresh_token."""
        with (
            patch("src.drive.OAuthCredentials") as mock_creds_cls,
            patch("src.drive.build"),
        ):
            DriveClient(FAKE_CLIENT_ID, FAKE_CLIENT_SECRET, FAKE_REFRESH_TOKEN)
            mock_creds_cls.assert_called_once_with(
                token=None,
                refresh_token=FAKE_REFRESH_TOKEN,
                client_id=FAKE_CLIENT_ID,
                client_secret=FAKE_CLIENT_SECRET,
                token_uri="https://oauth2.googleapis.com/token",
            )


class TestCreateRunFolder:
    def test_returns_correct_run_id(self, client, mock_service):
        """run_id is {today}_{slug}."""
        run_id, _ = client.create_run_folder("test-slug", FAKE_ROOT_ID)
        assert run_id == f"{date.today().isoformat()}_test-slug"

    def test_returns_folder_id(self, client, mock_service):
        """Returned folder_id matches the Drive API response."""
        _, folder_id = client.create_run_folder("test-slug", FAKE_ROOT_ID)
        assert folder_id == FAKE_FOLDER_ID

    def test_creates_all_subfolders(self, client, mock_service):
        """All six subfolders are created under the run folder."""
        client.create_run_folder("test-slug", FAKE_ROOT_ID)

        created_names = [
            call.kwargs["body"]["name"]
            for call in mock_service.files().create.call_args_list
            if call.kwargs.get("body", {}).get("mimeType") == "application/vnd.google-apps.folder"
        ]
        for subfolder in _SUBFOLDERS:
            assert subfolder in created_names, f"Missing subfolder: {subfolder}"

    def test_creates_runs_parent_folder(self, client, mock_service):
        """A 'runs' folder is sought/created under the root before the run folder."""
        client.create_run_folder("test-slug", FAKE_ROOT_ID)

        created_names = [
            call.kwargs["body"]["name"]
            for call in mock_service.files().create.call_args_list
            if call.kwargs.get("body", {}).get("mimeType") == "application/vnd.google-apps.folder"
        ]
        assert "runs" in created_names

    def test_uploads_run_log_json(self, client, mock_service):
        """run_log.json is uploaded as part of folder creation."""
        client.create_run_folder("test-slug", FAKE_ROOT_ID)

        uploaded_names = [
            call.kwargs["body"]["name"]
            for call in mock_service.files().create.call_args_list
            if "media_body" in call.kwargs
        ]
        assert "run_log.json" in uploaded_names

    def test_reuses_existing_folder(self, client, mock_service):
        """If 'runs' folder already exists in Drive, it is reused and not re-created."""
        mock_service.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "existing-runs-folder-id"}]
        }
        client.create_run_folder("test-slug", FAKE_ROOT_ID)

        folder_creates = [
            call.kwargs["body"]["name"]
            for call in mock_service.files().create.call_args_list
            if call.kwargs.get("body", {}).get("mimeType") == "application/vnd.google-apps.folder"
        ]
        assert "runs" not in folder_creates

    def test_drive_list_error_raises_drive_error(self, client, mock_service):
        """Drive list() failure propagates as DriveError."""
        mock_service.files().list().execute.side_effect = Exception("quota exceeded")
        with pytest.raises(DriveError, match="Drive list failed"):
            client.create_run_folder("test-slug", FAKE_ROOT_ID)

    def test_drive_create_error_raises_drive_error(self, client, mock_service):
        """Drive create() failure propagates as DriveError."""
        mock_service.files().create().execute.side_effect = Exception("permission denied")
        with pytest.raises(DriveError):
            client.create_run_folder("test-slug", FAKE_ROOT_ID)

    def test_list_calls_include_all_drives_params(self, client, mock_service):
        """list() is called with supportsAllDrives and includeItemsFromAllDrives."""
        client.create_run_folder("test-slug", FAKE_ROOT_ID)
        list_call_kwargs = mock_service.files().list.call_args_list[0].kwargs
        assert list_call_kwargs.get("supportsAllDrives") is True
        assert list_call_kwargs.get("includeItemsFromAllDrives") is True

    def test_create_calls_include_supports_all_drives(self, client, mock_service):
        """create() is called with supportsAllDrives=True for both folders and file uploads."""
        client.create_run_folder("test-slug", FAKE_ROOT_ID)
        for call in mock_service.files().create.call_args_list:
            assert call.kwargs.get("supportsAllDrives") is True, (
                f"create() call missing supportsAllDrives=True: {call}"
            )


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
        """run_id matches the value passed in."""
        log = _build_run_log("2026-05-22_my-slug")
        assert log.run_id == "2026-05-22_my-slug"

    def test_created_at_is_set(self):
        """created_at is a non-empty ISO timestamp."""
        log = _build_run_log("2026-05-22_my-slug")
        assert log.created_at
        assert "T" in log.created_at
