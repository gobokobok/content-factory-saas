"""Generating scene images: one scene, or every scene of a run (P14 / P-AN1-S5, D104, D108).

`generate_scene_image` is the one place an image is paid for. The per-scene
Generate route and the bulk job are thin wrappers around it, so both follow the
same order, which matters because the call costs money:

    check the cap (counting generations already under way) → generate →
    record the spend → store the file → update storyboard and manifest

A failure after the paid call never loses the ledger entry.

`run_image_job` generates many scenes in the background with a concurrency
limit. It retries a failed scene once, keeps going when one scene fails, stops
cleanly at the spend cap, and writes its progress to
`runs/{run_id}/images/current_job.json` for Studio to poll.

Storyboard and manifest are versioned artifacts updated by read-modify-write, so
every commit for a run happens under that run's lock; only the provider calls
run in parallel. The locks are process-local, which matches the single web
process the platform runs as.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cf_platform.core.ai_images import (
    SpendCapReachedError,
    build_animation_prompt,
    build_prompt,
    ensure_under_cap,
    read_spend,
    record_spend,
)
from cf_platform.core.artifact_manager import ArtifactStorage
from cf_platform.core.image_provider import ImageGenerationError, ImageProvider
from src.models import (
    AI_GENERATED_SOURCE,
    ANIMATION_MODE,
    AWAITING_UPLOAD_STATUS,
    OPERATOR_SUPPLIED_STRATEGIES,
    SCENE_FLAG_IMAGE_STALE,
    SCENE_FLAG_NEEDS_PROMPT,
    AssetManifest,
    Storyboard,
    StoryboardScene,
    effective_asset_strategy,
)

logger = logging.getLogger(__name__)

# Scene states in the job document.
PENDING, RUNNING, DONE, FAILED, NOT_STARTED = "pending", "running", "done", "failed", "not_started"
# Job states. INTERRUPTED is never stored: it is what a "running" document means
# when no job is alive in this process (the server restarted).
JOB_RUNNING, JOB_COMPLETE, JOB_STOPPED_AT_CAP, JOB_ERROR, JOB_INTERRUPTED = (
    "running", "complete", "stopped_at_cap", "error", "interrupted",
)

_RUN_LOCKS: dict[str, asyncio.Lock] = {}
_RESERVED_USD: dict[str, float] = {}
_ACTIVE_JOBS: set[str] = set()


class SceneNotFoundError(LookupError):
    """Raised when the storyboard has no scene with the given id."""


class EmptyPromptError(ValueError):
    """Raised when a scene has no prompt to generate from."""


@dataclass
class ImageGenContext:
    """Everything one image generation needs, resolved by the caller."""

    storage: ArtifactStorage
    run_id: str
    provider: ImageProvider
    provider_name: str
    model: str
    cost_usd: float
    cap_usd: float
    aspect_ratio: str
    # Animation mode: the run's master style (run, else project). Stock mode: the project style.
    master_style: str | None = None
    project_style: str | None = None


def run_lock(run_id: str) -> asyncio.Lock:
    """The lock serialising storyboard / manifest / ledger writes of one run."""
    return _RUN_LOCKS.setdefault(run_id, asyncio.Lock())


def images_job_key(run_id: str) -> str:
    """R2 key of a run's bulk image job document."""
    return f"runs/{run_id}/images/current_job.json"


def job_is_active(run_id: str) -> bool:
    """True while a bulk image job for the run is alive in this process."""
    return run_id in _ACTIVE_JOBS


def claim_job(run_id: str) -> bool:
    """Mark the run's bulk job as started; False when one is already running.

    Synchronous on purpose: check and claim happen without an await between them,
    so two requests cannot both start a job.
    """
    if run_id in _ACTIVE_JOBS:
        return False
    _ACTIVE_JOBS.add(run_id)
    return True


def release_job(run_id: str) -> None:
    """Forget the run's bulk job (it finished, or never got scheduled)."""
    _ACTIVE_JOBS.discard(run_id)


