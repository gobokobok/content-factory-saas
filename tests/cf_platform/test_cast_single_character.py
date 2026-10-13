"""One character throughout a video (D113): the rule is resolved, given to the model and enforced in code."""

from unittest.mock import patch

import pytest

from cf_platform.core import project_assets as pa
from cf_platform.core.cast import CastRule, enforce_single_cast, prompt_block, resolve_cast
from cf_platform.workers.voice_production import VoiceWordTimestamp
from src.models import Storyboard

MAYA = "a cheerful woman in her thirties with short curly black hair and a red scarf"


def _storyboard() -> Storyboard:
    scene = lambda n, ents: {  # noqa: E731 - a small local builder
        "scene": str(n), "clip_type": "still_with_motion", "duration_s": 2.0, "voiceover_line": f"line {n}",
        "segment_type": "B-roll", "asset_strategy": "ai_image", "asset_tier": "still", "motion_effect": "zoom_in",
        "start_word": n - 1, "end_word": n - 1, "entities": ents, "ai_prompt": f"prompt {n}",
    }
    return Storyboard.model_validate({
        "global": {"subtitle_style": "", "bg_music": "", "visual_style": ""},
        "scenes": [scene(1, ["rival", "desk"]), scene(2, ["learner"]), scene(3, [])],
        "summary": {"total_scenes": 3, "total_duration_s": 6, "rhythm": ""},
        "visual_mode": "ai_animation",
        "continuity": [
            {"id": "learner", "kind": "character", "name": "the learner", "description": "a student"},
            {"id": "rival", "kind": "character", "name": "the rival", "description": "a competitor"},
            {"id": "desk", "kind": "prop", "name": "the desk", "description": "an oak desk"},
        ],
    })


class TestResolve:
    def test_free_is_no_rule(self):
        assert resolve_cast({"cast_mode": "free", "protagonist_text": MAYA}, None) is None
        assert resolve_cast({}, None) is None

    def test_single_with_a_project_asset(self):
        config, _ = pa.add_asset({}, kind="character", name="Maya", description=MAYA)
        rule = resolve_cast({"cast_mode": "single", "protagonist_asset_id": "maya"}, config)
        assert rule == CastRule("maya", "Maya", MAYA, "maya")

    def test_a_deleted_asset_falls_back_to_the_typed_text_and_nothing_means_no_rule(self):
        rule = resolve_cast({"cast_mode": "single", "protagonist_asset_id": "gone", "protagonist_text": "  a tall man  "}, {})
        assert rule == CastRule("protagonist", "the protagonist", "a tall man")
        assert resolve_cast({"cast_mode": "single", "protagonist_asset_id": "gone"}, {}) is None

    def test_the_prompt_block_names_the_rule(self):
        block = prompt_block(CastRule("maya", "Maya", MAYA, "maya"))
        assert 'id "maya"' in block and MAYA in block and "Do NOT create any other character" in block
        assert prompt_block(None) == ""


class TestEnforce:
    def test_other_characters_are_removed_and_their_scenes_show_the_protagonist(self):
        out = enforce_single_cast(_storyboard(), CastRule("maya", "Maya", MAYA, "maya"))
        ids = [e.id for e in out.continuity]
        assert "learner" not in ids and "rival" not in ids and "desk" in ids and "maya" in ids
        assert out.continuity[0].description == MAYA and out.continuity[0].project_asset_id == "maya"
        assert [s.entities for s in out.scenes] == [["maya", "desk"], ["maya"], []]

    def test_a_protagonist_the_model_already_made_is_overwritten_not_duplicated(self):
        out = enforce_single_cast(_storyboard(), CastRule("learner", "Maya", MAYA))
        assert [e.id for e in out.continuity].count("learner") == 1
        assert next(e for e in out.continuity if e.id == "learner").description == MAYA
        assert [s.entities for s in out.scenes] == [["learner", "desk"], ["learner"], []]

    def test_no_rule_changes_nothing(self):
        sb = _storyboard()
        assert enforce_single_cast(sb, None) is sb


class TestThroughTheWorker:
    @pytest.mark.asyncio
    async def test_a_second_character_from_the_model_never_survives(self):
        from cf_platform.workers import animation_storyboard_worker as aw

        words = [VoiceWordTimestamp(word=w, start_ms=i * 300, end_ms=i * 300 + 250) for i, w in enumerate("one two three four".split())]
        answer = (
            '{"continuity":[{"id":"ann","kind":"character","name":"Ann","description":"a young woman"},'
            '{"id":"bob","kind":"character","name":"Bob","description":"an older man"}],'
            '"scenes":[{"start_word":0,"end_word":1,"ai_prompt":"ann at a desk","entities":["ann"],'
            '"shot":{"size":"wide","angle":"eye"},"motion_effect":"zoom_in","visual_concept":"c","visual_keywords":["k"]},'
            '{"start_word":2,"end_word":3,"ai_prompt":"bob walks","entities":["bob"],'
            '"shot":{"size":"wide","angle":"eye"},"motion_effect":"zoom_in","visual_concept":"c","visual_keywords":["k"]}]}'
        )
        rule = CastRule("protagonist", "the protagonist", MAYA)
        seen = {}

        async def fake(system, user, key):
            seen["user"] = user
            return answer

        with patch.object(aw, "request_animation_storyboard", fake):
            sb = await aw.generate_animation_storyboard("one two three four", words, "k", cast=rule)
        assert "CAST RULE" in seen["user"] and MAYA in seen["user"]
        assert [e.id for e in sb.continuity if e.kind == "character"] == ["protagonist"]
        assert all(s.entities == ["protagonist"] for s in sb.scenes)
