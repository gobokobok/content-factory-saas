"""Google Drive client — authentication, folder creation, file upload, and run_log helpers."""

import base64
import json
import logging
from datetime import date, datetime, timezone

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

from src.exceptions import DriveError
from src.models import PIPELINE_STEPS, RunLog, StepLog

logger = logging.getLogger(__name__)

_DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
_SUBFOLDERS = ("video", "images", "sfx", "music", "voiceover", "output")


class DriveClient:
    """Wraps the Google Drive v3 API for Content Factory pipeline operations."""

    def __init__(self, service_account_json_b64: str) -> None:
        """Authenticate with Drive using a base64-encoded service account JSON string."""
        try:
            creds_info = json.loads(base64.b64decode(service_account_json_b64))
        except Exception as exc:
            raise DriveError(f"Failed to decode GOOGLE_SERVICE_ACCOUNT_JSON: {exc}") from exc

        try:
            creds = service_account.Credentials.from_service_account_info(
                creds_info, scopes=_DRIVE_SCOPES
            )
            self._service = build("drive", "v3", credentials=creds)
        except Exception as exc:
            raise DriveError(f"Failed to build Drive service: {exc}") from exc

    def _get_or_create_folder(self, name: str, parent_id: str) -> str:
        """Return existing folder ID under parent, or create it. Returns folder ID."""
        query = (
            f"name='{name}' and "
            f"'{parent_id}' in parents and "
            f"mimeType='{_DRIVE_FOLDER_MIME}' and "
            "trashed=false"
        )
        try:
            results = (
                self._service.files()
                .list(
                    q=query,
                    fields="files(id)",
                    spaces="drive",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
        except Exception as exc:
            raise DriveError(f"Drive list failed for folder '{name}': {exc}") from exc

        files = results.get("files", [])
        if files:
            return files[0]["id"]

        try:
            metadata = {
                "name": name,
                "mimeType": _DRIVE_FOLDER_MIME,
                "parents": [parent_id],
            }
            folder = (
                self._service.files()
                .create(body=metadata, fields="id", supportsAllDrives=True)
                .execute()
            )
        except Exception as exc:
            raise DriveError(f"Drive folder create failed for '{name}': {exc}") from exc

        return folder["id"]

    def upload_json(self, data: dict, filename: str, folder_id: str) -> str:
        """Upload a dict as a JSON file to a Drive folder. Returns the new file ID."""
        content = json.dumps(data, indent=2).encode("utf-8")
        media = MediaInMemoryUpload(content, mimetype="application/json")
        metadata = {"name": filename, "parents": [folder_id]}
        try:
            file = (
                self._service.files()
                .create(body=metadata, media_body=media, fields="id", supportsAllDrives=True)
                .execute()
            )
        except Exception as exc:
            raise DriveError(f"Drive upload failed for '{filename}': {exc}") from exc

        return file["id"]

    def create_run_folder(self, slug: str, root_folder_id: str) -> tuple[str, str]:
        """
        Create a dated run folder and all subfolders under root_folder_id/runs/.

        Returns (run_id, run_folder_id). Idempotent — reuses existing folders by name.
        """
        run_id = f"{date.today().isoformat()}_{slug}"
        logger.info("Creating run folder: %s", run_id)

        runs_folder_id = self._get_or_create_folder("runs", root_folder_id)
        run_folder_id = self._get_or_create_folder(run_id, runs_folder_id)

        for subfolder in _SUBFOLDERS:
            self._get_or_create_folder(subfolder, run_folder_id)

        run_log = _build_run_log(run_id)
        self.upload_json(run_log.model_dump(mode="json"), "run_log.json", run_folder_id)
        logger.info("Run folder ready: %s (id=%s)", run_id, run_folder_id)

        return run_id, run_folder_id


def _build_run_log(run_id: str) -> RunLog:
    """Construct a RunLog with all pipeline steps initialized to pending."""
    return RunLog(
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        steps={step: StepLog() for step in PIPELINE_STEPS},
    )
