"""Tests for P9-S1: Storyboard schema v2 — new models and field extensions."""

import json
import pytest
from pydantic import ValidationError

from src.models import (
    LowerThirdSpec,
    ManifestEntry,
    OnScreenTextOverlay,
    SceneRenderOptions,
    StoryboardScene,
    VisualPrompts,
)


# ── LowerThirdSpec ─────────────────────────────────────────────────────────────


class TestLowerThirdSpec:
    def test_required_field_name(self):
        """name is required; title and caption_y_override are optional."""
        spec = LowerThirdSpec(name="Jerome Powell")
        assert spec.name == "Jerome Powell"
        assert spec.title is None
        assert spec.caption_y_override == 1540

    def test_title_set(self):
        """title field persists when provided."""
        spec = LowerThirdSpec(name="Janet Yellen", title="Secretary of the Treasury")
        assert spec.title == "Secretary of the Treasury"

    def test_caption_y_override_custom(self):
        """caption_y_override can be overridden."""
        spec = LowerThirdSpec(name="X", caption_y_override=1400)
        assert spec.caption_y_override == 1400


# ── OnScreenTextOverlay ────────────────────────────────────────────────────────


class TestOnScreenTextOverlay:
    def test_stat_type(self):
        """Accepts 'stat' as a valid type."""
        overlay = OnScreenTextOverlay(text="38%", type="stat", enable_expr="between(t,2,4)")
        assert overlay.type == "stat"
        assert overlay.text == "38%"
        assert overlay.enable_expr == "between(t,2,4)"

    def test_date_type(self):
        """Accepts 'date' as a valid type."""
        overlay = OnScreenTextOverlay(text="2008", type="date", enable_expr="between(t,0,2)")
        assert overlay.type == "date"

    def test_lower_third_type(self):
        """Accepts 'lower_third' as a valid type."""
        overlay = OnScreenTextOverlay(text="Powell", type="lower_third", enable_expr="between(t,0,3)")
        assert overlay.type == "lower_third"

    def test_invalid_type_rejected(self):
        """Unknown type values are rejected."""
        with pytest.raises(ValidationError):
            OnScreenTextOverlay(text="x", type="banner", enable_expr="between(t,0,1)")


# ── SceneRenderOptions ─────────────────────────────────────────────────────────


class TestSceneRenderOptions:
    def test_defaults(self):
        """All fields default to False/None."""
        opts = SceneRenderOptions()
        assert opts.film_look is False
        assert opts.lower_third is None
        assert opts.on_screen_text_overlay is None

    def test_film_look(self):
        """film_look can be set True."""
        opts = SceneRenderOptions(film_look=True)
        assert opts.film_look is True

    def test_with_lower_third(self):
        """lower_third accepts a LowerThirdSpec."""
        spec = LowerThirdSpec(name="Powell", title="Fed Chair")
        opts = SceneRenderOptions(lower_third=spec)
        assert opts.lower_third.name == "Powell"
        assert opts.lower_third.caption_y_override == 1540

    def test_with_text_overlay(self):
        """on_screen_text_overlay accepts an OnScreenTextOverlay."""
        overlay = OnScreenTextOverlay(text="38%", type="stat", enable_expr="between(t,1,3)")
        opts = SceneRenderOptions(on_screen_text_overlay=overlay)
        assert opts.on_screen_text_overlay.text == "38%"

    def test_json_round_trip(self):
        """SceneRenderOptions serialises and deserialises through JSON without loss."""
        opts = SceneRenderOptions(
            film_look=True,
            lower_third=LowerThirdSpec(name="A", title="B", caption_y_override=1500),
            on_screen_text_overlay=OnScreenTextOverlay(
                text="2008", type="date", enable_expr="between(t,0,2)"
            ),
        )
        dumped = json.loads(opts.model_dump_json())
        restored = SceneRenderOptions.model_validate(dumped)
        assert restored.film_look is True
        assert restored.lower_third.name == "A"
        assert restored.lower_third.caption_y_override == 1500
        assert restored.on_screen_text_overlay.type == "date"


# ── StoryboardScene — new fields ───────────────────────────────────────────────


