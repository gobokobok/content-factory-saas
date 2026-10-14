"""Sprint P-LITE — the Creator flow's backend (D114, D117).

S1  New run: format, language, master style and characters are stored on the run;
    saving any setting no longer drops look / cast / characters / voice.
S2  The director uses only the listed characters.
S3  The narrator's voice is a per-run choice.
S5  Sound effects are off unless the deployment turns them on.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.cast import (
    CastRule,
    enforce_listed_cast,
    listed_prompt_block,
    resolve_listed_cast,
)
from cf_platform.core.config import get_platform_settings
from cf_platform.core.schemas import StageState
from cf_platform.interfaces.dependencies import get_artifact_storage
from cf_platform.interfaces.routes._helpers import sfx_enabled
from cf_platform.interfaces.routes.workers import resolve_tts_voice
from cf_platform.workers.timeline import without_sfx
from cf_platform.workers.voice_production import VoiceWordTimestamp
from src.main import app
from src.models import Storyboard, VideoSettings
from src.routes.runs import merge_video_settings
from tests.cf_platform.p12_helpers import p12_env
from tests.cf_platform.p13_helpers import (
    RUN_ID,
    make_manifest,
    make_storyboard,
    make_words,
    p13_env,
    seed_manifest,
    seed_storyboard,
)

MAYA = "a cheerful woman in her thirties with short curly black hair and a red scarf"
TOM = "a tall man in his fifties with a grey beard and a green raincoat"
CREATOR_SETTINGS = SimpleNamespace(CREATOR_PROJECT_NAME="My videos", CREATOR_SCRIPT_MAX_WORDS=450)


def _storyboard() -> Storyboard:
    """Three scenes; the model invented two characters and one prop."""
    scene = lambda n, ents: {  # noqa: E731 - a small local builder
        "scene": str(n), "clip_type": "still_with_motion", "duration_s": 2.0, "voiceover_line": f"line {n}",
        "segment_type": "B-roll", "asset_strategy": "ai_image", "asset_tier": "still", "motion_effect": "zoom_in",
        "start_word": n - 1, "end_word": n - 1, "entities": ents, "ai_prompt": f"prompt {n}", "sfx": "whoosh",
    }
    return Storyboard.model_validate({
        "global": {"subtitle_style": "", "bg_music": "", "visual_style": ""},
        "scenes": [scene(1, ["rival", "desk"]), scene(2, ["maya", "stranger"]), scene(3, [])],
        "summary": {"total_scenes": 3, "total_duration_s": 6, "rhythm": ""},
        "visual_mode": "ai_animation",
        "continuity": [
            {"id": "maya", "kind": "character", "name": "a woman", "description": "a drifting rewrite"},
            {"id": "rival", "kind": "character", "name": "the rival", "description": "a competitor"},
            {"id": "stranger", "kind": "character", "name": "a stranger", "description": "someone else"},
            {"id": "desk", "kind": "prop", "name": "the desk", "description": "an oak desk"},
        ],
    })


# ── S1: settings keep every key; the Creator's New run ───────────────────


class TestSettingsKeepEveryKey:
    def test_saving_one_setting_keeps_look_cast_characters_and_voice(self):
        """Regression: these keys were not on VideoSettings, so any save dropped them from settings.json."""
        stored = VideoSettings.model_validate({
            "look": "animated", "visual_mode": "ai_animation", "cast_mode": "listed", "voice": "female",
            "characters": [{"name": "Maya", "description": MAYA}], "protagonist_text": "x",
        })
        merged = merge_video_settings(stored, VideoSettings.model_validate({"subtitles": "none"})).model_dump()
        assert merged["look"] == "animated" and merged["cast_mode"] == "listed" and merged["voice"] == "female"
        assert merged["characters"] == [{"name": "Maya", "description": MAYA}] and merged["protagonist_text"] == "x"
        assert merged["subtitles"] == "none"

    def test_the_single_cast_fields_are_saved_at_all(self):
        """D113's "One character throughout" was never stored before this sprint."""
        saved = VideoSettings.model_validate({"cast_mode": "single", "protagonist_asset_id": "maya", "protagonist_text": MAYA})
        assert saved.model_dump()["cast_mode"] == "single" and saved.protagonist_asset_id == "maya"

    def test_characters_are_trimmed_validated_and_limited(self):
        ok = VideoSettings.model_validate({"characters": [{"name": "  Maya ", "description": f" {MAYA} "}]})
        assert ok.characters[0].name == "Maya" and ok.characters[0].description == MAYA
        with pytest.raises(ValueError):
            VideoSettings.model_validate({"characters": [{"name": "Maya", "description": "  "}]})
        with pytest.raises(ValueError):
            VideoSettings.model_validate({"characters": [{"name": f"P{i}", "description": "d"} for i in range(7)]})
        with pytest.raises(ValueError):
            VideoSettings.model_validate({"voice": "robot"})


