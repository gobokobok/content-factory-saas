"""Small helpers shared by multiple route modules (not a route module itself)."""

from cf_platform.core.artifact_manager import ArtifactStorage
from cf_platform.interfaces.dependencies import PLATFORM_USER_ID


async def latest_artifact_key(storage: ArtifactStorage, run_id: str, stage: str, name: str) -> str | None:
    """Return the R2 key for the latest version of an artifact, or None if absent."""
    prefix = f"users/{PLATFORM_USER_ID}/runs/{run_id}/{stage}/{name}@v"
    keys = await storage.list_keys(prefix)
    return sorted(keys)[-1] if keys else None
