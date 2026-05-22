"""Route handlers for /runs endpoints."""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from src.config import Settings, get_settings
from src.exceptions import StorageError
from src.models import RunCreateRequest, RunCreateResponse
from src.storage import R2Client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/runs", response_model=RunCreateResponse, status_code=201)
def create_run(
    body: RunCreateRequest,
    settings: Settings = Depends(get_settings),
) -> RunCreateResponse:
    """Create an R2 run prefix and initialise run_log.json."""
    client = R2Client(
        settings.R2_ACCOUNT_ID,
        settings.R2_ACCESS_KEY_ID,
        settings.R2_SECRET_ACCESS_KEY,
        settings.R2_BUCKET_NAME,
    )
    run_id = f"{date.today().isoformat()}_{body.slug}"
    try:
        prefix = client.create_run_folder(run_id)
    except StorageError as exc:
        logger.error("Storage error creating run '%s': %s", run_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RunCreateResponse(run_id=run_id, storage_prefix=prefix)
