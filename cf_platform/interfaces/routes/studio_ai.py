"""Studio routes for AI images (P14, D104; Animation mode P-AN1, D108).

    POST /studio/runs/{run_id}/scenes/{scene_n}/generate        generate one scene's image
    POST /studio/runs/{run_id}/scenes/{scene_n}/prompt-preview  the exact text the model would get
    GET  /studio/runs/{run_id}/ai-spend                         spend so far, cap, estimate
    GET  /studio/runs/{run_id}/images/plan                      what Generate all would do and cost
    POST /studio/runs/{run_id}/images/generate                  start the bulk job (202)
    GET  /studio/runs/{run_id}/images/status                    bulk job progress

Nothing here runs during acquisition: an image is only ever generated because
the operator pressed Generate on a scene or confirmed Generate all. The routes
are thin wrappers — provider and key come from the tenant's settings
(cf_platform/core/tenant_settings.py), the prompt and ledger logic from
cf_platform/core/ai_images.py, and the generation itself, shared by the
per-scene route and the bulk job, from cf_platform/workers/scene_images.py.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

import psycopg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

from cf_platform.core.ai_images import (
    SpendCapReachedError,
    effective_spend_cap,
    model_cost_usd,
    read_spend,
    spend_summary,
)
from cf_platform.core.artifact_manager import ArtifactStorage
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.image_provider import ImageGenerationError, build_image_provider
from cf_platform.core.integrations import resolve_defaults
from cf_platform.core.projects import ProjectRepository
from cf_platform.core.run_manager import RunRepository
from cf_platform.core.run_visuals import RunVisuals, load_run_visuals, save_run_spend_cap
from cf_platform.core.secret_box import SecretBoxError
from cf_platform.core.tenant_settings import ImageConfig, TenantSettingsRepository, resolve_image_config
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_artifact_storage,
    get_project_repository,
    get_run_repository,
    get_tenant_settings_repository,
)
from cf_platform.interfaces.routes.studio import _load_manifest, _load_storyboard
from cf_platform.workers.scene_images import (
    JOB_RUNNING,
    EmptyPromptError,
    ImageGenContext,
    SceneNotFoundError,
    assemble_scene_prompt,
    claim_job,
    generate_scene_image,
    images_job_key,
    job_is_active,
    new_job_document,
    read_job,
    release_job,
    run_image_job,
    scenes_missing_images,
    stale_scene_ids,
)

_logger = logging.getLogger(__name__)

router = APIRouter()


class GenerateSceneImageRequest(BaseModel):
    """Request body for POST …/scenes/{scene_n}/generate."""

    prompt: str


class PromptPreviewRequest(BaseModel):
    """Request body for POST …/scenes/{scene_n}/prompt-preview; no prompt means the scene's stored one."""

    prompt: str | None = None


class GenerateAllRequest(BaseModel):
    """Request body for POST …/images/generate.

    `scene_ids` names the scenes to (re)generate even when they already have an
    image; without it every AI-image scene that has none is generated.
    `spend_cap_usd` sets the cap for this run, up to IMAGE_RUN_SPEND_CAP_MAX_USD.
    """

    scene_ids: list[str] | None = None
    spend_cap_usd: float | None = None


def _max_cap(settings: PlatformSettings) -> float:
    """The highest cap one run may be given (IMAGE_RUN_SPEND_CAP_MAX_USD)."""
    return float(getattr(settings, "IMAGE_RUN_SPEND_CAP_MAX_USD", 10.0))


def _image_cost(settings: PlatformSettings, model: str) -> float:
    """The estimated price of one image on `model` (IMAGE_MODEL_COSTS_USD, else IMAGE_COST_USD)."""
    costs = getattr(settings, "IMAGE_MODEL_COSTS_USD", None)
    return model_cost_usd(model, costs if isinstance(costs, dict) else None, settings.IMAGE_COST_USD)


