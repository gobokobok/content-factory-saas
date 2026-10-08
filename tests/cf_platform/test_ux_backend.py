"""Tests for the UI/UX build's backend: integrations, tenant defaults, run progress,
libraries, runs without an idea, idea editing and the voice-source switch.

Covers:
- Integrations: a saved key wins over the Railway variable, is never returned, can be removed;
  unsaveable / unknown services and empty keys are refused; the settings overlay uses saved keys
- Defaults: validation, the tenant-over-built-in merge, run language/format resolution order
- Run progress derived from artifacts and the final video
- Library: stable asset IDs, per-kind classification, the listing route with project / run labels
- POST /projects/{id}/runs from a title alone; format and language resolution; 422 with neither
- PATCH an idea; 404 / 409 / 422 cases
- PUT /studio/runs/{id}/voice-source: confirmation, discard marker, no-op
"""

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.integrations import (
    SERVICE_IDS,
    UnknownServiceError,
    effective_platform_settings,
    project_run_defaults,
    public_integrations,
    resolve_defaults,
    resolve_run_values,
    resolve_service_key,
    save_defaults,
    save_integration_key,
    validate_defaults,
)
from cf_platform.core.library import RunRef, asset_id, classify_run_keys, list_run_assets
from cf_platform.core.run_progress import PIPELINE, progress_from_artifacts
from cf_platform.core.secret_box import SecretBoxError
from cf_platform.core.tenant_settings import InMemoryTenantSettingsRepository
from cf_platform.interfaces.dependencies import (
    get_artifact_repository,
    get_artifact_storage,
    get_tenant_settings_repository,
)
from src.main import app
from tests.cf_platform.p12_helpers import p12_env

KEY = Fernet.generate_key().decode()


class _Settings(SimpleNamespace):
    """PlatformSettings stand-in supporting model_copy(update=...)."""

    def model_copy(self, update=None):
        return _Settings(**{**self.__dict__, **(update or {})})


def _settings(**over) -> _Settings:
    base = dict(
        SETTINGS_ENCRYPTION_KEY=KEY, ANTHROPIC_API_KEY="env-claude", GEMINI_API_KEY="", DEEPGRAM_API_KEY="",
        OPENAI_API_KEY="", KIE_API_KEY="", PEXELS_API_KEY="env-pexels", PIXABAY_API_KEY="", YOUTUBE_API_KEY="",
        IMAGE_RUN_SPEND_CAP_USD=2.0,
    )
    base.update(over)
    return _Settings(**base)


# ── Integrations ──────────────────────────────────────────────────────────