def _minimal_v2_scene(**overrides) -> dict:
    """Minimal valid v2 StoryboardScene dict (flat queries, no visual_prompts)."""
    base = {
        "scene": "scene-1",
        "clip_type": "hard_cut",
        "duration_s": 3.0,
        "voiceover_line": "The housing market crashed.",
        "primary_stk": "housing market crash exterior",
        "context_stk": "real estate crisis",
        "concept_stk": "economic collapse",
        "sfx": "none",
        "sfx_timing": "none",
    }
    base.update(overrides)
    return base


class TestStoryboardSceneV2Fields:
    def test_segment_type_defaults_to_broll(self):
        """segment_type defaults to 'B-roll' when omitted."""
        scene = StoryboardScene.model_validate(_minimal_v2_scene())
        assert scene.segment_type == "B-roll"

    def test_segment_type_character(self):
        """segment_type accepts 'Character'."""
        scene = StoryboardScene.model_validate(
            _minimal_v2_scene(segment_type="Character", person_name="Jerome Powell")
        )
        assert scene.segment_type == "Character"

    def test_segment_type_event(self):
        """segment_type accepts 'Event'."""
        scene = StoryboardScene.model_validate(_minimal_v2_scene(segment_type="Event"))
        assert scene.segment_type == "Event"

    def test_segment_type_invalid_rejected(self):
        """Unknown segment_type values are rejected."""
        with pytest.raises(ValidationError):
            StoryboardScene.model_validate(_minimal_v2_scene(segment_type="Intro"))

    def test_flat_query_fields_present(self):
        """primary_stk, context_stk, concept_stk are stored correctly."""
        scene = StoryboardScene.model_validate(_minimal_v2_scene())
        assert scene.primary_stk == "housing market crash exterior"
        assert scene.context_stk == "real estate crisis"
        assert scene.concept_stk == "economic collapse"

    def test_on_screen_text_type_stat(self):
        """on_screen_text_type accepts 'stat'."""
        scene = StoryboardScene.model_validate(
            _minimal_v2_scene(on_screen_text="38%", on_screen_text_type="stat")
        )
        assert scene.on_screen_text_type == "stat"

    def test_on_screen_text_type_date(self):
        """on_screen_text_type accepts 'date'."""
        scene = StoryboardScene.model_validate(
            _minimal_v2_scene(on_screen_text="2008", on_screen_text_type="date")
        )
        assert scene.on_screen_text_type == "date"

    def test_on_screen_text_type_lower_third(self):
        """on_screen_text_type accepts 'lower_third'."""
        scene = StoryboardScene.model_validate(
            _minimal_v2_scene(on_screen_text="Powell", on_screen_text_type="lower_third")
        )
        assert scene.on_screen_text_type == "lower_third"

    def test_on_screen_text_type_invalid_rejected(self):
        """Unknown on_screen_text_type values are rejected."""
        with pytest.raises(ValidationError):
            StoryboardScene.model_validate(_minimal_v2_scene(on_screen_text_type="banner"))

    def test_render_options_accepted(self):
        """render_options field stores a SceneRenderOptions when provided."""
        data = _minimal_v2_scene(render_options={"film_look": True})
        scene = StoryboardScene.model_validate(data)
        assert scene.render_options is not None
        assert scene.render_options.film_look is True

    def test_render_options_defaults_none(self):
        """render_options is None when omitted."""
        scene = StoryboardScene.model_validate(_minimal_v2_scene())
        assert scene.render_options is None


# ── Backward compat: v1 storyboard JSON with visual_prompts ───────────────────


def _v1_scene_dict(**overrides) -> dict:
    """Minimal v1 StoryboardScene dict using the visual_prompts nested struct."""
    base = {
        "scene": "scene-1",
        "clip_type": "still_with_motion",
        "duration_s": 4.0,
        "voiceover_line": "Prices rose sharply.",
        "visual_prompts": {
            "primary_stk": "rising house prices suburb",
            "fallback_stk": "real estate market",
            "ai_generate": "suburban neighbourhood with for-sale signs",
        },
        "sfx": "none",
        "sfx_timing": "none",
    }
    base.update(overrides)
    return base