def assemble_scene_prompt(
    storyboard: Storyboard,
    scene: StoryboardScene,
    prompt: str,
    *,
    master_style: str | None,
    project_style: str | None,
    aspect_ratio: str | None,
) -> str:
    """The exact text sent to the image model for a scene.

    An Animation storyboard gets the assembled prompt (D108). Any other storyboard
    keeps the P14 behaviour: the project's style, then the prompt.
    """
    if storyboard.visual_mode == ANIMATION_MODE:
        return build_animation_prompt(
            prompt,
            entities=scene.entities,
            continuity=storyboard.continuity,
            has_overlay=bool((scene.on_screen_text or "").strip()),
            master_style=master_style,
            aspect_ratio=aspect_ratio,
        )
    return build_prompt(project_style, prompt)


def scene_has_image(scene: StoryboardScene, manifest: AssetManifest | None) -> bool:
    """True when the scene's manifest entry holds a generated image."""
    if manifest is None:
        return False
    entry = next((e for e in manifest.entries if str(e.scene_id) == str(scene.scene)), None)
    return bool(entry and entry.status == "acquired" and entry.file_key and entry.source == AI_GENERATED_SOURCE)


def scenes_missing_images(storyboard: Storyboard, manifest: AssetManifest | None) -> list[str]:
    """Ids of the AI-image scenes that have no generated image yet, in storyboard order."""
    return [
        str(scene.scene)
        for scene in storyboard.scenes
        if effective_asset_strategy(scene.asset_strategy, scene.asset_tier, scene.clip_type) == "ai_image"
        and not scene_has_image(scene, manifest)
    ]


def stale_scene_ids(storyboard: Storyboard) -> list[str]:
    """Ids of the scenes whose image predates a change to a bible entry they use."""
    return [str(s.scene) for s in storyboard.scenes if SCENE_FLAG_IMAGE_STALE in s.flags]


async def _commit_scene_image(ctx: ImageGenContext, scene_n: str, prompt: str, r2_key: str, worker: str) -> None:
    """Point the scene at its new image: storyboard first, then the manifest.

    Caller holds the run lock. The storyboard is only rewritten when the scene
    actually changes (strategy, prompt or a cleared flag) — in a bulk job on an
    Animation storyboard it usually does not.
    """
    from cf_platform.interfaces.routes.studio import (
        _load_manifest,
        _load_storyboard,
        _write_manifest,
        _write_storyboard,
    )
    from cf_platform.workers.acquisition_worker import manifest_entry_for_scene
    from cf_platform.workers.storyboard_worker import _apply_patches_and_render_options, apply_asset_strategy

    artifact_body, storyboard = await _load_storyboard(ctx.storage, ctx.run_id)
    scene = next((sc for sc in storyboard.scenes if str(sc.scene) == scene_n), None)
    if scene is None:
        raise SceneNotFoundError(f"Scene {scene_n!r} is no longer in the storyboard.")
    cleared = [f for f in scene.flags if f not in (SCENE_FLAG_IMAGE_STALE, SCENE_FLAG_NEEDS_PROMPT)]
    if scene.asset_strategy != "ai_image" or scene.ai_prompt != prompt or cleared != scene.flags:
        updated = apply_asset_strategy(scene, "ai_image").model_copy(update={"ai_prompt": prompt, "flags": cleared})
        scenes = [updated if str(sc.scene) == scene_n else sc for sc in storyboard.scenes]
        storyboard = _apply_patches_and_render_options(storyboard.model_copy(update={"scenes": scenes}), [])
        await _write_storyboard(ctx.storage, ctx.run_id, artifact_body, storyboard, worker)
        scene = updated

    manifest = await _load_manifest(ctx.storage, ctx.run_id)
    if manifest is None:
        entries = [manifest_entry_for_scene(sc) for sc in storyboard.scenes]
        for e in entries:
            if e.asset_strategy in OPERATOR_SUPPLIED_STRATEGIES:
                e.status = AWAITING_UPLOAD_STATUS
        manifest = AssetManifest(run_id=ctx.run_id, entries=entries)
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
    await _write_manifest(ctx.storage, ctx.run_id, manifest, worker)


