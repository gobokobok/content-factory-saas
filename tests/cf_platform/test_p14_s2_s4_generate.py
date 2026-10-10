"""Tests for P14-S2..S4: tenant settings API, per-scene Generate, spend cap and cost display.

The provider is replaced by a fake; nothing here reaches kie.ai or OpenAI.
"""

import asyncio

import pytest
from cryptography.fernet import Fernet

from cf_platform.core.image_provider import ImageGenerationError, ImageResult
from cf_platform.core.projects import InMemoryProjectRepository, update_project
from cf_platform.core.run_manager import InMemoryRunRepository, create_run
from cf_platform.core.tenant_settings import InMemoryTenantSettingsRepository
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_project_repository,
    get_run_repository,
    get_tenant_settings_repository,
)
from src.main import app
from tests.cf_platform.p13_helpers import RUN_ID, p13_env

_GEN = f"/platform/studio/runs/{RUN_ID}/scenes"
_SPEND = f"/platform/studio/runs/{RUN_ID}/ai-spend"
_SETTINGS = "/platform/tenant/settings/image"
PNG = b"\x89PNG-ai-image"


class FakeProvider:
    """Records the prompt it was asked for and returns a fixed image, or fails."""

    calls: list[tuple[str, str]] = []
    fail: str | None = None

    def __init__(self, provider: str, api_key: str, model: str) -> None:
        self.name, self.api_key, self.model = provider, api_key, model

    async def generate(self, prompt: str, aspect_ratio: str) -> ImageResult:
        if FakeProvider.fail:
            raise ImageGenerationError(FakeProvider.fail)
        FakeProvider.calls.append((prompt, aspect_ratio))
        return ImageResult(data=PNG + prompt.encode())


@pytest.fixture(autouse=True)
def _fake_provider(monkeypatch):
    """Swap the provider factory for FakeProvider and reset its state."""
    FakeProvider.calls = []
    FakeProvider.fail = None
    monkeypatch.setattr(
        "cf_platform.interfaces.routes.studio_ai.build_image_provider",
        lambda provider, api_key, model, **kw: FakeProvider(provider, api_key, model),
    )


def _configure(env, *, key: str = "env-key", cap: float = 2.0, cost: float = 0.5) -> InMemoryTenantSettingsRepository:
    """Give the env's settings the image fields and wire in-memory tenant/run/project repos."""
    s = env.settings
    s.SETTINGS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    s.IMAGE_PROVIDER, s.KIE_API_KEY, s.OPENAI_API_KEY = "kie", key, ""
    s.KIE_IMAGE_MODEL, s.OPENAI_IMAGE_MODEL = "kie-model", "oa-model"
    s.IMAGE_QUALITY, s.IMAGE_RESOLUTION, s.IMAGE_DEFAULT_ASPECT_RATIO = "medium", "1K", "9:16"
    s.IMAGE_TIMEOUT_S, s.IMAGE_POLL_INTERVAL_S = 5, 0
    s.IMAGE_COST_USD, s.IMAGE_RUN_SPEND_CAP_USD = cost, cap
    tenant = InMemoryTenantSettingsRepository()
    app.dependency_overrides[get_tenant_settings_repository] = lambda: tenant
    app.dependency_overrides[get_run_repository] = lambda: InMemoryRunRepository()
    app.dependency_overrides[get_project_repository] = lambda: InMemoryProjectRepository(PLATFORM_USER_ID)
    return tenant


def _cleanup() -> None:
    """Remove the repository overrides _configure added."""
    for dep in (get_tenant_settings_repository, get_run_repository, get_project_repository):
        app.dependency_overrides.pop(dep, None)


