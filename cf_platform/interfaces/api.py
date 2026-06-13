"""Platform-facing REST API routes for cf_platform, mounted under /platform in src/main.py."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def platform_health() -> dict:
    """Return the cf_platform subsystem health status."""
    return {"status": "ok"}
