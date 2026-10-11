"""Which providers and models a run used (P-INT1-S4).

    GET /studio/runs/{run_id}/providers

Two honest views side by side: what each artifact the run already has was made
with (read from its lineage — worker, model, prompt version, as recorded when it
was written), and what each block's default is right now (what the next step
would use). They differ when the defaults changed after the run was made.
"""

from typing import Any

from fastapi import APIRouter, Depends

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.providers import BLOCKS, resolve_block
from cf_platform.core.tenant_settings import TenantSettingsRepository
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_artifact_storage,
    get_tenant_settings_repository,
)
from cf_platform.interfaces.routes._helpers import latest_artifact_key

router = APIRouter()

# (label, stage, artifact name) of what a run produces, in pipeline order.
_STEPS = (
    ("Script", "script", "script"),
    ("Voice", "voice", "voice_alignment"),
    ("Storyboard", "storyboard", "verified_storyboard"),
    ("Metadata", "metadata", "youtube_metadata"),
)


@router.get("/studio/runs/{run_id}/providers")
async def studio_run_providers(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict[str, Any]:
    """What this run's artifacts were made with, and what each block would use now."""
    made: list[dict[str, Any]] = []
    for label, stage, name in _STEPS:
        key = await latest_artifact_key(storage, run_id, stage, name)
        if not key:
            continue
        try:
            record, _ = await read_artifact(storage, key)
        except Exception:
            continue
        lineage = record.lineage
        made.append({
            "step": label, "worker": lineage.worker, "model": lineage.model,
            "prompt_version": lineage.prompt_version,
        })
    now: list[dict[str, Any]] = []
    for block in BLOCKS:
        for role in block.roles:
            choice = await resolve_block(repo, PLATFORM_USER_ID, settings, block.block_id, role)
            now.append({
                "block": block.name, "role": role, "provider": choice["provider"],
                "model": choice["model"], "has_key": bool(choice["api_key"]),
            })
    return {"made_with": made, "defaults_now": now}
