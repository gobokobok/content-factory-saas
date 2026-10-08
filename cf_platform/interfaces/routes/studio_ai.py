"""Studio routes for per-scene AI images (P14, D104).

    POST /studio/runs/{run_id}/scenes/{scene_n}/generate   generate one scene's image
    GET  /studio/runs/{run_id}/ai-spend                     spend so far, cap, estimate

Generation is always manual and per scene: nothing here runs during acquisition.
The route is a thin wrapper — provider and key come from the tenant's settings
(cf_platform/core/tenant_settings.py), the prompt and ledger logic from
cf_platform/core/ai_images.py.
"""

import hashlib
import logging
from datetime import datetime

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cf_platform.core.ai_images import (
    SpendCapReachedError,
    build_prompt,
    ensure_under_cap,
    read_spend,
    record_spend,
    spend_summary,
)
from cf_platform.core.artifact_manager import ArtifactStorage
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.image_provider import ImageGenerationError, build_image_provider
from cf_platform.core.integrations import resolve_defaults
from cf_platform.core.projects import ProjectNotFoundError, ProjectRepository
from cf_platform.core.run_manager import RunNotFoundError, RunRepository
from cf_platform.core.secret_box import SecretBoxError
from cf_platform.core.tenant_settings import TenantSettingsRepository, resolve_image_config
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_artifact_storage,
    get_project_repository,
    get_run_repository,
    get_tenant_settings_repository,
)
from cf_platform.interfaces.routes.studio import (
    _apply_scene_edit_to_storyboard,
    _load_manifest,
    _load_storyboard,
    _write_manifest,
)

_logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_ASPECTS = ("9:16", "16:9", "1:1")


class GenerateSceneImageRequest(BaseModel):
    """Request body for POST …/scenes/{scene_n}/generate."""

    prompt: str


async def _project_style(runs: RunRepository, projects: ProjectRepository, run_id: str) -> str | None:
    """The run's project `ai_image_style`, or None when unset or not resolvable (never raises)."""
    try:
        run = await runs.get(run_id)
        project = await projects.get(run.project_id)
    except (RunNotFoundError, ProjectNotFoundError):
        return None
    except Exception:
        _logger.warning("studio_generate: could not read project style for run %s", run_id, exc_info=True)
        return None
    style = (project.config or {}).get("ai_image_style")
    return style.strip() if isinstance(style, str) and style.strip() else None


async def _spend_cap(tenant_repo: TenantSettingsRepository, settings: PlatformSettings) -> float:
    """The per-run AI image cap: the tenant's default, else IMAGE_RUN_SPEND_CAP_USD (never raises)."""
    try:
        return float((await resolve_defaults(tenant_repo, PLATFORM_USER_ID, settings))["spend_cap"])
    except Exception:
        _logger.warning("studio_generate: tenant defaults unavailable — using the ENV spend cap", exc_info=True)
        return settings.IMAGE_RUN_SPEND_CAP_USD


async def _run_aspect(storage: ArtifactStorage, run_id: str, default: str) -> str:
    """The run's aspect ratio from settings.json, else `default`; 9:16 / 16:9 / 1:1 only."""
    try:
        aspect = (await storage.get_json(f"runs/{run_id}/settings.json")).get("aspect_ratio")
    except Exception:
        return default
    return aspect if aspect in _VALID_ASPECTS else default


@router.get("/studio/runs/{run_id}/ai-spend")
async def studio_get_ai_spend(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
    tenant_repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
) -> dict:
    """Return what the run has spent on AI images, its cap and the per-image estimate."""
    ledger = await read_spend(storage, run_id)
    cap = await _spend_cap(tenant_repo, settings)
    return spend_summary(ledger, settings.IMAGE_COST_USD, cap)