async def _default_cap(tenant_repo: TenantSettingsRepository, settings: PlatformSettings) -> float:
    """The tenant's default per-run AI image cap, else IMAGE_RUN_SPEND_CAP_USD (never raises)."""
    try:
        return float((await resolve_defaults(tenant_repo, PLATFORM_USER_ID, settings))["spend_cap"])
    except Exception:
        _logger.warning("studio_generate: tenant defaults unavailable — using the ENV spend cap", exc_info=True)
        return settings.IMAGE_RUN_SPEND_CAP_USD


async def _run_cap(
    tenant_repo: TenantSettingsRepository, settings: PlatformSettings, visuals: RunVisuals
) -> float:
    """The cap this run generates under: its own when set, else the tenant default."""
    return effective_spend_cap(visuals.spend_cap_usd, await _default_cap(tenant_repo, settings), _max_cap(settings))


async def _image_model(tenant_repo: TenantSettingsRepository, settings: PlatformSettings) -> str:
    """The model images would be generated on, '' when it cannot be resolved (never raises)."""
    try:
        return (await resolve_image_config(tenant_repo, PLATFORM_USER_ID, settings)).model
    except Exception:
        return ""


async def _resolve_config(
    tenant_repo: TenantSettingsRepository, settings: PlatformSettings, run_id: str
) -> ImageConfig:
    """Provider, model and key, or the HTTP error that says why there are none.

    409 when the saved key cannot be read or no key exists; 503 when the settings
    database is unreachable.
    """
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
    return config


async def _generation_context(
    run_id: str,
    storage: ArtifactStorage,
    settings: PlatformSettings,
    tenant_repo: TenantSettingsRepository,
    runs: RunRepository,
    projects: ProjectRepository,
) -> ImageGenContext:
    """Resolve everything a generation needs for this run; HTTP errors as in _resolve_config."""
    config = await _resolve_config(tenant_repo, settings, run_id)
    visuals = await load_run_visuals(storage, run_id, runs, projects)
    provider = build_image_provider(
        config.provider, config.api_key, config.model,
        quality=settings.IMAGE_QUALITY, resolution=settings.IMAGE_RESOLUTION,
        timeout_s=settings.IMAGE_TIMEOUT_S, poll_interval_s=settings.IMAGE_POLL_INTERVAL_S,
    )
    return ImageGenContext(
        storage=storage,
        run_id=run_id,
        provider=provider,
        provider_name=config.provider,
        model=config.model,
        cost_usd=_image_cost(settings, config.model),
        cap_usd=await _run_cap(tenant_repo, settings, visuals),
        aspect_ratio=visuals.aspect_ratio or settings.IMAGE_DEFAULT_ASPECT_RATIO,
        master_style=visuals.master_style,
        project_style=visuals.project_style,
    )


