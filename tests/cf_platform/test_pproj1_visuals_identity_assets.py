"""P-PROJ1: look + image source (S1), channel identity (S2), project assets (S3, S4), prompt v0.18 (S5)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core import project_assets as pa
from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.run_manager import InMemoryRunRepository, create_run
from cf_platform.core.run_visuals import LOOK_STYLE, visuals_from
from cf_platform.interfaces.dependencies import PLATFORM_USER_ID, get_run_repository
from cf_platform.workers.animation_storyboard_worker import build_animation_user_message
from cf_platform.workers.storyboard_worker import (
    _GENERATE_SYSTEM_PROMPT_V013,
    _METHOD_V018,
    STORYBOARD_PROMPT_VERSION,
    apply_look_hint,
)
from cf_platform.workers.voice_production import VoiceWordTimestamp
from src.main import app
from src.models import Storyboard
from tests.cf_platform.p12_helpers import p12_env
from tests.cf_platform.p13_helpers import RUN_ID, make_storyboard, make_words, p13_env, seed_storyboard

MAYA = "a cheerful woman with a red scarf and short curly black hair"


# ── S3: project assets as pure functions ─────────────────────────────────


class TestProjectAssets:
    def test_add_slugs_the_name_and_keeps_ids_unique(self):
        config, first = pa.add_asset({}, kind="character", name="Maya the Guide", description=MAYA)
        config, second = pa.add_asset(config, kind="character", name="maya the guide!", description=MAYA)
        assert first["id"] == "maya_the_guide" and second["id"] == "maya_the_guide_2"
        assert [a["id"] for a in pa.list_assets(config)] == ["maya_the_guide", "maya_the_guide_2"]

    def test_validation_names_the_problem(self):
        for kwargs, needle in [
            ({"kind": "mascot", "name": "x", "description": "d"}, "Kind"),
            ({"kind": "prop", "name": " ", "description": "d"}, "name"),
            ({"kind": "prop", "name": "???", "description": "d"}, "letter"),
            ({"kind": "prop", "name": "x", "description": ""}, "description"),
            ({"kind": "prop", "name": "x", "description": "d" * (pa.MAX_DESCRIPTION_CHARS + 1)}, "limited"),
        ]:
            with pytest.raises(pa.ProjectAssetError, match=needle):
                pa.add_asset({}, **kwargs)

    def test_update_keeps_the_id_and_remove_reports_unknown(self):
        config, a = pa.add_asset({"niche_note": 1}, kind="prop", name="Teal Book", description="a teal book")
        config, b = pa.update_asset(config, a["id"], name="The Big Teal Book", description="a big teal book")
        assert b["id"] == "teal_book" and b["name"] == "The Big Teal Book" and config["niche_note"] == 1
        assert pa.list_assets(pa.remove_asset(config, "teal_book")) == []
        with pytest.raises(pa.ProjectAssetNotFoundError):
            pa.remove_asset(config, "nope")

    def test_the_prompt_block_lists_the_assets_and_is_empty_without_them(self):
        assert pa.prompt_block({}) == ""
        config, _ = pa.add_asset({}, kind="character", name="Maya", description=MAYA)
        block = pa.prompt_block(config)
        assert 'id "maya"' in block and MAYA in block and "EXACTLY" in block

    def test_a_reused_asset_is_forced_back_to_the_saved_text(self):
        config, _ = pa.add_asset({}, kind="character", name="Maya", description=MAYA)
        bible = [
            {"id": "maya", "kind": "prop", "name": "a woman", "description": "a drifting rewrite"},
            {"id": "teal_book", "kind": "prop", "name": "book", "description": "teal"},
        ]
        out = pa.apply_to_continuity(bible, config)
        assert out[0]["description"] == MAYA and out[0]["kind"] == "character" and out[0]["project_asset_id"] == "maya"
        assert out[1] == bible[1]


# ── S3 routes ────────────────────────────────────────────────────────────


class TestAssetRoutes:
    def test_crud_roundtrip_and_the_config_patch_cannot_wipe_assets(self):
        with p12_env() as env:
            pid = env.create_project()
            r = env.client.post(f"/platform/projects/{pid}/assets", json={"kind": "character", "name": "Maya", "description": MAYA})
            assert r.status_code == 201 and r.json()["id"] == "maya"
            assert env.client.get(f"/platform/projects/{pid}/assets").json()[0]["description"] == MAYA

            # A stale page saves its old config: the assets stay.
            r = env.client.patch(f"/platform/projects/{pid}", json={"config": {"ai_image_style": "ink"}})
            assert r.status_code == 200 and r.json()["config"]["ai_image_style"] == "ink"
            assert [a["id"] for a in r.json()["config"]["assets"]] == ["maya"]

            r = env.client.patch(f"/platform/projects/{pid}/assets/maya", json={"description": "new look"})
            assert r.status_code == 200 and r.json()["description"] == "new look"
            assert env.client.patch(f"/platform/projects/{pid}/assets/zzz", json={"name": "x"}).status_code == 404
            assert env.client.post(f"/platform/projects/{pid}/assets", json={"name": "x", "description": ""}).status_code == 422
            assert env.client.delete(f"/platform/projects/{pid}/assets/maya").status_code == 204
            assert env.client.get(f"/platform/projects/{pid}/assets").json() == []

    def test_channel_identity_is_text_and_limited(self):
        with p12_env() as env:
            pid = env.create_project()
            ok = env.client.patch(f"/platform/projects/{pid}", json={"config": {"channel_identity": "  Plain-spoken housing explainers.  "}})
            assert ok.status_code == 200 and ok.json()["config"]["channel_identity"] == "Plain-spoken housing explainers."
            too_long = env.client.patch(f"/platform/projects/{pid}", json={"config": {"channel_identity": "x" * 2001}})
            assert too_long.status_code == 422
            not_text = env.client.patch(f"/platform/projects/{pid}", json={"config": {"channel_identity": ["a"]}})
            assert not_text.status_code == 422

    def test_a_run_entry_is_copied_into_the_project(self):
        with p13_env() as env:
            sb = make_storyboard(make_words(), (0, 4, 8))
            sb = sb.model_copy(update={"visual_mode": "ai_animation", "continuity": Storyboard.model_validate({
                "global": {"subtitle_style": "", "bg_music": "", "visual_style": ""}, "scenes": [],
                "summary": {"total_scenes": 0, "total_duration_s": 0, "rhythm": ""},
                "continuity": [{"id": "learner", "kind": "character", "name": "the learner", "description": MAYA}],
            }).continuity})
            asyncio.run(seed_storyboard(env.storage, sb))
            runs = InMemoryRunRepository()
            app.dependency_overrides[get_run_repository] = lambda: runs
            try:
                from cf_platform.core.projects import InMemoryProjectRepository
                from cf_platform.interfaces.dependencies import get_project_repository

                projects = InMemoryProjectRepository(PLATFORM_USER_ID)
                app.dependency_overrides[get_project_repository] = lambda: projects
                project = asyncio.run(projects.get("default"))
                asyncio.run(create_run(PLATFORM_USER_ID, "studio", {}, runs, run_id=RUN_ID, project_id=project.project_id))
                r = env.client.post(f"/platform/projects/{project.project_id}/assets/from-run",
                                    json={"run_id": RUN_ID, "entry_id": "learner"})
                assert r.status_code == 201
                assert r.json()["name"] == "the learner" and r.json()["source_run_id"] == RUN_ID
                missing = env.client.post(f"/platform/projects/{project.project_id}/assets/from-run",
                                          json={"run_id": RUN_ID, "entry_id": "ghost"})
                assert missing.status_code == 404
            finally:
                from cf_platform.interfaces.dependencies import get_project_repository as gpr
                app.dependency_overrides.pop(get_run_repository, None)
                app.dependency_overrides.pop(gpr, None)


# ── S4: the animation worker's message and result ────────────────────────


class TestWorkerUsesAssets:
    def _words(self):
        return [VoiceWordTimestamp(word=w, start_ms=i * 300, end_ms=i * 300 + 250) for i, w in enumerate("one two three four".split())]

    def test_the_message_carries_the_assets_only_when_there_are_some(self):
        words = self._words()
        plain = build_animation_user_message("one two", words, [w.word for w in words], "portrait", "")
        assert "PROJECT ASSETS" not in plain
        config, _ = pa.add_asset({}, kind="character", name="Maya", description=MAYA)
        with_assets = build_animation_user_message(
            "one two", words, [w.word for w in words], "portrait", "", pa.list_assets(config)
        )
        assert "PROJECT ASSETS" in with_assets and MAYA in with_assets

    @pytest.mark.asyncio
    async def test_the_generated_bible_is_overwritten_by_the_asset(self):
        from cf_platform.workers import animation_storyboard_worker as aw

        words = self._words()
        answer = (
            '{"continuity":[{"id":"maya","kind":"prop","name":"a woman","description":"drift"}],'
            '"scenes":[{"start_word":0,"end_word":3,"voiceover_line":"one two three four",'
            '"ai_prompt":"maya at a desk","entities":["maya"],"shot":{"size":"wide","angle":"eye"},'
            '"motion_effect":"zoom_in","visual_concept":"c","visual_keywords":["k"]}]}'
        )
        config, _ = pa.add_asset({}, kind="character", name="Maya", description=MAYA)
        with patch.object(aw, "request_animation_storyboard", AsyncMock(return_value=answer)):
            sb = await aw.generate_animation_storyboard(
                "one two three four", words, "k", project_assets=pa.list_assets(config)
            )
        entry = sb.continuity[0]
        assert entry.description == MAYA and entry.kind == "character" and entry.project_asset_id == "maya"


# ── S1: look and image source ────────────────────────────────────────────


class TestLookAndSource:
    def test_a_chosen_look_is_the_master_style_fallback_and_never_overrides_a_style(self):
        assert visuals_from({"look": "animated", "visual_mode": "ai_animation"}, None).master_style == LOOK_STYLE["animated"]
        assert visuals_from({"look": "realistic", "visual_mode": "ai_animation"}, None).master_style == LOOK_STYLE["realistic"]
        assert visuals_from({"look": "animated", "master_style": "own"}, None).master_style == "own"
        assert visuals_from({"look": "animated"}, {"ai_image_style": "project"}).master_style == "project"
        # never chosen: no invented style
        assert visuals_from({"visual_mode": "ai_animation"}, None).master_style is None

    def test_get_put_and_the_lock(self):
        with p13_env() as env:                      # a run with a storyboard
            asyncio.run(env.storage.put_json(f"runs/{RUN_ID}/settings.json", {"visual_mode": "stock", "master_style": "keep"}))
            base = f"/platform/studio/runs/{RUN_ID}/visuals"
            got = env.client.get(base).json()
            assert got == {"look": "realistic", "image_source": "stock", "locked": True}

            same = env.client.put(base, json={"look": "realistic", "image_source": "stock"})
            assert same.status_code == 200 and same.json()["changed"] is False

            asked = env.client.put(base, json={"look": "animated"})
            assert asked.status_code == 409 and asked.json()["needs_confirmation"] is True
            assert env.client.get(base).json()["look"] == "realistic"            # nothing changed

            done = env.client.put(base, json={"look": "animated", "image_source": "ai", "confirm_reset": True})
            assert done.status_code == 200 and done.json()["changed"] is True and done.json()["discarded"]
            after = env.client.get(base).json()
            assert after == {"look": "animated", "image_source": "ai", "locked": False}
            assert env.client.get(f"/platform/studio/runs/{RUN_ID}/storyboard").status_code == 404
            settings = asyncio.run(env.storage.get_json(f"runs/{RUN_ID}/settings.json"))
            assert settings["visual_mode"] == "ai_animation" and settings["master_style"] == "keep"

    def test_without_a_storyboard_a_change_just_applies(self):
        storage = InMemoryArtifactStorage()
        from cf_platform.interfaces.dependencies import get_artifact_storage
        from src.config import Settings, get_settings
        from src.main import app as _app
        from tests.cf_platform.p12_helpers import VALID_ENV

        _app.dependency_overrides[get_artifact_storage] = lambda: storage
        _app.dependency_overrides[get_settings] = lambda: Settings.model_validate(VALID_ENV)
        try:
            from fastapi.testclient import TestClient

            client = TestClient(_app)
            r = client.put("/platform/studio/runs/r9/visuals", json={"look": "animated", "image_source": "ai"})
            assert r.status_code == 200 and r.json()["changed"] is True and r.json()["discarded"] == []
        finally:
            _app.dependency_overrides.pop(get_artifact_storage, None)
            _app.dependency_overrides.pop(get_settings, None)

    def test_an_animated_look_on_stock_aims_the_queries_at_illustration(self):
        sb = make_storyboard(make_words(), (0, 4, 8))
        first = sb.scenes[0].model_copy(update={"segment_type": "B-roll", "primary_stk": "city street",
                                                "context_stk": "traffic", "concept_stk": "animated map"})
        char = sb.scenes[1].model_copy(update={"segment_type": "Character", "primary_stk": "Jerome Powell"})
        out = apply_look_hint(sb.model_copy(update={"scenes": [first, char, *sb.scenes[2:]]}))
        assert out.scenes[0].primary_stk == "city street animation illustration"
        assert out.scenes[0].concept_stk == "animated map"            # already says it
        assert out.scenes[1].primary_stk == "Jerome Powell"           # a real person stays a photograph


# ── S5: prompt v0.18 ─────────────────────────────────────────────────────


class TestPromptV018:
    def test_the_default_is_still_v017_and_the_method_is_additive(self):
        assert STORYBOARD_PROMPT_VERSION == "v0.17"
        for must in ("CONCEPT BEFORE QUERY", "NO GENERIC IMAGERY", "VARIETY AS SEARCH INTENT", "FINAL SELF-CHECK"):
            assert must in _METHOD_V018
        # the method adds rules; it does not redefine the output contract
        assert "primary_stk" not in _METHOD_V018 and "segment_type" not in _METHOD_V018.replace("segment types", "")
        assert "PACING_TARGET_PLACEHOLDER" in _GENERATE_SYSTEM_PROMPT_V013

    @pytest.mark.asyncio
    async def test_v018_runs_on_sonnet_5_5_with_the_method_and_v017_does_not(self):
        from cf_platform.workers import storyboard_worker as sw

        seen: dict = {}

        class _Stream:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *a):
                return False

            async def get_final_message(self_inner):
                block = MagicMock(type="text", text='{"scenes": []}')
                return MagicMock(content=[block])

        def make_client(**kw):
            client = MagicMock()

            def stream(**params):
                seen["stream"] = params
                return _Stream()

            async def create(**params):
                seen["create"] = params
                return MagicMock(content=[MagicMock(text='{"scenes": []}')])

            client.messages.stream, client.messages.create = stream, create
            return client

        words = [VoiceWordTimestamp(word=w, start_ms=i * 300, end_ms=i * 300 + 250) for i, w in enumerate("a b c d".split())]
        with patch.object(sw.anthropic, "AsyncAnthropic", side_effect=make_client):
            for version in ("v0.18", "v0.17"):
                try:
                    await sw._generate("a b c d", words, "k", prompt_version=version)
                except ValueError:
                    pass                                    # an empty scene list is not a storyboard; the call is what we check
        assert seen["stream"]["model"] == "claude-sonnet-5-5" and seen["stream"]["thinking"] == {"type": "adaptive"}
        assert "VISUAL DIRECTOR METHOD" in seen["stream"]["system"][0]["text"]
        assert seen["create"]["model"] == "claude-sonnet-4-6"
        assert "VISUAL DIRECTOR METHOD" not in seen["create"]["system"][0]["text"]


# ── S2: metadata ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metadata_gets_the_channel_identity_next_to_the_script():
    from cf_platform.workers.youtube_metadata import build_youtube_metadata_worker
    from tests.cf_platform.test_p7_s2_youtube_metadata import _claude_response, _make_script_body, _make_state

    captured: list = []
    client = MagicMock()

    async def create(**kwargs):
        captured.extend(kwargs["messages"])
        return _claude_response("T", "D", ["tag"])

    client.messages.create = create
    state = _make_state()
    state.inputs["channel_identity"] = "Calm explainers for first-time buyers"
    with (
        patch("cf_platform.workers.youtube_metadata.read_artifact", AsyncMock(return_value=(MagicMock(), _make_script_body()))),
        patch("cf_platform.workers.youtube_metadata.anthropic.AsyncAnthropic", return_value=client),
    ):
        await build_youtube_metadata_worker(storage=MagicMock(), anthropic_api_key="k")(state)
    assert "CHANNEL IDENTITY" in captured[0]["content"] and "first-time buyers" in captured[0]["content"]