class TestStoryboardSceneV1BackwardCompat:
    def test_v1_json_parses_without_error(self):
        """Old storyboard JSON with visual_prompts and no v2 fields parses cleanly."""
        scene = StoryboardScene.model_validate(_v1_scene_dict())
        assert scene.visual_prompts is not None
        assert scene.visual_prompts.primary_stk == "rising house prices suburb"

    def test_primary_stk_backfilled_from_visual_prompts(self):
        """primary_stk is populated from visual_prompts.primary_stk when absent."""
        scene = StoryboardScene.model_validate(_v1_scene_dict())
        assert scene.primary_stk == "rising house prices suburb"

    def test_context_stk_backfilled_from_visual_prompts(self):
        """context_stk is populated from visual_prompts.fallback_stk when absent."""
        scene = StoryboardScene.model_validate(_v1_scene_dict())
        assert scene.context_stk == "real estate market"

    def test_concept_stk_not_backfilled(self):
        """concept_stk has no v1 equivalent and remains empty string."""
        scene = StoryboardScene.model_validate(_v1_scene_dict())
        assert scene.concept_stk == ""

    def test_explicit_primary_stk_not_overwritten_by_validator(self):
        """When primary_stk is already set, the validator does not overwrite it."""
        data = _v1_scene_dict(primary_stk="explicit override")
        scene = StoryboardScene.model_validate(data)
        assert scene.primary_stk == "explicit override"

    def test_segment_type_defaults_to_broll_on_v1_scene(self):
        """v1 scenes lacking segment_type get the 'B-roll' default."""
        scene = StoryboardScene.model_validate(_v1_scene_dict())
        assert scene.segment_type == "B-roll"

    def test_historic_alias_still_parsed(self):
        """historic field continues to parse on v1 storyboards."""
        scene = StoryboardScene.model_validate(_v1_scene_dict(historic=True))
        assert scene.historic is True


# ── ManifestEntry v2 fields ───────────────────────────────────────────────────


class TestManifestEntryV2Fields:
    def test_old_required_fields_now_optional(self):
        """primary_query, fallback_query, ai_generate_prompt default to None."""
        entry = ManifestEntry(scene_id="s1", clip_type="hard_cut")
        assert entry.primary_query is None
        assert entry.fallback_query is None
        assert entry.ai_generate_prompt is None

    def test_v1_fields_still_accepted_as_strings(self):
        """Legacy callers that set primary_query/fallback_query as strings still work."""
        entry = ManifestEntry(
            scene_id="s1",
            clip_type="hard_cut",
            primary_query="housing exterior",
            fallback_query="real estate",
            ai_generate_prompt="suburban street",
        )
        assert entry.primary_query == "housing exterior"

    def test_v2_flat_fields_default_values(self):
        """New v2 fields have correct defaults."""
        entry = ManifestEntry(scene_id="s1", clip_type="hard_cut")
        assert entry.segment_type == "B-roll"
        assert entry.primary_stk == ""
        assert entry.context_stk == ""
        assert entry.concept_stk == ""

    def test_v2_flat_fields_set(self):
        """New v2 fields accept string values."""
        entry = ManifestEntry(
            scene_id="s1",
            clip_type="hard_cut",
            segment_type="Character",
            primary_stk="jerome powell federal reserve",
            context_stk="central bank interest rates",
            concept_stk="monetary policy",
        )
        assert entry.segment_type == "Character"
        assert entry.primary_stk == "jerome powell federal reserve"
        assert entry.context_stk == "central bank interest rates"
        assert entry.concept_stk == "monetary policy"

    def test_historic_alias_preserved(self):
        """historic field still parses on ManifestEntry for R2 backward compat."""
        entry = ManifestEntry(scene_id="s1", clip_type="hard_cut", historic=True)
        assert entry.historic is True

    def test_existing_qa_fields_unaffected(self):
        """P8 QA fields remain intact alongside new v2 fields."""
        entry = ManifestEntry(
            scene_id="s1",
            clip_type="hard_cut",
            qa_passed=True,
            qa_resolution_ok=True,
            qa_clip_score=0.45,
        )
        assert entry.qa_passed is True
        assert entry.qa_clip_score == 0.45