class TestSettingsApi:
    def test_save_then_read_shows_only_a_hint(self):
        with p13_env() as env:
            try:
                _configure(env, key="")
                r = env.client.put(_SETTINGS, json={"provider": "kie", "api_key": "kie-secret-7777", "model": "m1"})
                assert r.status_code == 200, r.text
                body = env.client.get(_SETTINGS).json()
                assert "kie-secret" not in env.client.get(_SETTINGS).text
                assert body["providers"]["kie"] == {"key_source": "tenant", "key_hint": "7777"}
                assert body["model"] == "m1" and body["provider"] == "kie"
            finally:
                _cleanup()

    def test_unknown_provider_is_422_and_missing_encryption_key_is_409(self):
        with p13_env() as env:
            try:
                _configure(env)
                assert env.client.put(_SETTINGS, json={"provider": "nope"}).status_code == 422
                env.settings.SETTINGS_ENCRYPTION_KEY = ""
                r = env.client.put(_SETTINGS, json={"provider": "kie", "api_key": "abcdefgh1234"})
                assert r.status_code == 409 and "SETTINGS_ENCRYPTION_KEY" in r.json()["detail"]
                assert env.client.get(_SETTINGS).json()["can_save_keys"] is False
            finally:
                _cleanup()

    def test_clearing_a_key_falls_back_to_the_env_key(self):
        with p13_env() as env:
            try:
                _configure(env, key="env-key")
                env.client.put(_SETTINGS, json={"provider": "kie", "api_key": "tenant-key-1111"})
                body = env.client.put(_SETTINGS, json={"clear_key_for": "kie"}).json()
                assert body["providers"]["kie"]["key_source"] == "env"
            finally:
                _cleanup()


