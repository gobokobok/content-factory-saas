"""Route handlers for /runs endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from src.config import Settings, get_settings
from src.drive import DriveClient
from src.exceptions import DriveError
from src.models import RunCreateRequest, RunCreateResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/runs", response_model=RunCreateResponse, status_code=201)
def create_run(
    body: RunCreateRequest,
    settings: Settings = Depends(get_settings),
) -> RunCreateResponse:
    """Create a Drive run folder with subfolders and initialize run_log.json."""
    client = DriveClient(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
    try:
        run_id, folder_id = client.create_run_folder(body.slug, settings.GOOGLE_DRIVE_ROOT_ID)
    except DriveError as exc:
        logger.error("Drive error creating run for slug '%s': %s", body.slug, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RunCreateResponse(run_id=run_id, drive_folder_id=folder_id)
