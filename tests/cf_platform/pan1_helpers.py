"""Shared fixtures for the P-AN1 (Animation mode, D108) tests.

Builds on the P13 helpers: the same in-memory run, with its storyboard replaced
by an Animation one (every scene an `ai_image` scene, a two-entry bible), a fake
image provider, and the image settings the generate routes read.
"""

import asyncio
from contextlib import contextmanager

from cryptography.fernet import Fernet

from cf_platform.core.image_provider import ImageGenerationError, ImageResult
from cf_platform.core.projects import InMemoryProjectRepository
from cf_platform.core.run_manager import InMemoryRunRepository
from cf_platform.core.tenant_settings import InMemoryTenantSettingsRepository
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_project_repository,
    get_run_repository,
    get_tenant_settings_repository,
)
from cf_platform.workers import scene_images
from src.main import app
from src.models import AI_GENERATED_SOURCE, AssetManifest, Storyboard
from tests.cf_platform.p13_helpers import RUN_ID, make_manifest, p13_env, seed_manifest, seed_storyboard

PNG = b"\x89PNG-ai-image"
MASTER_STYLE = "Flat editorial illustration, muted earth palette."
BIBLE = [
    {"id": "learner", "kind": "character", "name": "the learner", "description": "a student with a black bob and round glasses"},
    {"id": "teal_book", "kind": "prop", "name": "the teal book", "description": "a thick teal cloth-bound book"},
]


class FakeProvider:
    """Records each (prompt, aspect) it is asked for; fails for prompts in `fail_on`."""

    calls: list[tuple[str, str]] = []
    # prompt substring -> how many times it still fails
    fail_on: dict[str, int] = {}
    delay_s: float = 0.0

    def __init__(self, provider: str, api_key: str, model: str) -> None:
        """Remember what it was built with."""
        self.name, self.api_key, self.model = provider, api_key, model

    async def generate(self, prompt: str, aspect_ratio: str) -> ImageResult:
        """Return a fixed image, or raise when the prompt is set to fail."""
        if FakeProvider.delay_s:
            await asyncio.sleep(FakeProvider.delay_s)
        for needle, left in FakeProvider.fail_on.items():
            if needle in prompt and left > 0:
                FakeProvider.fail_on[needle] = left - 1
                raise ImageGenerationError(f"provider refused {needle}")
        FakeProvider.calls.append((prompt, aspect_ratio))
        return ImageResult(data=PNG + prompt.encode())


def animation_storyboard(storyboard: Storyboard, **scene_overrides: dict) -> Storyboard:
    """Turn a P13 storyboard into an Animation one: ai_image scenes, prompts, a bible."""
    scenes = []
    for i, scene in enumerate(storyboard.scenes):
        update = {
            "asset_strategy": "ai_image", "asset_tier": "still", "clip_type": "still_with_motion",
            "motion_effect": "zoom_in", "ai_prompt": f"prompt {scene.scene}",
            "visual_concept": f"concept {scene.scene}", "visual_keywords": ["a", "b"],
            "shot": {"size": "wide", "angle": "low"}, "entities": ["learner"] if i == 0 else [],
            "motion_note": "Slow push-in.", "flags": [],
        }
        update.update(scene_overrides.get(str(scene.scene), {}))
        scenes.append(Storyboard.model_validate({
            "global": {"subtitle_style": "", "bg_music": "", "visual_style": ""},
            "scenes": [{**scene.model_dump(by_alias=True, mode="json"), **update}],
            "summary": {"total_scenes": 1, "total_duration_s": 0, "rhythm": ""},
        }).scenes[0])
    return storyboard.model_copy(update={"scenes": scenes, "visual_mode": "ai_animation", "continuity": [
        *Storyboard.model_validate({
            "global": {"subtitle_style": "", "bg_music": "", "visual_style": ""}, "scenes": [],
            "summary": {"total_scenes": 0, "total_duration_s": 0, "rhythm": ""}, "continuity": BIBLE,
        }).continuity
    ]})