class TestIntegrations:
    @pytest.mark.asyncio
    async def test_saved_key_wins_over_env_and_is_never_returned(self):
        repo, s = InMemoryTenantSettingsRepository(), _settings()
        assert await resolve_service_key(repo, "t", s, "pexels") == "env-pexels"
        await save_integration_key(repo, "t", s, "pexels", api_key="tenant-pexels-9999")
        assert await resolve_service_key(repo, "t", s, "pexels") == "tenant-pexels-9999"
        public = await public_integrations(repo, "t", s)
        pexels = next(x for x in public["services"] if x["service_id"] == "pexels")
        assert (pexels["key_source"], pexels["key_hint"]) == ("tenant", "9999")
        assert "tenant-pexels" not in str(public)

    @pytest.mark.asyncio
    async def test_env_and_missing_sources_are_reported(self):
        public = await public_integrations(InMemoryTenantSettingsRepository(), "t", _settings())
        by_id = {x["service_id"]: x for x in public["services"]}
        assert by_id["anthropic"]["key_source"] == "env" and by_id["pixabay"]["key_source"] is None
        assert set(by_id) == set(SERVICE_IDS) and public["can_save_keys"] is True

    @pytest.mark.asyncio
    async def test_remove_returns_to_env(self):
        repo, s = InMemoryTenantSettingsRepository(), _settings()
        await save_integration_key(repo, "t", s, "anthropic", api_key="tenant-claude")
        await save_integration_key(repo, "t", s, "anthropic", clear_key=True)
        assert await resolve_service_key(repo, "t", s, "anthropic") == "env-claude"

    @pytest.mark.asyncio
    async def test_refusals(self):
        repo, s = InMemoryTenantSettingsRepository(), _settings()
        with pytest.raises(UnknownServiceError):
            await save_integration_key(repo, "t", s, "nope", api_key="x")
        with pytest.raises(UnknownServiceError):  # a service that cannot hold a saved key yet
            await save_integration_key(repo, "t", s, "youtube", api_key="x")
        with pytest.raises(ValueError):
            await save_integration_key(repo, "t", s, "pexels", api_key="   ")
        with pytest.raises(SecretBoxError):
            await save_integration_key(repo, "t", _settings(SETTINGS_ENCRYPTION_KEY=""), "pexels", api_key="abcd")

    @pytest.mark.asyncio
    async def test_overlay_replaces_only_saved_keys(self):
        repo, s = InMemoryTenantSettingsRepository(), _settings()
        await save_integration_key(repo, "t", s, "pixabay", api_key="tenant-pixabay")
        effective = await effective_platform_settings(repo, "t", s)
        assert effective.PIXABAY_API_KEY == "tenant-pixabay" and effective.PEXELS_API_KEY == "env-pexels"
        assert s.PIXABAY_API_KEY == ""  # the original is untouched
        assert await effective_platform_settings(InMemoryTenantSettingsRepository(), "t", s) is s

    @pytest.mark.asyncio
    async def test_unreadable_saved_key_falls_back_to_env(self):
        repo, s = InMemoryTenantSettingsRepository(), _settings()
        await save_integration_key(repo, "t", s, "pexels", api_key="tenant-pexels")
        changed = _settings(SETTINGS_ENCRYPTION_KEY=Fernet.generate_key().decode())
        assert (await effective_platform_settings(repo, "t", changed)).PEXELS_API_KEY == "env-pexels"


class TestIntegrationRoutes:
    def test_get_and_put_never_echo_a_key(self):
        repo = InMemoryTenantSettingsRepository()
        from cf_platform.core.config import get_platform_settings
        from src.config import Settings, get_settings
        from tests.cf_platform.p12_helpers import VALID_ENV

        app.dependency_overrides[get_settings] = lambda: Settings.model_validate(VALID_ENV)
        app.dependency_overrides[get_tenant_settings_repository] = lambda: repo
        app.dependency_overrides[get_platform_settings] = lambda: _settings()
        try:
            from fastapi.testclient import TestClient

            c = TestClient(app, raise_server_exceptions=True)
            r = c.put("/platform/tenant/integrations/deepgram", json={"api_key": "dg-secret-1234"})
            assert r.status_code == 200 and "dg-secret" not in r.text
            dg = next(x for x in r.json()["services"] if x["service_id"] == "deepgram")
            assert (dg["key_source"], dg["key_hint"]) == ("tenant", "1234")
            assert c.put("/platform/tenant/integrations/nope", json={"api_key": "x"}).status_code == 422
            assert c.put("/platform/tenant/integrations/pexels", json={}).status_code == 422
            assert c.put("/platform/tenant/integrations/deepgram", json={"clear_key": True}).status_code == 200
        finally:
            app.dependency_overrides.pop(get_tenant_settings_repository, None)
            app.dependency_overrides.pop(get_platform_settings, None)
            app.dependency_overrides.pop(get_settings, None)


# ── Defaults ──────────────────────────────────────────────────────────────