class TestGenerate:
    def test_generate_makes_the_scene_an_ai_image_scene(self):
        with p13_env() as env:
            try:
                _configure(env)
                r = env.client.post(f"{_GEN}/2/generate", json={"prompt": "  a quiet street at dusk "})

                assert r.status_code == 200, r.text
                body = r.json()
                assert body["source"] == "ai_generated" and body["ai_prompt"] == "a quiet street at dusk"
                assert body["file_key"].startswith(f"runs/{RUN_ID}/images/scene_2".replace("scene_2", "scene_02_ai_"))
                assert body["spend"]["images"] == 1 and body["spend"]["spent_usd"] == 0.5

                scene = next(s for s in env.scenes() if s["scene"] == "2")
                assert scene["asset_strategy"] == "ai_image" and scene["ai_prompt"] == "a quiet street at dusk"
                assert scene["effective_asset_strategy"] == "ai_image"
                entry = next(e for e in env.manifest_entries() if e["scene_id"] == "2")
                assert (entry["status"], entry["source"], entry["file_key"]) == ("acquired", "ai_generated", body["file_key"])
                assert env.storage._bytes[body["file_key"]].startswith(PNG)
                assert FakeProvider.calls == [("a quiet street at dusk", "9:16")]
            finally:
                _cleanup()

    def test_a_manifest_is_started_when_the_run_has_none_and_other_scenes_stay_pending(self):
        with p13_env() as env:
            try:
                _configure(env)
                env.client.post(f"{_GEN}/2/generate", json={"prompt": "x"})
                entries = {e["scene_id"]: e for e in env.manifest_entries()}
                assert entries["2"]["status"] == "acquired"
                assert entries["1"]["status"] == "pending" and entries["3"]["status"] == "pending"
            finally:
                _cleanup()

    def test_the_project_style_is_added_in_front_when_set_and_absent_otherwise(self):
        with p13_env() as env:
            try:
                _configure(env)
                runs, projects = InMemoryRunRepository(), InMemoryProjectRepository(PLATFORM_USER_ID)
                app.dependency_overrides[get_run_repository] = lambda: runs
                app.dependency_overrides[get_project_repository] = lambda: projects
                asyncio.run(create_run(PLATFORM_USER_ID, "studio", {}, runs, run_id=RUN_ID))

                env.client.post(f"{_GEN}/1/generate", json={"prompt": "a house"})
                asyncio.run(update_project("default", projects, config={"ai_image_style": "flat editorial illustration"}))
                env.client.post(f"{_GEN}/2/generate", json={"prompt": "a house"})

                assert FakeProvider.calls[0][0] == "a house"
                assert FakeProvider.calls[1][0] == "flat editorial illustration\n\na house"
                # The stored prompt is the operator's own words, not the style-prefixed text.
                scene = next(s for s in env.scenes() if s["scene"] == "2")
                assert scene["ai_prompt"] == "a house"
            finally:
                _cleanup()

    def test_the_run_aspect_ratio_is_used(self):
        with p13_env() as env:
            try:
                _configure(env)
                asyncio.run(env.storage.put_json(f"runs/{RUN_ID}/settings.json", {"aspect_ratio": "16:9"}))
                env.client.post(f"{_GEN}/1/generate", json={"prompt": "x"})
                assert FakeProvider.calls[0][1] == "16:9"
            finally:
                _cleanup()

    def test_generating_again_replaces_the_image_and_counts_both(self):
        with p13_env() as env:
            try:
                _configure(env)
                first = env.client.post(f"{_GEN}/2/generate", json={"prompt": "one"}).json()
                second = env.client.post(f"{_GEN}/2/generate", json={"prompt": "two"}).json()
                assert first["file_key"] != second["file_key"]
                entry = next(e for e in env.manifest_entries() if e["scene_id"] == "2")
                assert entry["file_key"] == second["file_key"] and entry["ai_prompt"] == "two"
                assert second["spend"]["images"] == 2 and second["spend"]["spent_usd"] == 1.0
            finally:
                _cleanup()

    def test_it_replaces_a_stock_asset_and_leaves_other_scenes_alone(self):
        with p13_env(with_manifest=True) as env:
            try:
                _configure(env)
                before = {e["scene_id"]: e["file_key"] for e in env.manifest_entries()}
                env.client.post(f"{_GEN}/2/generate", json={"prompt": "x"})
                after = {e["scene_id"]: e["file_key"] for e in env.manifest_entries()}
                assert after["2"] != before["2"] and after["1"] == before["1"] and after["3"] == before["3"]
            finally:
                _cleanup()

    def test_validation_failures_change_nothing_and_cost_nothing(self):
        with p13_env() as env:
            try:
                _configure(env)
                assert env.client.post(f"{_GEN}/2/generate", json={"prompt": "   "}).status_code == 422
                assert env.client.post(f"{_GEN}/99/generate", json={"prompt": "x"}).status_code == 404
                assert FakeProvider.calls == []
                assert env.client.get(_SPEND).json()["images"] == 0
                assert env.versions("storyboard", "verified_storyboard") == 1
            finally:
                _cleanup()

    def test_no_key_is_409_with_a_pointer_to_settings(self):
        with p13_env() as env:
            try:
                _configure(env, key="")
                r = env.client.post(f"{_GEN}/2/generate", json={"prompt": "x"})
                assert r.status_code == 409 and "Settings" in r.json()["detail"]
                assert FakeProvider.calls == []
            finally:
                _cleanup()

    def test_a_tenant_key_is_used_and_beats_the_env_key(self):
        with p13_env() as env:
            try:
                _configure(env, key="env-key")
                env.client.put(_SETTINGS, json={"provider": "kie", "api_key": "tenant-key-5555"})
                seen: dict = {}
                import cf_platform.interfaces.routes.studio_ai as route

                original = route.build_image_provider
                route.build_image_provider = lambda provider, api_key, model, **kw: seen.update(key=api_key) or FakeProvider(provider, api_key, model)
                try:
                    assert env.client.post(f"{_GEN}/2/generate", json={"prompt": "x"}).status_code == 200
                finally:
                    route.build_image_provider = original
                assert seen["key"] == "tenant-key-5555"
            finally:
                _cleanup()

    def test_a_provider_failure_is_502_and_nothing_is_charged_or_changed(self):
        with p13_env(with_manifest=True) as env:
            try:
                _configure(env)
                FakeProvider.fail = "content policy"
                versions = env.versions("acquisition", "asset_manifest")
                r = env.client.post(f"{_GEN}/2/generate", json={"prompt": "x"})
                assert r.status_code == 502 and "content policy" in r.json()["detail"]
                assert env.client.get(_SPEND).json()["images"] == 0
                assert env.versions("acquisition", "asset_manifest") == versions
                assert env.versions("storyboard", "verified_storyboard") == 1
            finally:
                _cleanup()