class TestCreatorRoutes:
    @staticmethod
    def _env():
        """A P12 env plus in-memory storage and the Creator's platform settings."""
        storage = InMemoryArtifactStorage()
        app.dependency_overrides[get_artifact_storage] = lambda: storage
        app.dependency_overrides[get_platform_settings] = lambda: CREATOR_SETTINGS
        return storage

    @staticmethod
    def _clear():
        app.dependency_overrides.pop(get_artifact_storage, None)
        app.dependency_overrides.pop(get_platform_settings, None)

    def test_config_creates_the_project_once_and_lists_the_voices(self):
        with p12_env() as env:
            self._env()
            try:
                first = env.client.get("/platform/creator/config").json()
                second = env.client.get("/platform/creator/config").json()
            finally:
                self._clear()
            assert first["project_id"] == second["project_id"] and first["project_name"] == "My videos"
            assert first["script_max_words"] == 20000 and first["max_characters"] == 6  # the owner is Super: no cap (P-CORE)
            # Named voices; the channel's own voice is listed first when it is not one of them.
            ids = [v["id"] for v in first["voices"]]
            assert "Charon" in ids and "Kore" in ids and first["default_voice"] in ids
            assert set(first["voice_aliases"]) == {"male", "female"}
            flagged = [p for p in env.client.get("/platform/projects").json() if p["config"].get("creator")]
            assert len(flagged) == 1

    def test_a_renamed_creator_project_is_still_the_one(self):
        with p12_env() as env:
            self._env()
            try:
                pid = env.client.get("/platform/creator/config").json()["project_id"]
                env.client.patch(f"/platform/projects/{pid}", json={"name": "Bedtime stories"})
                again = env.client.get("/platform/creator/config").json()
            finally:
                self._clear()
            assert again["project_id"] == pid and again["project_name"] == "Bedtime stories"

    def test_new_run_stores_format_language_style_and_characters(self):
        with p12_env() as env:
            storage = self._env()
            try:
                r = env.client.post("/platform/creator/runs", json={
                    "title": "  The fox who was afraid of the dark ", "aspect_ratio": "16:9", "language": "ru",
                    "master_style": " flat 2D illustration ",
                    "characters": [{"name": "Maya", "description": MAYA}, {"name": "Tom", "description": TOM}],
                })
                pid = env.client.get("/platform/creator/config").json()["project_id"]
                listed = env.client.get(f"/platform/projects/{pid}/runs")
            finally:
                self._clear()
            assert r.status_code == 201, r.text
            run = r.json()
            assert run["name"] == "The fox who was afraid of the dark" and run["format"] == "16:9" and run["language"] == "ru"
            saved = asyncio.run(storage.get_json(f"runs/{run['run_id']}/settings.json"))
            assert saved["aspect_ratio"] == "16:9" and saved["visual_mode"] == "ai_animation" and saved["look"] == "animated"
            assert saved["master_style"] == "flat 2D illustration" and saved["subtitles"] == "none"
            assert saved["cast_mode"] == "listed" and [c["name"] for c in saved["characters"]] == ["Maya", "Tom"]
            assert [x["run_id"] for x in listed.json()] == [run["run_id"]]

    def test_a_run_without_characters_leaves_the_cast_to_the_director(self):
        with p12_env() as env:
            storage = self._env()
            try:
                r = env.client.post("/platform/creator/runs", json={"title": "Rain"})
            finally:
                self._clear()
            saved = asyncio.run(storage.get_json(f"runs/{r.json()['run_id']}/settings.json"))
            assert r.status_code == 201 and saved["cast_mode"] == "free" and saved["characters"] == []
            assert saved["aspect_ratio"] == "9:16"

    @pytest.mark.parametrize("body", [
        {"title": "   "},
        {"title": ""},
        {"title": "x", "aspect_ratio": "1:1"},
        {"title": "x", "language": "english"},
        {"title": "x", "characters": [{"name": "Maya", "description": ""}]},
        {"title": "x", "characters": [{"name": f"P{i}", "description": "d"} for i in range(7)]},
    ])
    def test_a_bad_request_is_refused_and_creates_nothing(self, body):
        with p12_env() as env:
            storage = self._env()
            try:
                r = env.client.post("/platform/creator/runs", json=body)
            finally:
                self._clear()
            assert r.status_code == 422
            assert asyncio.run(storage.list_keys("runs/")) == []