class TestDefaults:
    def test_validation(self):
        assert validate_defaults({"language": "ru", "format": "16:9", "captions": "punch", "spend_cap": "3.5"}) == {
            "language": "ru", "format": "16:9", "captions": "punch", "spend_cap": 3.5,
        }
        for bad in ({"language": "English"}, {"format": "1:1"}, {"captions": "loud"}, {"spend_cap": -1},
                    {"spend_cap": "x"}, {"colour": "red"}):
            with pytest.raises(ValueError):
                validate_defaults(bad)

    @pytest.mark.asyncio
    async def test_tenant_over_builtin(self):
        repo, s = InMemoryTenantSettingsRepository(), _settings()
        assert await resolve_defaults(repo, "t", s) == {"language": "en", "format": "9:16", "captions": "standard", "spend_cap": 2.0}
        await save_defaults(repo, "t", {"language": "ru", "spend_cap": 5})
        merged = await resolve_defaults(repo, "t", s)
        assert (merged["language"], merged["format"], merged["spend_cap"]) == ("ru", "9:16", 5.0)

    def test_project_run_defaults_use_tenant_vocabulary(self):
        config = {"language": "ru", "run_defaults": {"aspect_ratio": "16:9", "subtitles": "TikTok", "caption_style": "punch"}}
        assert project_run_defaults(config) == {"language": "ru", "format": "16:9", "captions": "punch"}
        assert project_run_defaults({"run_defaults": {"subtitles": "none"}}) == {"captions": "none"}
        assert project_run_defaults(None) == {}

    def test_run_values_resolve_run_then_project_then_tenant(self):
        tenant = {"language": "en", "format": "9:16"}
        project = {"language": "ru", "run_defaults": {"aspect_ratio": "16:9"}}
        assert resolve_run_values(tenant, project) == {"language": "ru", "format": "16:9"}
        assert resolve_run_values(tenant, project, language="en", aspect_ratio="9:16") == {"language": "en", "format": "9:16"}
        assert resolve_run_values(tenant, {}) == {"language": "en", "format": "9:16"}


# ── Run progress ──────────────────────────────────────────────────────────


class TestRunProgress:
    def test_pipeline_has_five_steps_in_order(self):
        assert PIPELINE == ("script", "voice", "storyboard", "render", "metadata")

    def test_nothing_produced(self):
        assert progress_from_artifacts([], False) == (0, "script")

    def test_steps_count_only_in_order(self):
        arts = [("script", "script"), ("voice", "voice_alignment")]
        assert progress_from_artifacts(arts, False) == (2, "storyboard")
        # a storyboard without a voice does not count past the missing step
        assert progress_from_artifacts([("script", "script"), ("storyboard", "verified_storyboard")], False) == (1, "voice")

    def test_uploaded_run_has_script_and_voice_together_and_all_done(self):
        arts = [("script", "script"), ("voice", "voice_alignment"), ("storyboard", "verified_storyboard"),
                ("metadata", "youtube_metadata")]
        assert progress_from_artifacts(arts, False) == (3, "render")
        assert progress_from_artifacts(arts, True) == (5, None)


# ── Library ───────────────────────────────────────────────────────────────


RUN = RunRef("r1", "Starter homes", "p1", "Housing", "2026-10-02T10:00:00+00:00")


