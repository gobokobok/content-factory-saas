"""Platform meta routes — GET /version, GET /health."""

from fastapi import APIRouter

from cf_platform.core.config import get_platform_settings
from cf_platform.core.db import check_db_health

router = APIRouter()


@router.get("/version")
async def platform_version() -> dict:
    """Return the deployed git commit and async-worker status for deploy verification."""
    import subprocess
    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        commit = "unknown"
    return {"commit": commit, "storyboard_async": True, "voice_async": True}


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