# ── S2: only the listed characters ───────────────────────────────────────


class TestListedCast:
    def test_resolve_gives_each_character_a_stable_id_and_skips_what_is_unusable(self):
        rules = resolve_listed_cast({"cast_mode": "listed", "characters": [
            {"name": "Maya the Guide", "description": MAYA},
            {"name": "maya the guide!", "description": "a duplicate"},
            {"name": "", "description": "nameless"},
            {"name": "Tom", "description": "  "},
            {"name": "Маша", "description": "девочка в красном пальто"},
            "not a dict",
        ]})
        assert [(r.entry_id, r.name) for r in rules] == [("maya_the_guide", "Maya the Guide"), ("character_5", "Маша")]
        assert rules[0].description == MAYA

    def test_no_rule_unless_the_mode_is_listed(self):
        chars = [{"name": "Maya", "description": MAYA}]
        assert resolve_listed_cast({"cast_mode": "free", "characters": chars}) == []
        assert resolve_listed_cast({"characters": chars}) == []
        assert resolve_listed_cast({"cast_mode": "listed"}) == []

    def test_the_prompt_names_every_character_and_forbids_others(self):
        block = listed_prompt_block([CastRule("maya", "Maya", MAYA), CastRule("tom", "Tom", TOM)])
        assert 'id "maya"' in block and 'id "tom"' in block and MAYA in block and TOM in block
        assert "ONLY characters" in block and "Do NOT create any other" in block
        assert listed_prompt_block([]) == ""
        assert "ONE person" in listed_prompt_block([CastRule("maya", "Maya", MAYA)])

    def test_invented_characters_are_removed_and_every_listed_one_is_in_the_bible(self):
        out = enforce_listed_cast(_storyboard(), [CastRule("maya", "Maya", MAYA), CastRule("tom", "Tom", TOM)])
        assert [(e.id, e.kind) for e in out.continuity] == [("maya", "character"), ("tom", "character"), ("desk", "prop")]
        assert out.continuity[0].description == MAYA and out.continuity[0].name == "Maya"
        assert out.continuity[1].description == TOM
        # An invented person is removed from a scene, not swapped for a listed one.
        assert [s.entities for s in out.scenes] == [["desk"], ["maya"], []]

    def test_one_listed_character_behaves_as_the_single_cast_rule(self):
        out = enforce_listed_cast(_storyboard(), [CastRule("maya", "Maya", MAYA)])
        assert [e.id for e in out.continuity if e.kind == "character"] == ["maya"]
        assert [s.entities for s in out.scenes] == [["maya", "desk"], ["maya"], []]

    def test_no_rules_changes_nothing(self):
        sb = _storyboard()
        assert enforce_listed_cast(sb, []) is sb

    @pytest.mark.asyncio
    async def test_through_the_worker_an_invented_character_never_survives(self):
        from cf_platform.workers import animation_storyboard_worker as aw

        words = [VoiceWordTimestamp(word=w, start_ms=i * 300, end_ms=i * 300 + 250) for i, w in enumerate("one two three four".split())]
        answer = json.dumps({
            "continuity": [
                {"id": "maya", "kind": "character", "name": "Maya", "description": "rewritten"},
                {"id": "bob", "kind": "character", "name": "Bob", "description": "an older man"},
            ],
            "scenes": [
                {"start_word": 0, "end_word": 1, "ai_prompt": "maya at a desk", "entities": ["maya"],
                 "shot": {"size": "wide", "angle": "eye"}, "motion_effect": "zoom_in", "visual_concept": "c", "visual_keywords": ["k"]},
                {"start_word": 2, "end_word": 3, "ai_prompt": "bob walks", "entities": ["bob"],
                 "shot": {"size": "wide", "angle": "eye"}, "motion_effect": "zoom_in", "visual_concept": "c", "visual_keywords": ["k"]},
            ],
        })
        rules = [CastRule("maya", "Maya", MAYA), CastRule("tom", "Tom", TOM)]
        seen = {}

        async def fake(system, user, key):
            seen["user"] = user
            return answer

        with patch.object(aw, "request_animation_storyboard", fake):
            sb = await aw.generate_animation_storyboard("one two three four", words, "k", cast_list=rules)
        assert "ONLY characters" in seen["user"] and TOM in seen["user"]
        assert [e.id for e in sb.continuity if e.kind == "character"] == ["maya", "tom"]
        assert sb.continuity[0].description == MAYA
        assert [s.entities for s in sb.scenes] == [["maya"], []]