class TestLibrary:
    def test_asset_id_is_stable_and_prefixed(self):
        a = asset_id("videos", "runs/r1/output/final.mp4")
        assert a == asset_id("videos", "runs/r1/output/final.mp4") and a.startswith("VID-") and len(a) == 10
        assert asset_id("ai", "x").startswith("AIG-") and asset_id("audio", "x").startswith("AUD-")
        assert asset_id("videos", "a") != asset_id("videos", "b")
        with pytest.raises(ValueError):
            asset_id("nope", "x")

    def test_footage_excludes_ai_images_and_non_media(self):
        keys = {"video": ["runs/r1/video/scene_01.mp4"], "images": ["runs/r1/images/scene_02.jpg",
                "runs/r1/images/scene_03_ai_ab12cd34.png", "runs/r1/images/notes.txt"]}
        names = [i["name"] for i in classify_run_keys("footage", keys)]
        assert names == ["scene_02.jpg", "scene_01.mp4"] or sorted(names) == ["scene_01.mp4", "scene_02.jpg"]
        assert [i["name"] for i in classify_run_keys("ai", keys, {"runs/r1/images/scene_03_ai_ab12cd34.png"})] == ["scene_03_ai_ab12cd34.png"]

    def test_ai_images_split_into_in_use_and_replaced(self):
        keys = {"images": ["runs/r1/images/scene_03_ai_aaaa1111.png", "runs/r1/images/scene_03_ai_bbbb2222.png"]}
        facets = {i["name"]: i["facet"] for i in classify_run_keys("ai", keys, {"runs/r1/images/scene_03_ai_bbbb2222.png"})}
        assert facets == {"scene_03_ai_aaaa1111.png": "replaced", "scene_03_ai_bbbb2222.png": "in use"}

    def test_audio_distinguishes_generated_from_uploaded(self):
        keys = {"voiceover": ["runs/r1/voiceover/generated.mp3", "runs/r1/voiceover/uploaded.m4a", "runs/r1/voiceover/x.txt"]}
        assert {i["name"]: i["facet"] for i in classify_run_keys("audio", keys)} == {
            "generated.mp3": "generated", "uploaded.m4a": "uploaded"}

    @pytest.mark.asyncio
    async def test_run_assets_carry_ids_labels_and_download_links(self):
        storage = InMemoryArtifactStorage()
        await storage.put_bytes("runs/r1/output/final.mp4", b"v")
        items = await list_run_assets("videos", RUN, storage)
        assert len(items) == 1
        item = items[0]
        assert item["asset_id"].startswith("VID-") and item["run_id"] == "r1" and item["project_name"] == "Housing"
        assert item["download_url"].startswith("https://fake-r2.example.com/runs/r1/output/final.mp4")

    @pytest.mark.asyncio
    async def test_a_failing_listing_reads_as_empty(self):
        class Broken(InMemoryArtifactStorage):
            async def list_keys(self, prefix):
                raise RuntimeError("down")

        assert await list_run_assets("videos", RUN, Broken()) == []


class TestLibraryRoute:
    def test_lists_assets_across_runs_with_project_and_run(self):
        storage = InMemoryArtifactStorage()
        with p12_env() as env:
            pid = env.create_project("Housing")
            item = env.add_item(pid, "Why rents rise")
            run = env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": [item]}).json()
            import asyncio

            asyncio.run(storage.put_bytes(f"runs/{run['run_id']}/output/final.mp4", b"v"))
            asyncio.run(storage.put_bytes(f"runs/{run['run_id']}/images/scene_01_ai_aa11bb22.png", b"p"))
            app.dependency_overrides[get_artifact_storage] = lambda: storage
            try:
                videos = env.client.get("/platform/library/videos").json()
                assert [i["run_id"] for i in videos["items"]] == [run["run_id"]]
                assert videos["items"][0]["project_name"] == "Housing" and videos["items"][0]["asset_id"].startswith("VID-")
                assert "Housing" in [p["name"] for p in videos["projects"]]
                ai = env.client.get("/platform/library/ai").json()
                assert ai["items"][0]["facet"] == "replaced"  # no manifest, so not in use
                assert env.client.get("/platform/library/footage").json()["items"] == []
                assert env.client.get("/platform/library/nope").status_code == 404
            finally:
                app.dependency_overrides.pop(get_artifact_storage, None)


# ── Runs without an idea, idea editing ────────────────────────────────────