@router.get("/studio/runs/{run_id}/ai-spend")
async def studio_get_ai_spend(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
    tenant_repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
) -> dict:
    """Return what the run has spent on AI images, its cap and the per-image estimate."""
    ledger = await read_spend(storage, run_id)
    visuals = await load_run_visuals(storage, run_id)
    cap = await _run_cap(tenant_repo, settings, visuals)
    model = await _image_model(tenant_repo, settings)
    return {**spend_summary(ledger, _image_cost(settings, model), cap), "cap_max_usd": _max_cap(settings), "model": model}


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

    The work is in scene_images.generate_scene_image: validate and check the cap,
    generate, record the spend, and only then touch the storyboard and manifest.
    The scene becomes an `ai_image` scene carrying the prompt; any previous asset
    is replaced. In an Animation run the text sent to the model is assembled from
    the prompt, the scene's bible entries, the fixed lines, the master style and
    the aspect phrase (D108); otherwise the project's style is put in front (D104).
    Responses: 409 no key / cap reached / key unreadable, 422 empty prompt,
    404 unknown scene, 503 settings database unreachable, 502 the provider failed
    (nothing is changed or charged).
    """
    from src.models import AI_GENERATED_SOURCE

    if not body.prompt.strip():
        raise HTTPException(status_code=422, detail="Write a prompt first.")
    _, storyboard = await _load_storyboard(storage, run_id)
    if not any(str(sc.scene) == scene_n for sc in storyboard.scenes):
        raise HTTPException(status_code=404, detail=f"Scene {scene_n!r} not found in storyboard.")

    ctx = await _generation_context(run_id, storage, settings, tenant_repo, runs, projects)
    try:
        result = await generate_scene_image(ctx, scene_n, body.prompt)
    except SceneNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EmptyPromptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SpendCapReachedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ImageGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        preview_url = await storage.generate_presigned_url(result["file_key"], expires_in=3600)
    except Exception:
        preview_url = None
    return {
        "scene_n": scene_n,
        "file_key": result["file_key"],
        "source": AI_GENERATED_SOURCE,
        "preview_url": preview_url,
        "ai_prompt": result["ai_prompt"],
        "spend": spend_summary(result["ledger"], ctx.cost_usd, ctx.cap_usd),
        "generated_at": datetime.now().isoformat(),
    }


@router.post("/studio/runs/{run_id}/scenes/{scene_n}/prompt-preview")
async def studio_preview_scene_prompt(
    run_id: str,
    scene_n: str,
    body: PromptPreviewRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
    runs: RunRepository = Depends(get_run_repository),
    projects: ProjectRepository = Depends(get_project_repository),
) -> dict:
    """Return the exact text the image model would receive for this scene. Costs nothing."""
    _, storyboard = await _load_storyboard(storage, run_id)
    scene = next((sc for sc in storyboard.scenes if str(sc.scene) == scene_n), None)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_n!r} not found in storyboard.")
    visuals = await load_run_visuals(storage, run_id, runs, projects)
    prompt = (body.prompt if body.prompt is not None else scene.ai_prompt or "").strip()
    return {
        "scene_n": scene_n,
        "visual_mode": storyboard.visual_mode,
        "text": assemble_scene_prompt(
            storyboard, scene, prompt,
            master_style=visuals.master_style, project_style=visuals.project_style,
            aspect_ratio=visuals.aspect_ratio or settings.IMAGE_DEFAULT_ASPECT_RATIO,
        ),
    }


async def _plan(
    run_id: str,
    storage: ArtifactStorage,
    settings: PlatformSettings,
    tenant_repo: TenantSettingsRepository,
    scene_ids: list[str] | None,
) -> dict[str, Any]:
    """What a bulk generation would do: which scenes, what it costs, what the cap allows.

    Scenes named in `scene_ids` are generated even when they have an image;
    otherwise the AI-image scenes without one. A scene without a prompt is never
    generated — it is listed in `without_prompt` instead.
    """
    _, storyboard = await _load_storyboard(storage, run_id)
    manifest = await _load_manifest(storage, run_id)
    by_id = {str(sc.scene): sc for sc in storyboard.scenes}
    if scene_ids is not None:
        unknown = [s for s in scene_ids if s not in by_id]
        if unknown:
            raise HTTPException(status_code=404, detail=f"Scene {unknown[0]!r} not found in storyboard.")
        wanted = list(dict.fromkeys(scene_ids))
    else:
        wanted = scenes_missing_images(storyboard, manifest)
    with_prompt = [s for s in wanted if (by_id[s].ai_prompt or "").strip()]

    visuals = await load_run_visuals(storage, run_id)
    model = await _image_model(tenant_repo, settings)
    cost = _image_cost(settings, model)
    cap = await _run_cap(tenant_repo, settings, visuals)
    spend = spend_summary(await read_spend(storage, run_id), cost, cap)
    affordable = len(with_prompt) if cost <= 0 else min(len(with_prompt), int((spend["remaining_usd"] + 1e-9) // cost))
    return {
        "scene_ids": with_prompt,
        "count": len(with_prompt),
        "without_prompt": [s for s in wanted if s not in with_prompt],
        "out_of_date": stale_scene_ids(storyboard),
        "model": model,
        "cost_per_image_usd": cost,
        "estimated_cost_usd": round(cost * len(with_prompt), 4),
        "spent_usd": spend["spent_usd"],
        "cap_usd": cap,
        "remaining_usd": spend["remaining_usd"],
        "cap_max_usd": _max_cap(settings),
        "affordable": affordable,
        "job_active": job_is_active(run_id),
    }


@router.get("/studio/runs/{run_id}/images/plan")
async def studio_images_plan(
    run_id: str,
    scene_ids: str | None = Query(default=None, description="Comma-separated scene ids to regenerate"),
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
    tenant_repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
) -> dict:
    """Scene count, estimated cost and remaining cap for Generate all — shown before anything is spent."""
    ids = [s for s in scene_ids.split(",") if s] if scene_ids else None
    return await _plan(run_id, storage, settings, tenant_repo, ids)


@router.post("/studio/runs/{run_id}/images/generate", status_code=202)
async def studio_generate_all_images(
    run_id: str,
    body: GenerateAllRequest,
    background_tasks: BackgroundTasks,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
    tenant_repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
    runs: RunRepository = Depends(get_run_repository),
    projects: ProjectRepository = Depends(get_project_repository),
) -> dict:
    """Start generating the run's missing images in the background (the operator confirmed the cost).

    Poll GET …/images/status. Starting it while a job is running returns that job
    and starts nothing. After a server restart the job can be started again and
    picks up the scenes still missing. `spend_cap_usd` sets this run's cap first
    (422 above IMAGE_RUN_SPEND_CAP_MAX_USD). Other responses as for the per-scene
    route: 409 no key, 503 settings database unreachable, 404 unknown scene.
    """
    if job_is_active(run_id):
        return {"status": JOB_RUNNING, "already_running": True, "job": await read_job(storage, run_id)}

    if body.spend_cap_usd is not None:
        max_cap = _max_cap(settings)
        if not 0 <= body.spend_cap_usd <= max_cap + 1e-9:
            raise HTTPException(
                status_code=422,
                detail=f"The cap for one run can be at most ${max_cap:.2f} (IMAGE_RUN_SPEND_CAP_MAX_USD).",
            )
        await save_run_spend_cap(storage, run_id, body.spend_cap_usd)

    plan = await _plan(run_id, storage, settings, tenant_repo, body.scene_ids)
    if not plan["scene_ids"]:
        return {"status": "nothing_to_do", "already_running": False, "plan": plan}
    ctx = await _generation_context(run_id, storage, settings, tenant_repo, runs, projects)

    if not claim_job(run_id):
        return {"status": JOB_RUNNING, "already_running": True, "job": await read_job(storage, run_id)}
    job_id = str(uuid.uuid4())
    try:
        job = new_job_document(job_id, plan["scene_ids"])
        await storage.put_json(images_job_key(run_id), job)
        background_tasks.add_task(
            run_image_job, ctx, plan["scene_ids"],
            job_id=job_id, concurrency=int(getattr(settings, "IMAGE_JOB_CONCURRENCY", 3)),
        )
    except Exception:
        release_job(run_id)
        raise
    _logger.info("image job %s enqueued for run %s (%d scenes)", job_id, run_id, len(plan["scene_ids"]))
    return {"status": JOB_RUNNING, "already_running": False, "job": job, "plan": plan}


@router.get("/studio/runs/{run_id}/images/status")
async def studio_images_status(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Bulk image job progress: {status, total, done, failed, left, scenes, message}; status 'none' when no job ran."""
    job = await read_job(storage, run_id)
    return job if job is not None else {"status": "none"}