# ── S3: the run's voice ──────────────────────────────────────────────────


class TestRunVoice:
    SETTINGS = SimpleNamespace(GEMINI_TTS_VOICE="Zephyr", CREATOR_VOICE_MALE="Charon", CREATOR_VOICE_FEMALE="Kore")

    def test_male_and_female_pick_the_configured_voices(self):
        assert resolve_tts_voice("male", self.SETTINGS) == "Charon"
        assert resolve_tts_voice("female", self.SETTINGS) == "Kore"

    @pytest.mark.parametrize("choice", [None, "", "robot", 3])
    def test_no_or_an_unknown_choice_is_the_deployment_voice(self, choice):
        assert resolve_tts_voice(choice, self.SETTINGS) == "Zephyr"

    def test_the_male_default_is_the_deployments_own_voice(self):
        from cf_platform.core.config import PlatformSettings

        assert PlatformSettings.model_fields["CREATOR_VOICE_MALE"].default == ""
        own = SimpleNamespace(GEMINI_TTS_VOICE="Sadachbia", CREATOR_VOICE_MALE="", CREATOR_VOICE_FEMALE="Kore")
        assert resolve_tts_voice("male", own) == "Sadachbia" and resolve_tts_voice("female", own) == "Kore"

    def test_a_choice_whose_voice_is_not_configured_falls_back(self):
        bare = SimpleNamespace(GEMINI_TTS_VOICE="Zephyr", CREATOR_VOICE_MALE=" ")
        assert resolve_tts_voice("male", bare) == "Zephyr"
        assert resolve_tts_voice("female", bare) == "Zephyr"

    def test_the_voice_route_builds_the_worker_with_the_runs_voice(self):
        from cf_platform.interfaces.dependencies import get_effective_platform_settings
        from cf_platform.interfaces.routes import workers as workers_routes

        seen = {}

        def fake_build(storage, **kwargs):
            seen.update(kwargs)

            async def worker(state):
                raise RuntimeError("not run in this test")
            return worker

        async def no_background(*args, **kwargs):
            return None

        with p13_env() as env:
            asyncio.run(env.storage.put_json(f"runs/{RUN_ID}/settings.json", {"voice": "female"}))
            settings = SimpleNamespace(GEMINI_API_KEY="k", DEEPGRAM_API_KEY="", **vars(self.SETTINGS))
            app.dependency_overrides[get_effective_platform_settings] = lambda: settings
            try:
                with patch.object(workers_routes, "build_voice_production_worker", fake_build), \
                        patch.object(workers_routes, "_run_voice_background", no_background):
                    r = env.client.post("/platform/workers/voice", json={"run_id": RUN_ID, "script": "one two three"})
            finally:
                app.dependency_overrides.pop(get_effective_platform_settings, None)
        assert r.status_code == 202, r.text
        assert seen["gemini_tts_voice"] == "Kore"


# ── S5: sound effects off by default ─────────────────────────────────────