class TestRunCreation:
    def test_run_from_a_title_alone(self):
        with p12_env() as env:
            pid = env.create_project()
            r = env.client.post(f"/platform/projects/{pid}/runs", json={"title": "Rent vs buy", "brief": "use 2026 numbers"})
            assert r.status_code == 201, r.text
            run = r.json()
            assert run["name"] == "Rent vs buy" and run["format"] == "9:16" and run["language"] == "en"
            ctx = env.client.get(f"/platform/studio/runs/{run['run_id']}/context").json()
            assert ctx["items"] == [] and ctx["idea_title"] == "Rent vs buy"
            assert ctx["supporting_points"] == ["use 2026 numbers"] and ctx["format"] == "9:16"

    def test_neither_idea_nor_title_is_422(self):
        with p12_env() as env:
            pid = env.create_project()
            assert env.client.post(f"/platform/projects/{pid}/runs", json={}).status_code == 422
            assert env.client.post(f"/platform/projects/{pid}/runs", json={"title": "  "}).status_code == 422

    def test_format_and_language_resolve_run_then_project_then_tenant(self):
        with p12_env() as env:
            pid = env.create_project()
            env.client.patch(f"/platform/projects/{pid}", json={"config": {"language": "ru", "run_defaults": {"aspect_ratio": "16:9"}}})
            a = env.client.post(f"/platform/projects/{pid}/runs", json={"title": "A"}).json()
            assert (a["language"], a["format"]) == ("ru", "16:9")
            b = env.client.post(f"/platform/projects/{pid}/runs", json={"title": "B", "language": "en", "aspect_ratio": "9:16"}).json()
            assert (b["language"], b["format"]) == ("en", "9:16")

    def test_idea_runs_still_work_and_a_title_overrides_the_idea_title(self):
        with p12_env() as env:
            pid = env.create_project()
            item = env.add_item(pid, "Why rents rise", summary="Supply")
            run = env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": [item], "title": "Rents, simplified"}).json()
            ctx = env.client.get(f"/platform/studio/runs/{run['run_id']}/context").json()
            assert ctx["idea_title"] == "Rents, simplified" and [i["item_id"] for i in ctx["items"]] == [item]
            assert env.client.get(f"/platform/projects/{pid}/shortlist").json()[0]["run_count"] == 1

    def test_project_run_list_reports_mode_language_and_progress(self):
        storage = InMemoryArtifactStorage()
        from cf_platform.core.artifact_manager import InMemoryArtifactRepository

        with p12_env() as env:
            pid = env.create_project()
            run = env.client.post(f"/platform/projects/{pid}/runs", json={"title": "A", "voice_source": "uploaded"}).json()
            app.dependency_overrides[get_artifact_storage] = lambda: storage
            app.dependency_overrides[get_artifact_repository] = lambda: InMemoryArtifactRepository()
            try:
                row = env.client.get(f"/platform/projects/{pid}/runs").json()[0]
            finally:
                app.dependency_overrides.pop(get_artifact_storage, None)
                app.dependency_overrides.pop(get_artifact_repository, None)
            assert row["run_id"] == run["run_id"] and row["voice_source"] == "uploaded"
            assert (row["steps_done"], row["current_step"], row["has_video"]) == (0, "script", False)

    def test_projects_report_last_activity(self):
        with p12_env() as env:
            pid = env.create_project()
            assert env.client.get(f"/platform/projects/{pid}").json()["last_activity"] is None
            env.client.post(f"/platform/projects/{pid}/runs", json={"title": "A"})
            assert env.client.get(f"/platform/projects/{pid}").json()["last_activity"] is not None
            assert env.client.get("/platform/projects").json()[0]["last_activity"] is not None


class TestIdeaEditing:
    def test_patch_changes_only_supplied_fields(self):
        with p12_env() as env:
            pid = env.create_project()
            item = env.add_item(pid, "Old title", summary="old", source="a report", notes="n")
            r = env.client.patch(f"/platform/projects/{pid}/shortlist/{item}", json={"title": " New title ", "source": ""})
            assert r.status_code == 200, r.text
            body = r.json()
            assert (body["title"], body["summary"], body["source"]) == ("New title", "old", None)
            assert body["evidence"] == {"notes": "n"}
            r = env.client.patch(f"/platform/projects/{pid}/shortlist/{item}", json={"notes": ""})
            assert r.json()["evidence"] == {}

    def test_errors(self):
        with p12_env() as env:
            pid, other = env.create_project("A"), env.create_project("B")
            item = env.add_item(pid)
            assert env.client.patch(f"/platform/projects/{pid}/shortlist/{item}", json={"title": ""}).status_code == 422
            assert env.client.patch(f"/platform/projects/{other}/shortlist/{item}", json={"title": "x"}).status_code == 404
            assert env.client.patch(f"/platform/projects/{pid}/shortlist/nope", json={"title": "x"}).status_code == 404
            env.client.delete(f"/platform/projects/{pid}/shortlist/{item}")
            assert env.client.patch(f"/platform/projects/{pid}/shortlist/{item}", json={"title": "x"}).status_code == 409


# ── Voice source switch ───────────────────────────────────────────────────


