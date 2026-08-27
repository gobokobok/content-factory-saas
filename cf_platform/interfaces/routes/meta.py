"""Platform meta routes — GET /version, GET /health."""

from fastapi import APIRouter

from cf_platform.core.build_info import get_build_info
from cf_platform.core.config import get_platform_settings
from cf_platform.core.db import check_db_health

router = APIRouter()


@router.get("/version")
async def platform_version() -> dict:
    """Return the deployed commit, release tag, and async-worker status for deploy verification.

    Reads the build stamp written by the CD workflow (D077) rather than shelling
    out to git — the image has neither a .git directory nor a git binary.
    """
    return {**get_build_info(), "storyboard_async": True, "voice_async": True}


@router.get("/health")
async def platform_health() -> dict:
    """Return the cf_platform subsystem health status, including a DB check (D048).

    The "status" field always reports "ok" for the platform subsystem itself —
    a database outage is reported via "database" but does not affect "status"
    (DB down != legacy down, P2-S1).
    """
    settings = get_platform_settings()
    database_status = await check_db_health(settings.DATABASE_URL)
    return {"status": "ok", "database": database_status}