async def generate_scene_image(
    ctx: ImageGenContext,
    scene_n: str,
    prompt: str | None = None,
    *,
    worker: str = "studio_generate",
) -> dict[str, Any]:
    """Generate one scene's image and make it the scene's asset.

    `prompt` is the scene-specific prompt; None means the scene's stored
    `ai_prompt`. Returns {scene_n, file_key, ai_prompt, ledger}.

    Raises SceneNotFoundError, EmptyPromptError, SpendCapReachedError (nothing was
    generated or charged) and ImageGenerationError (the provider failed; nothing
    was charged). The storyboard-not-found HTTPException of the Studio loader
    passes through unchanged.
    """
    from cf_platform.interfaces.routes.studio import _load_storyboard

    _, storyboard = await _load_storyboard(ctx.storage, ctx.run_id)
    scene = next((sc for sc in storyboard.scenes if str(sc.scene) == scene_n), None)
    if scene is None:
        raise SceneNotFoundError(f"Scene {scene_n!r} not found in storyboard.")
    prompt = (prompt if prompt is not None else scene.ai_prompt or "").strip()
    if not prompt:
        raise EmptyPromptError("Write a prompt first.")
    text = assemble_scene_prompt(
        storyboard, scene, prompt,
        master_style=ctx.master_style, project_style=ctx.project_style, aspect_ratio=ctx.aspect_ratio,
    )

    lock = run_lock(ctx.run_id)
    async with lock:
        ledger = await read_spend(ctx.storage, ctx.run_id)
        ensure_under_cap(ledger, ctx.cost_usd, ctx.cap_usd, _RESERVED_USD.get(ctx.run_id, 0.0))
        _RESERVED_USD[ctx.run_id] = _RESERVED_USD.get(ctx.run_id, 0.0) + ctx.cost_usd

    paid = False
    try:
        image = await ctx.provider.generate(text, ctx.aspect_ratio)
        paid = True
    finally:
        if not paid:
            _RESERVED_USD[ctx.run_id] = max(_RESERVED_USD.get(ctx.run_id, 0.0) - ctx.cost_usd, 0.0)

    async with lock:
        try:
            ledger = await record_spend(
                ctx.storage, ctx.run_id, scene=scene_n, cost_usd=ctx.cost_usd,
                provider=ctx.provider_name, model=ctx.model,
            )
        finally:
            _RESERVED_USD[ctx.run_id] = max(_RESERVED_USD.get(ctx.run_id, 0.0) - ctx.cost_usd, 0.0)
        digest = hashlib.sha1(image.data).hexdigest()[:8]
        r2_key = f"runs/{ctx.run_id}/images/scene_{scene_n.zfill(2)}_ai_{digest}{image.ext}"
        await ctx.storage.put_bytes(r2_key, image.data, content_type=image.content_type)
        await _commit_scene_image(ctx, scene_n, prompt, r2_key, worker)

    return {"scene_n": scene_n, "file_key": r2_key, "ai_prompt": prompt, "ledger": ledger}


# ── Bulk job ──────────────────────────────────────────────────────────────


def new_job_document(job_id: str, scene_ids: list[str]) -> dict[str, Any]:
    """The job document as it is when the job starts."""
    return {
        "job_id": job_id,
        "status": JOB_RUNNING,
        "total": len(scene_ids),
        "done": 0,
        "failed": [],
        "left": len(scene_ids),
        "scenes": {scene_id: PENDING for scene_id in scene_ids},
        "message": "",
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": None,
    }


def _summarise(job: dict[str, Any]) -> None:
    """Recompute the job's counters from its per-scene states, in place."""
    states = list(job["scenes"].values())
    job["done"] = states.count(DONE)
    job["left"] = sum(1 for s in states if s in (PENDING, RUNNING, NOT_STARTED))


