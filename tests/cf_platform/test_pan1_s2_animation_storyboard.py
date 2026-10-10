"""Tests for P-AN1-S2: the animation storyboard worker (D108).

The model call is replaced; nothing here reaches Anthropic.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, read_artifact
from cf_platform.core.schemas import StageState
from cf_platform.interfaces.api import StoryboardWorkerRequest, storyboard_worker_endpoint
from cf_platform.workers import animation_storyboard_worker as aw
from cf_platform.workers.animation_storyboard_worker import (
    ANIMATION_STORYBOARD_PROMPT_VERSION,
    ANIMATION_STORYBOARD_WORKER_REGISTRATION,
    AnimationStoryboardError,
    animation_scene_flags,
    animation_system_prompt,
    build_animation_storyboard_worker,
    build_animation_user_message,
    generate_animation_storyboard,
    parse_animation_storyboard,
)
from cf_platform.workers.storyboard_worker import STORYBOARD_WORKER_REGISTRATION
from src.models import MOTION_EFFECTS, Storyboard
from tests.cf_platform.p13_helpers import RUN_ID, make_storyboard, make_words, seed_voice

WORDS = make_words(12, 500)  # 12 words, 0.5 s each


def _answer(**over) -> str:
    """A model answer: three scenes over the 12 words, one bible entry."""
    data = {
        "continuity": [
            {"id": "Learner", "kind": "character", "name": "the learner", "description": "a student with a black bob"},
        ],
        "scenes": [
            {"scene": "1", "start_word": 0, "end_word": 3, "visual_concept": "c1", "visual_keywords": ["k1", " k2 "],
             "shot": {"size": "medium", "angle": "low"}, "entities": ["learner"], "ai_prompt": " the learner reads ",
             "motion_effect": "zoom_in", "motion_note": "Slow push-in.", "on_screen_text": None,
             "on_screen_text_type": None, "sfx": "silence"},
            {"scene": "2", "start_word": 4, "end_word": 7, "visual_concept": "c2", "visual_keywords": [],
             "shot": {"size": "wide", "angle": "high"}, "entities": [], "ai_prompt": "an empty desk",
             "motion_effect": "tilt_up", "motion_note": "Tilt up to the window.", "on_screen_text": "40%",
             "on_screen_text_type": "stat", "sfx": "no-such-sfx"},
            {"scene": "3", "start_word": 8, "end_word": 11, "visual_concept": "c3", "visual_keywords": ["k"],
             "shot": None, "entities": ["ghost"], "ai_prompt": "", "motion_effect": "static",
             "motion_note": "Static hold.", "sfx": "silence"},
        ],
    }
    data.update(over)
    return json.dumps(data)


class TestParse:
    def test_scenes_get_the_new_fields_and_python_owns_the_timing(self):
        sb = parse_animation_storyboard(_answer(), WORDS)
        s1 = sb.scenes[0]
        assert sb.visual_mode == "ai_animation"
        assert (s1.visual_concept, s1.visual_keywords, s1.motion_note) == ("c1", ["k1", "k2"], "Slow push-in.")
        assert (s1.shot.size, s1.shot.angle) == ("medium", "low")
        assert s1.ai_prompt == "the learner reads"
        assert (s1.start_word, s1.end_word, s1.duration_s) == (0, 3, 2.0)
        assert s1.voiceover_line == "w0 w1 w2 w3"

    def test_every_scene_is_an_ai_image_still_with_no_stock_queries(self):
        sb = parse_animation_storyboard(_answer(), WORDS)
        assert {s.asset_strategy for s in sb.scenes} == {"ai_image"}
        assert {s.clip_type for s in sb.scenes} == {"still_with_motion"}
        assert all(s.primary_stk == "" and s.segment_type == "B-roll" for s in sb.scenes)

    def test_the_bible_is_cleaned_and_entity_ids_resolve_to_it(self):
        sb = parse_animation_storyboard(_answer(), WORDS)
        assert [(e.id, e.kind, e.name) for e in sb.continuity] == [("learner", "character", "the learner")]
        assert sb.scenes[0].entities == ["learner"]

    def test_an_entity_id_that_is_not_in_the_bible_is_dropped(self, caplog):
        with caplog.at_level("WARNING"):
            sb = parse_animation_storyboard(_answer(), WORDS)
        assert sb.scenes[2].entities == []
        assert "ghost" in caplog.text

    def test_motion_effect_is_the_models_choice_from_the_vocabulary(self):
        sb = parse_animation_storyboard(_answer(), WORDS)
        assert sb.scenes[0].motion_effect == "zoom_in" and sb.scenes[2].motion_effect == "static"
        # a move the renderer does not have falls back to the still default; the wording is kept
        assert sb.scenes[1].motion_effect in MOTION_EFFECTS
        assert sb.scenes[1].motion_note == "Tilt up to the window."

    def test_overlays_map_to_on_screen_text_and_get_render_options(self):
        sb = parse_animation_storyboard(_answer(), WORDS)
        s2 = sb.scenes[1]
        assert (s2.on_screen_text, s2.on_screen_text_type) == ("40%", "stat")
        assert s2.render_options.on_screen_text_overlay.text == "40%"
        assert sb.scenes[0].render_options is None

    def test_an_unknown_sfx_becomes_silence(self):
        assert parse_animation_storyboard(_answer(), WORDS).scenes[1].sfx == "silence"

    def test_a_scene_without_a_prompt_is_flagged(self):
        sb = parse_animation_storyboard(_answer(), WORDS)
        assert sb.scenes[2].ai_prompt is None and sb.scenes[2].flags == ["needs_prompt"]
        assert sb.scenes[0].flags == []

    def test_a_scene_over_five_seconds_is_flagged_and_not_split(self):
        long_words = make_words(14, 1000)  # 14 s
        answer = _answer(scenes=[
            {"scene": "1", "start_word": 0, "end_word": 7, "ai_prompt": "long one", "motion_effect": "zoom_in"},
            {"scene": "2", "start_word": 8, "end_word": 13, "ai_prompt": "second", "motion_effect": "static"},
        ])
        sb = parse_animation_storyboard(answer, long_words)
        assert len(sb.scenes) == 2  # the stock path would have split these
        assert sb.scenes[0].duration_s == 8.0 and sb.scenes[0].flags == ["too_long"]
        assert sb.scenes[0].ai_prompt == "long one"
        assert sb.scenes[0].clip_type == "still_with_motion"  # never promoted to footage by its length

    def test_exactly_five_seconds_is_not_flagged(self):
        assert animation_scene_flags(5.0, "p") == [] and animation_scene_flags(5.04, "p") == []
        assert animation_scene_flags(5.2, "p") == ["too_long"]
        assert animation_scene_flags(2.0, "p", ["image_out_of_date", "too_long"]) == ["image_out_of_date"]

    def test_gaps_and_overlaps_in_the_word_spans_are_closed(self):
        answer = _answer(scenes=[
            {"scene": "b", "start_word": 6, "end_word": 9, "ai_prompt": "b"},
            {"scene": "a", "start_word": 1, "end_word": 7, "ai_prompt": "a"},
        ])
        sb = parse_animation_storyboard(answer, WORDS)
        assert [(s.scene, s.start_word, s.end_word) for s in sb.scenes] == [("1", 0, 5), ("2", 6, 11)]
        assert sb.scenes[0].ai_prompt == "a"

    def test_fenced_json_is_accepted(self):
        assert len(parse_animation_storyboard(f"```json\n{_answer()}\n```", WORDS).scenes) == 3

    def test_an_answer_that_is_not_json_or_has_no_scenes_is_an_error(self):
        with pytest.raises(AnimationStoryboardError):
            parse_animation_storyboard("I cannot do that.", WORDS)
        with pytest.raises(AnimationStoryboardError):
            parse_animation_storyboard(_answer(scenes=[]), WORDS)

    def test_bible_entries_without_a_description_or_with_a_repeated_id_are_dropped(self):
        answer = _answer(continuity=[
            {"id": "a", "kind": "character", "name": "A", "description": "first"},
            {"id": "A", "kind": "prop", "name": "A again", "description": "second"},
            {"id": "b", "kind": "prop", "name": "B", "description": "  "},
            {"id": "c", "kind": "vehicle", "name": "C", "description": "a red van"},
        ])
        sb = parse_animation_storyboard(answer, WORDS)
        assert [(e.id, e.kind, e.description) for e in sb.continuity] == [("a", "character", "first"), ("c", "prop", "a red van")]


class TestOldStoryboards:
    def test_a_storyboard_without_the_new_fields_still_loads_as_stock(self):
        old = make_storyboard(WORDS).model_dump(by_alias=True, mode="json")
        for key in ("visual_mode", "continuity"):
            old.pop(key)
        for scene in old["scenes"]:
            for key in ("visual_concept", "visual_keywords", "shot", "entities", "motion_note", "flags"):
                scene.pop(key)
        sb = Storyboard.model_validate(old)
        assert sb.visual_mode == "stock" and sb.continuity == []
        assert sb.scenes[0].entities == [] and sb.scenes[0].shot is None and sb.scenes[0].flags == []

    def test_null_lists_and_texts_are_tolerated(self):
        raw = make_storyboard(WORDS).model_dump(by_alias=True, mode="json")
        raw["scenes"][0].update(entities=None, visual_keywords=None, flags=None, visual_concept=None, motion_note=None)
        scene = Storyboard.model_validate(raw).scenes[0]
        assert (scene.entities, scene.visual_keywords, scene.flags, scene.visual_concept) == ([], [], [], "")


class TestPrompt:
    def test_the_system_prompt_has_the_vocabularies_and_the_json_contract(self):
        prompt = animation_system_prompt()
        assert "PLACEHOLDER" not in prompt
        for effect in MOTION_EFFECTS:
            assert f'"{effect}"' in prompt
        assert "start_word" in prompt and '"continuity"' in prompt and "Output ONLY a valid JSON object" in prompt

    def test_the_user_message_carries_the_style_as_context_the_format_and_the_word_budget(self):
        message = build_animation_user_message("the script", WORDS, [w.word for w in WORDS], "landscape", "INK STYLE")
        assert "Horizontal 16:9" in message and "INK STYLE" in message and "never repeat it" in message
        assert "2.0 words/sec" in message and "HARD MAXIMUM 10 words" in message
        assert '[0]  "w0"' in message and "the script" in message

    def test_portrait_is_the_default_format_and_a_missing_style_is_said(self):
        message = build_animation_user_message("s", WORDS, [w.word for w in WORDS], "portrait", "  ")
        assert "Vertical 9:16" in message and "None given" in message


class TestGenerate:
    @pytest.mark.asyncio
    async def test_no_voiceover_timing_is_refused_before_any_model_call(self):
        with patch.object(aw, "request_animation_storyboard", new_callable=AsyncMock) as call:
            with pytest.raises(AnimationStoryboardError, match="voiceover"):
                await generate_animation_storyboard("script", [], "key")
        call.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_style_reaches_the_model_and_is_not_echoed_in_the_output(self):
        with patch.object(aw, "request_animation_storyboard", new_callable=AsyncMock, return_value=_answer()) as call:
            sb = await generate_animation_storyboard("script", WORDS, "key", format_track="portrait", master_style="INK STYLE")
        _system, user, key = call.call_args.args
        assert "INK STYLE" in user and key == "key"
        assert "INK STYLE" not in json.dumps(sb.model_dump(by_alias=True, mode="json"))

    @pytest.mark.asyncio
    async def test_the_worker_emits_one_storyboard_artifact_with_its_prompt_version(self):
        from datetime import datetime

        from cf_platform.core.artifact_manager import write_artifact
        from cf_platform.workers.script_packager import ScriptArtifact
        from tests.cf_platform.p13_helpers import _lineage

        storage = InMemoryArtifactStorage()
        script = await write_artifact(
            storage, ScriptArtifact(idea_title="", niche=None, script="the script", word_count=2, status="ok", generated_at=datetime.now()),
            name="script", stage="script", run_id=RUN_ID, user_id="u", lineage=_lineage(),
        )
        voice_key = await seed_voice(storage, WORDS)
        worker = build_animation_storyboard_worker(storage, "key")
        state = StageState(
            run_id=RUN_ID, user_id="u", inputs={"format_track": "landscape", "master_style": "INK STYLE"},
            artifacts={"script": script.r2_key, "voice_alignment": voice_key},
        )
        with patch.object(aw, "request_animation_storyboard", new_callable=AsyncMock, return_value=_answer()) as call:
            output = await worker(state)
        assert output.artifact.prompt_version == ANIMATION_STORYBOARD_PROMPT_VERSION
        assert output.artifact.scene_count == 3
        assert output.artifact.storyboard["visual_mode"] == "ai_animation"
        assert "Horizontal 16:9" in call.call_args.args[1] and "INK STYLE" in call.call_args.args[1]

    def test_the_registration_pins_the_model_the_look_was_validated_on(self):
        reg = ANIMATION_STORYBOARD_WORKER_REGISTRATION
        assert reg.model == "claude-sonnet-5-5" and reg.prompt_version == ANIMATION_STORYBOARD_PROMPT_VERSION
        assert reg.prompt_version != STORYBOARD_WORKER_REGISTRATION.prompt_version


class TestWorkerSelection:
    """The storyboard endpoint picks the worker from the run's visual_mode."""

    async def _call(self, settings_json: dict | None, *, with_voice: bool = True):
        """Run the endpoint with both builders replaced; return (stock_called, animation_called, state, lineage)."""
        from unittest.mock import MagicMock

        from pydantic import BaseModel

        from cf_platform.core.schemas import WorkerOutput

        storage = InMemoryArtifactStorage()
        if settings_json is not None:
            await storage.put_json(f"runs/{RUN_ID}/settings.json", settings_json)
        if with_voice:
            await seed_voice(storage, WORDS)
        seen: dict = {"states": []}

        class _FakeArtifact(BaseModel):
            scene_count: int = 1
            prompt_version: str = "x"

        async def _fake_worker(state):
            seen["states"].append(state)
            return WorkerOutput(artifact=_FakeArtifact())

        tasks = BackgroundTasks()
        with patch("cf_platform.interfaces.routes.workers.build_storyboard_worker", return_value=_fake_worker) as stock, \
             patch("cf_platform.interfaces.routes.workers.build_animation_storyboard_worker", return_value=_fake_worker) as anim, \
             patch("cf_platform.interfaces.routes.workers.VerifiedStoryboardArtifact", _FakeArtifact):
            await storyboard_worker_endpoint(
                StoryboardWorkerRequest(run_id=RUN_ID, script="A script.", format_track="portrait"), tasks,
                storage=storage, settings=MagicMock(ANTHROPIC_API_KEY="k"), runs=None, projects=None,
            )
            await tasks()
        keys = [k for k in storage._objects if "/storyboard/verified_storyboard@v" in k]
        record, _ = await read_artifact(storage, keys[0])
        lineage = record.lineage
        return stock.called, anim.called, seen["states"][0], lineage

    @pytest.mark.asyncio
    async def test_a_run_without_settings_uses_the_stock_worker(self):
        stock, anim, state, lineage = await self._call(None)
        assert (stock, anim) == (True, False)
        assert "master_style" not in state.inputs
        assert lineage.worker == "storyboard_worker" and lineage.prompt_version == STORYBOARD_WORKER_REGISTRATION.prompt_version

    @pytest.mark.asyncio
    async def test_a_stock_run_uses_the_stock_worker(self):
        stock, anim, _, _ = await self._call({"visual_mode": "stock", "master_style": "ignored"})
        assert (stock, anim) == (True, False)

    @pytest.mark.asyncio
    async def test_an_animation_run_uses_the_animation_worker_with_its_style_and_lineage(self):
        stock, anim, state, lineage = await self._call({"visual_mode": "ai_animation", "master_style": "INK STYLE"})
        assert (stock, anim) == (False, True)
        assert state.inputs == {"format_track": "portrait", "master_style": "INK STYLE"}
        assert lineage.worker == "animation_storyboard_worker" and lineage.model == "claude-sonnet-5-5"
        assert lineage.prompt_version == ANIMATION_STORYBOARD_PROMPT_VERSION

    @pytest.mark.asyncio
    async def test_an_animation_run_without_a_voiceover_is_409(self):
        with pytest.raises(HTTPException) as exc:
            await self._call({"visual_mode": "ai_animation"}, with_voice=False)
        assert exc.value.status_code == 409 and "voiceover" in exc.value.detail