class TestSfxSwitch:
    def test_off_unless_the_deployment_turns_it_on(self):
        assert sfx_enabled(SimpleNamespace()) is False
        assert sfx_enabled(SimpleNamespace(SFX_ENABLED=False)) is False
        assert sfx_enabled(SimpleNamespace(SFX_ENABLED=True)) is True

    def test_the_platform_default_is_off(self):
        from cf_platform.core.config import PlatformSettings

        assert PlatformSettings.model_fields["SFX_ENABLED"].default is False

    def test_without_sfx_clears_every_scene_and_leaves_the_rest(self):
        sb = _storyboard()
        out = without_sfx(sb)
        assert [s.sfx for s in out.scenes] == ["", "", ""]
        assert [s.sfx for s in sb.scenes] == ["whoosh"] * 3, "the storyboard itself keeps the choice"
        assert [s.ai_prompt for s in out.scenes] == [s.ai_prompt for s in sb.scenes]
        assert without_sfx(out) is out

    def test_the_timeline_has_no_sound_effects_by_default(self):
        with p13_env(with_manifest=True, **{"1": {"sfx": "whoosh"}}) as env:
            off = env.client.get(f"/platform/studio/runs/{RUN_ID}/timeline")
            env.settings.SFX_ENABLED = True
            on = env.client.get(f"/platform/studio/runs/{RUN_ID}/timeline")
        assert off.status_code == 200 and on.status_code == 200, (off.text, on.text)
        assert all(s["sfx_path"] is None and s["sfx_key"] is None for s in off.json()["scenes"])
        assert on.json()["scenes"][0]["sfx_path"] == "sfx/whoosh.mp3"

    @pytest.mark.asyncio
    async def test_the_render_worker_drops_sound_effects_when_off(self):
        """The worker strips them before it copies SFX files or builds its own timeline."""
        from cf_platform.workers import render_worker as rw

        seen = {}

        async def spy(run_id, storyboard, storage):
            seen["sfx"] = [s.sfx for s in storyboard.scenes]
            raise RuntimeError("stop here")

        for flag, expected in ((False, ["", "", ""]), (True, ["whoosh"] * 3)):
            storage = InMemoryArtifactStorage()
            storyboard = make_storyboard(make_words(), **{str(n): {"sfx": "whoosh"} for n in (1, 2, 3)})
            sb_key = await seed_storyboard(storage, storyboard)
            mf_key = await seed_manifest(storage, make_manifest(storyboard))
            worker = rw.build_render_worker(storage, sfx_enabled=flag)
            state = StageState(run_id=RUN_ID, user_id="u", inputs={"music_enabled": False},
                               artifacts={"verified_storyboard": sb_key, "asset_manifest": mf_key})
            with patch.object(rw, "_copy_all_scene_sfx_to_run", spy), pytest.raises(RuntimeError, match="stop here"):
                await worker(state)
            assert seen["sfx"] == expected


# ── Smoke fix: a job that never started is "none", not "running" ─────────


class TestJobStatusNone:
    @pytest.mark.parametrize("kind", ["voice", "storyboard", "render"])
    def test_a_run_that_never_started_the_job_says_none(self, kind):
        with p13_env() as env:
            status = env.client.get(f"/platform/studio/runs/{RUN_ID}/{kind}/status").json()
        assert status == {"status": "none"}

    @pytest.mark.parametrize("kind", ["voice", "storyboard", "render"])
    def test_a_started_job_still_says_running(self, kind):
        with p13_env() as env:
            asyncio.run(env.storage.put_json(f"runs/{RUN_ID}/{kind}/current_job.json", {"job_id": "j", "status": "running"}))
            status = env.client.get(f"/platform/studio/runs/{RUN_ID}/{kind}/status").json()
        assert status == {"status": "running"}

    def test_storage_that_cannot_list_counts_as_started(self):
        from cf_platform.interfaces.routes.studio import _job_started

        class Broken:
            async def list_keys(self, prefix):
                raise RuntimeError("R2 blip")

        assert asyncio.run(_job_started(Broken(), "runs/x/voice/current_job.json")) is True

    def test_the_page_resumes_only_a_running_job_and_gives_up_on_one_that_never_appears(self):
        from pathlib import Path

        js = (Path(__file__).resolve().parents[2] / "src" / "static" / "ui" / "creator.js").read_text(encoding="utf-8")
        resume = js[js.index("async function resumeJobs"):js.index("const draftKey")]
        assert resume.count("=== 'running'") == 4
        assert "st.status === 'none' && ++missing >= 5" in js


class TestVideoOnlyWhenRendered:
    def test_a_run_without_final_mp4_has_no_video(self):
        with p13_env() as env:
            r = env.client.get(f"/platform/studio/runs/{RUN_ID}/video")
        assert r.status_code == 404

    def test_a_rendered_run_returns_its_url(self):
        with p13_env() as env:
            asyncio.run(env.storage.put_bytes(f"runs/{RUN_ID}/output/final.mp4", b"MP4", "video/mp4"))
            r = env.client.get(f"/platform/studio/runs/{RUN_ID}/video")
        assert r.status_code == 200 and r.json()["video_url"] and r.json()["source"] == "ffmpeg"