class TestDatabaseOutage:
    def test_an_unreachable_settings_database_is_503_with_a_message_not_a_500(self):
        import psycopg

        class Broken:
            async def get(self, tenant_id):
                raise psycopg.errors.AdminShutdown("terminating connection due to administrator command")

            async def save(self, settings):
                raise AssertionError("not called")

        with p13_env() as env:
            try:
                _configure(env)
                app.dependency_overrides[get_tenant_settings_repository] = lambda: Broken()
                r = env.client.post(f"{_GEN}/2/generate", json={"prompt": "x"})
                assert r.status_code == 503 and "try again" in r.json()["detail"]
                assert FakeProvider.calls == []
                assert env.client.get(_SPEND).json()["images"] == 0
            finally:
                _cleanup()

    def test_the_pools_check_connections_before_handing_them_out(self):
        import cf_platform.core.db as db

        db._pool = None
        db._checkpoint_pool = None
        try:
            pool = db.get_pool("postgresql://u:p@localhost/x")
            assert pool._check is not None  # replaces connections Postgres closed meanwhile
        finally:
            db._pool = None


class TestSpendCap:
    def test_the_cap_stops_generation_before_the_provider_is_called(self):
        with p13_env() as env:
            try:
                _configure(env, cap=1.0, cost=0.5)
                assert env.client.post(f"{_GEN}/1/generate", json={"prompt": "a"}).status_code == 200
                assert env.client.post(f"{_GEN}/2/generate", json={"prompt": "b"}).status_code == 200
                r = env.client.post(f"{_GEN}/3/generate", json={"prompt": "c"})

                assert r.status_code == 409 and "cap" in r.json()["detail"]
                assert len(FakeProvider.calls) == 2
                third = next(s for s in env.scenes() if s["scene"] == "3")
                assert third.get("asset_strategy") != "ai_image"
            finally:
                _cleanup()

    def test_spend_endpoint_reports_spent_cap_and_estimate(self):
        with p13_env() as env:
            try:
                _configure(env, cap=2.0, cost=0.5)
                assert env.client.get(_SPEND).json() == {
                    "spent_usd": 0.0, "cap_usd": 2.0, "remaining_usd": 2.0, "images": 0, "cost_per_image_usd": 0.5,
                    # P-AN1-S5/S6: the highest cap one run may be given, and the model the estimate is for.
                    "cap_max_usd": 10.0, "model": "kie-model",
                }
                env.client.post(f"{_GEN}/1/generate", json={"prompt": "a"})
                body = env.client.get(_SPEND).json()
                assert (body["spent_usd"], body["remaining_usd"], body["images"]) == (0.5, 1.5, 1)
            finally:
                _cleanup()

    def test_a_replaced_image_still_counts_toward_the_cap(self):
        with p13_env() as env:
            try:
                _configure(env, cap=1.0, cost=0.5)
                env.client.post(f"{_GEN}/1/generate", json={"prompt": "a"})
                env.client.post(f"{_GEN}/1/generate", json={"prompt": "a again"})
                assert env.client.post(f"{_GEN}/1/generate", json={"prompt": "third"}).status_code == 409
            finally:
                _cleanup()