@router.post("/studio/runs/{run_id}/scenes/{scene_n}/generate")
async def studio_generate_scene_image(
    run_id: str,
    scene_n: str,
    body: GenerateSceneImageRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
    tenant_repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    runs: RunRepository = Depends(get_run_repository),
    projects: ProjectRepository = Depends(get_project_repository),
) -> dict:
    """Generate one scene's image from the operator's prompt and make it the scene's asset.

    Order matters because the call costs money: validate and check the cap first,
    generate, record the spend, and only then touch the storyboard and manifest —
    so a failure after the paid call never loses the ledger entry. The scene
    becomes an `ai_image` scene carrying the prompt; any previous asset is replaced.
    Responses: 409 no key / cap reached / key unreadable, 422 empty prompt,
    404 unknown scene, 503 settings database unreachable, 502 the provider failed (nothing is changed or charged).
    """
    from cf_platform.workers.acquisition_worker import manifest_entry_for_scene
    from src.models import AI_GENERATED_SOURCE, AWAITING_UPLOAD_STATUS, OPERATOR_SUPPLIED_STRATEGIES, AssetManifest

    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="Write a prompt first.")

    _, storyboard = await _load_storyboard(storage, run_id)
    scene = next((sc for sc in storyboard.scenes if str(sc.scene) == scene_n), None)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_n!r} not found in storyboard.")

    try:
        config = await resolve_image_config(tenant_repo, PLATFORM_USER_ID, settings)
    except SecretBoxError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (psycopg.Error, OSError) as exc:
        _logger.warning("studio_generate: tenant settings unavailable for run %s", run_id, exc_info=True)
        raise HTTPException(
            status_code=503, detail="Settings database is not reachable right now — try again in a moment."
        ) from exc
    if not config.api_key:
        raise HTTPException(
            status_code=409,
            detail="No image API key yet — add a kie.ai or OpenAI key in Settings (Studio → Settings).",
        )

    ledger = await read_spend(storage, run_id)
    cap = await _spend_cap(tenant_repo, settings)
    try:
        ensure_under_cap(ledger, settings.IMAGE_COST_USD, cap)
    except SpendCapReachedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    style = await _project_style(runs, projects, run_id)
    aspect = await _run_aspect(storage, run_id, settings.IMAGE_DEFAULT_ASPECT_RATIO)
    provider = build_image_provider(
        config.provider, config.api_key, config.model,
        quality=settings.IMAGE_QUALITY, resolution=settings.IMAGE_RESOLUTION,
        timeout_s=settings.IMAGE_TIMEOUT_S, poll_interval_s=settings.IMAGE_POLL_INTERVAL_S,
    )
    try:
        image = await provider.generate(build_prompt(style, prompt), aspect)
    except ImageGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    digest = hashlib.sha1(image.data).hexdigest()[:8]
    r2_key = f"runs/{run_id}/images/scene_{scene_n.zfill(2)}_ai_{digest}{image.ext}"
    await storage.put_bytes(r2_key, image.data, content_type=image.content_type)
    ledger = await record_spend(
        storage, run_id, scene=scene_n, cost_usd=settings.IMAGE_COST_USD,
        provider=config.provider, model=config.model,
    )

    # The scene is an AI image scene from now on, whatever it was before.
    await _apply_scene_edit_to_storyboard(
        storage, run_id, scene_n, asset_strategy="ai_image", ai_prompt=prompt, worker="studio_generate",
    )

    manifest = await _load_manifest(storage, run_id)
    if manifest is None:
        entries = [manifest_entry_for_scene(sc) for sc in storyboard.scenes]
        for e in entries:
            if e.asset_strategy in OPERATOR_SUPPLIED_STRATEGIES:
                e.status = AWAITING_UPLOAD_STATUS
        manifest = AssetManifest(run_id=run_id, entries=entries)
    entry = next((e for e in manifest.entries if str(e.scene_id) == scene_n), None)
    if entry is None:
        entry = manifest_entry_for_scene(scene)
        manifest.entries.append(entry)
    entry.asset_strategy = "ai_image"
    entry.ai_prompt = prompt
    entry.file_key = r2_key
    entry.source = AI_GENERATED_SOURCE
    entry.status = "acquired"
    entry.qa_passed = True
    entry.fallback_used = False
    entry.attribution = None
    await _write_manifest(storage, run_id, manifest, "studio_generate")

    try:
        preview_url = await storage.generate_presigned_url(r2_key, expires_in=3600)
    except Exception:
        preview_url = None

    return {
        "scene_n": scene_n,
        "file_key": r2_key,
        "source": AI_GENERATED_SOURCE,
        "preview_url": preview_url,
        "ai_prompt": prompt,
        "spend": spend_summary(ledger, settings.IMAGE_COST_USD, cap),
        "generated_at": datetime.now().isoformat(),
    }