class TestVoiceSource:
    def _setup(self, env, *, uploaded_voice=False, storyboard=False):
        """A run created with an uploaded voice source, optionally with an uploaded alignment and a storyboard."""
        import asyncio
        from datetime import datetime

        from cf_platform.core.artifact_manager import write_artifact
        from cf_platform.core.schemas import LineageEnvelope
        from cf_platform.workers.voice_production import VoiceAlignmentArtifact

        pid = env.create_project()
        run = env.client.post(f"/platform/projects/{pid}/runs", json={"title": "A", "voice_source": "uploaded"}).json()
        storage = InMemoryArtifactStorage()
        lineage = LineageEnvelope(run_id=run["run_id"], worker="t", worker_version="1", prompt_version="n",
                                  model="n", created_at=datetime.now())

        async def seed():
            if uploaded_voice:
                await write_artifact(
                    storage, VoiceAlignmentArtifact(mp3_r2_key="runs/x/voiceover/uploaded.mp3", total_duration_s=5.0,
                                                    word_timestamps=[], alignment_method="uploaded_deepgram_nova2"),
                    name="voice_alignment", stage="voice", run_id=run["run_id"], user_id="operator", lineage=lineage)
            if storyboard:
                await storage.put_json(f"users/operator/runs/{run['run_id']}/storyboard/verified_storyboard@v1.json",
                                       {"body": {}})

        asyncio.run(seed())
        return run["run_id"], storage

    def _put(self, env, storage, run_id, **body):
        app.dependency_overrides[get_artifact_storage] = lambda: storage
        try:
            return env.client.put(f"/platform/studio/runs/{run_id}/voice-source", json=body)
        finally:
            app.dependency_overrides.pop(get_artifact_storage, None)

    def test_same_source_is_a_no_op(self):
        with p12_env() as env:
            run_id, storage = self._setup(env)
            r = self._put(env, storage, run_id, voice_source="uploaded")
            assert r.json() == {"voice_source": "uploaded", "changed": False, "discarded": []}

    def test_switch_to_generated_asks_before_replacing_an_uploaded_voice(self):
        with p12_env() as env:
            run_id, storage = self._setup(env, uploaded_voice=True, storyboard=True)
            r = self._put(env, storage, run_id, voice_source="generated")
            assert r.status_code == 409 and r.json()["needs_confirmation"] is True
            assert any("uploaded voiceover" in d for d in r.json()["discards"]) and any("storyboard" in d for d in r.json()["discards"])
            assert env.client.get(f"/platform/studio/runs/{run_id}/context").json()["voice_source"] == "uploaded"

    def test_confirmed_switch_discards_the_storyboard_and_changes_the_source(self):
        import asyncio

        with p12_env() as env:
            run_id, storage = self._setup(env, uploaded_voice=True, storyboard=True)
            r = self._put(env, storage, run_id, voice_source="generated", confirm_discard=True)
            assert r.status_code == 200 and r.json()["changed"] is True
            assert env.client.get(f"/platform/studio/runs/{run_id}/context").json()["voice_source"] == "generated"
            marker = asyncio.run(storage.get_json(f"runs/{run_id}/storyboard/discarded.json"))
            assert "verified_storyboard@v1.json" in marker["key"]

    def test_switch_without_anything_to_lose_needs_no_confirmation(self):
        with p12_env() as env:
            run_id, storage = self._setup(env)
            r = self._put(env, storage, run_id, voice_source="generated")
            assert r.status_code == 200 and r.json()["discarded"] == []

    def test_choosing_uploaded_only_unlocks_the_upload(self):
        with p12_env() as env:
            pid = env.create_project()
            run = env.client.post(f"/platform/projects/{pid}/runs", json={"title": "A"}).json()
            r = self._put(env, InMemoryArtifactStorage(), run["run_id"], voice_source="uploaded")
            assert r.status_code == 200 and r.json()["changed"] is True

    def test_unknown_run_is_404(self):
        with p12_env() as env:
            assert self._put(env, InMemoryArtifactStorage(), "missing", voice_source="generated").status_code == 404