def configure_images(env, *, key: str = "env-key", cap: float = 2.0, cost: float = 0.5) -> None:
    """Give the env's settings the image fields and wire in-memory tenant / run / project repos."""
    s = env.settings
    s.SETTINGS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    s.IMAGE_PROVIDER, s.KIE_API_KEY, s.OPENAI_API_KEY = "kie", key, ""
    s.KIE_IMAGE_MODEL, s.OPENAI_IMAGE_MODEL = "kie-model", "oa-model"
    s.IMAGE_QUALITY, s.IMAGE_RESOLUTION, s.IMAGE_DEFAULT_ASPECT_RATIO = "medium", "1K", "9:16"
    s.IMAGE_TIMEOUT_S, s.IMAGE_POLL_INTERVAL_S = 5, 0
    s.IMAGE_COST_USD, s.IMAGE_RUN_SPEND_CAP_USD = cost, cap
    s.IMAGE_MODEL_COSTS_USD, s.IMAGE_RUN_SPEND_CAP_MAX_USD, s.IMAGE_JOB_CONCURRENCY = {}, 10.0, 2
    tenant = InMemoryTenantSettingsRepository()
    app.dependency_overrides[get_tenant_settings_repository] = lambda: tenant
    app.dependency_overrides[get_run_repository] = lambda: InMemoryRunRepository()
    app.dependency_overrides[get_project_repository] = lambda: InMemoryProjectRepository(PLATFORM_USER_ID)


@contextmanager
def animation_env(
    monkeypatch,
    *,
    with_images_for: tuple[str, ...] = (),
    settings: dict | None = None,
    cap: float = 2.0,
    cost: float = 0.5,
    starts: tuple[int, ...] = (0, 4, 8),
    **scene_overrides: dict,
):
    """Yield a P13Env whose run has an Animation storyboard and a fake image provider.

    `with_images_for` names the scenes that already have a generated image.
    `settings` is the run's settings.json (visual_mode defaults to ai_animation).
    """
    FakeProvider.calls, FakeProvider.fail_on, FakeProvider.delay_s = [], {}, 0.0
    scene_images._ACTIVE_JOBS.clear()
    scene_images._RESERVED_USD.clear()
    scene_images._RUN_LOCKS.clear()
    monkeypatch.setattr(
        "cf_platform.interfaces.routes.studio_ai.build_image_provider",
        lambda provider, api_key, model, **kw: FakeProvider(provider, api_key, model),
    )
    with p13_env(starts=starts) as env:
        _, base = asyncio.run(_load(env.storage))
        storyboard = animation_storyboard(base, **scene_overrides)

        async def _seed() -> None:
            """Store the Animation storyboard, the run settings and any existing images."""
            await seed_storyboard(env.storage, storyboard)
            await env.storage.put_json(
                f"runs/{RUN_ID}/settings.json",
                {"visual_mode": "ai_animation", "master_style": MASTER_STYLE, "aspect_ratio": "9:16", **(settings or {})},
            )
            if with_images_for:
                manifest = make_manifest(storyboard, acquired=False)
                for entry in manifest.entries:
                    if entry.scene_id in with_images_for:
                        entry.status, entry.source = "acquired", AI_GENERATED_SOURCE
                        entry.file_key = f"runs/{RUN_ID}/images/scene_{entry.scene_id}_ai_old.png"
                    else:
                        entry.status = "awaiting_upload"
                await seed_manifest(env.storage, AssetManifest(run_id=RUN_ID, entries=manifest.entries))

        asyncio.run(_seed())
        configure_images(env, cap=cap, cost=cost)
        try:
            yield env
        finally:
            for dep in (get_tenant_settings_repository, get_run_repository, get_project_repository):
                app.dependency_overrides.pop(dep, None)


async def _load(storage):
    """Return (artifact_body, Storyboard) of the seeded run."""
    from cf_platform.interfaces.routes.studio import _load_storyboard

    return await _load_storyboard(storage, RUN_ID)