async def run_image_job(
    ctx: ImageGenContext,
    scene_ids: list[str],
    *,
    job_id: str,
    concurrency: int = 3,
) -> dict[str, Any]:
    """Generate an image for each of `scene_ids`; returns the final job document.

    Up to `concurrency` generations run at once. A scene whose generation fails is
    retried once, then reported with its reason while the rest continue. When the
    spend cap is reached no further scene is started: the job ends
    `stopped_at_cap` and says how many scenes are left. Nothing here raises —
    every outcome is in the document. The caller must have claimed the job
    (`claim_job`); it is released here.
    """
    job = new_job_document(job_id, scene_ids)
    job_key = images_job_key(ctx.run_id)
    write_lock = asyncio.Lock()
    at_cap = asyncio.Event()
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def _save() -> None:
        """Write the job document; a failed progress write must not stop the job."""
        async with write_lock:
            _summarise(job)
            try:
                await ctx.storage.put_json(job_key, job)
            except Exception:
                logger.warning("image job %s: could not write progress", job_id, exc_info=True)

    async def _one(scene_id: str) -> None:
        """Generate one scene, with one retry on a provider failure."""
        async with semaphore:
            if at_cap.is_set():
                job["scenes"][scene_id] = NOT_STARTED
                return
            job["scenes"][scene_id] = RUNNING
            await _save()
            reason = ""
            for attempt in (1, 2):
                try:
                    await generate_scene_image(ctx, scene_id, worker="studio_generate_all")
                    job["scenes"][scene_id] = DONE
                    break
                except SpendCapReachedError as exc:
                    at_cap.set()
                    job["scenes"][scene_id] = NOT_STARTED
                    job["message"] = str(exc)
                    break
                except ImageGenerationError as exc:
                    reason = str(exc)
                    logger.warning("image job %s: scene %s attempt %d failed: %s", job_id, scene_id, attempt, reason)
                except EmptyPromptError:
                    reason = "This scene has no image prompt."
                    break
                except Exception as exc:
                    logger.exception("image job %s: scene %s failed", job_id, scene_id)
                    reason = getattr(exc, "detail", None) or str(exc) or type(exc).__name__
                    break
            if job["scenes"][scene_id] == RUNNING:
                job["scenes"][scene_id] = FAILED
                job["failed"].append({"scene": scene_id, "reason": reason})
            await _save()

    try:
        await _save()
        await asyncio.gather(*(_one(scene_id) for scene_id in scene_ids))
        job["status"] = JOB_STOPPED_AT_CAP if at_cap.is_set() else JOB_COMPLETE
    except Exception as exc:  # defensive: _one swallows its own errors
        logger.exception("image job %s failed", job_id)
        job["status"] = JOB_ERROR
        job["message"] = str(exc)
    finally:
        job["finished_at"] = datetime.now(UTC).isoformat()
        release_job(ctx.run_id)
        await _save()
    if job["status"] == JOB_STOPPED_AT_CAP:
        job["message"] = (
            f"Stopped at the spend cap of ${ctx.cap_usd:.2f}: {job['left']} "
            f"scene{'s' if job['left'] != 1 else ''} left. Raise the cap for this run to continue."
        )
        await _save()
    logger.info(
        "image job %s for run %s: %s — %d done, %d failed, %d left",
        job_id, ctx.run_id, job["status"], job["done"], len(job["failed"]), job["left"],
    )
    return job


async def read_job(storage: ArtifactStorage, run_id: str) -> dict[str, Any] | None:
    """The run's job document as Studio should see it, or None when no job ever ran.

    A stored `running` job that is not alive in this process was cut short by a
    restart: it is reported as `interrupted`, and its unfinished scenes as not
    started, so the operator can start it again and pick up what is missing.
    """
    try:
        job = await storage.get_json(images_job_key(run_id))
    except Exception:
        return None
    if not isinstance(job, dict) or "scenes" not in job:
        return None
    if job.get("status") == JOB_RUNNING and not job_is_active(run_id):
        job["status"] = JOB_INTERRUPTED
        job["scenes"] = {k: (NOT_STARTED if v in (PENDING, RUNNING) else v) for k, v in job["scenes"].items()}
        _summarise(job)
        job["message"] = "The server restarted while images were being generated. Start again to finish the rest."
    return job