class TestStrategyInteractions:
    def test_acquisition_leaves_an_ai_scene_without_an_image_waiting(self):
        from cf_platform.workers.acquisition_worker import manifest_entry_for_scene
        from src.models import OPERATOR_SUPPLIED_STRATEGIES

        assert "ai_image" in OPERATOR_SUPPLIED_STRATEGIES
        with p13_env() as env:
            r = env.client.patch(f"/platform/studio/runs/{RUN_ID}/storyboard/scenes/2", json={"asset_strategy": "ai_image"})
            assert r.status_code == 200, r.text
            scene = next(s for s in env.scenes() if s["scene"] == "2")
            assert scene["effective_asset_strategy"] == "ai_image"
            assert scene["asset_tier"] in ("still", "still_motion") and scene["clip_type"] == "still_with_motion"
            assert manifest_entry_for_scene(__import__("src.models", fromlist=["StoryboardScene"]).StoryboardScene(
                scene="2", clip_type="still_with_motion", duration_s=1.0, voiceover_line="x", asset_strategy="ai_image",
            )).asset_strategy == "ai_image"

    def test_render_is_refused_with_an_ai_specific_message_for_an_empty_ai_scene(self):
        from cf_platform.workers.render_worker import missing_assets_message

        with p13_env(with_manifest=True, **{"2": {"asset_strategy": "ai_image"}}) as env:
            r = env.client.patch(f"/platform/studio/runs/{RUN_ID}/storyboard/scenes/2", json={"asset_strategy": "ai_image"})
            assert r.status_code == 200
            entries = env.manifest_entries()
            assert next(e for e in entries if e["scene_id"] == "2")["status"] in ("awaiting_upload", "pending")
            from cf_platform.interfaces.routes.studio import _load_manifest, _load_storyboard

            _, storyboard = asyncio.run(_load_storyboard(env.storage, RUN_ID))
            manifest = asyncio.run(_load_manifest(env.storage, RUN_ID))
            message = missing_assets_message(storyboard, manifest)
            assert message and "AI image" in message and "Scene(s) 2" in message

    def test_switching_a_stock_scene_to_ai_image_releases_the_stock_asset(self):
        with p13_env(with_manifest=True) as env:
            r = env.client.patch(f"/platform/studio/runs/{RUN_ID}/storyboard/scenes/2", json={"asset_strategy": "ai_image"})
            assert r.json()["needs_acquisition"] == ["2"]
            entry = next(e for e in env.manifest_entries() if e["scene_id"] == "2")
            assert entry["file_key"] is None and entry["status"] == "awaiting_upload"
            assert next(e for e in env.manifest_entries() if e["scene_id"] == "1")["file_key"]  # others untouched

    def test_switching_an_ai_scene_to_stock_releases_the_generated_image(self):
        with p13_env() as env:
            try:
                _configure(env)
                env.client.post(f"{_GEN}/2/generate", json={"prompt": "x"})
                env.client.patch(f"/platform/studio/runs/{RUN_ID}/storyboard/scenes/2", json={"asset_strategy": "stock_image"})
                entry = next(e for e in env.manifest_entries() if e["scene_id"] == "2")
                assert entry["file_key"] is None and entry["status"] == "pending"
            finally:
                _cleanup()

    def test_an_ai_image_does_not_fit_a_stock_scene_but_does_fit_an_ai_scene(self):
        from cf_platform.interfaces.routes.studio import _sync_entry_with_strategy
        from src.models import ManifestEntry, StoryboardScene

        def entry() -> ManifestEntry:
            return ManifestEntry(
                scene_id="1", clip_type="still_with_motion", segment_type="B-roll", primary_stk="q",
                context_stk="", concept_stk="", duration_s=2.0, status="acquired",
                file_key="runs/r/images/scene_01_ai_x.png", source="ai_generated",
            )

        manifest = type("M", (), {})()
        scene = StoryboardScene(scene="1", clip_type="still_with_motion", duration_s=2.0, voiceover_line="x", asset_strategy="stock_image", asset_tier="still")
        manifest.entries = [entry()]
        assert _sync_entry_with_strategy(manifest, scene) and manifest.entries[0].file_key is None

        scene = scene.model_copy(update={"asset_strategy": "ai_image"})
        manifest.entries = [entry()]
        _sync_entry_with_strategy(manifest, scene)
        assert manifest.entries[0].file_key == "runs/r/images/scene_01_ai_x.png"
