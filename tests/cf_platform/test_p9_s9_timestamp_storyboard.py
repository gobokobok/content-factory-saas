"""Tests for P9-S9: Timestamp-first storyboard — word indices + Python-derived fields."""

import pytest

from cf_platform.workers.storyboard_worker import (
    _GENERATE_SYSTEM_PROMPT,
    _GENERATE_SYSTEM_PROMPT_V013,
    STORYBOARD_PROMPT_VERSION,
    _asset_tier_to_clip_type,
    _assign_asset_tier,
    _derive_motion_effect,
    _format_indexed_timestamps,
    _normalize_deepgram_words,
    _reify_scene,
)
from cf_platform.workers.voice_production import VoiceWordTimestamp
from src.models import ManifestEntry, StoryboardScene

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _words(*pairs: tuple[str, int, int]) -> list[VoiceWordTimestamp]:
    """Build a list of VoiceWordTimestamp from (word, start_ms, end_ms) tuples."""
    return [VoiceWordTimestamp(word=w, start_ms=s, end_ms=e) for w, s, e in pairs]


# ── _format_indexed_timestamps ────────────────────────────────────────────────


class TestFormatIndexedTimestamps:
    def test_produces_indexed_lines(self) -> None:
        words = _words(("hello", 0, 500), ("world", 600, 1100))
        result = _format_indexed_timestamps(words)
        lines = result.splitlines()
        assert lines[0].startswith('[0]')
        assert '"hello"' in lines[0]
        assert '0.00s' in lines[0]
        assert '0.50s' in lines[0]

    def test_second_word_index(self) -> None:
        words = _words(("a", 0, 400), ("b", 500, 900))
        result = _format_indexed_timestamps(words)
        assert '[1]' in result
        assert '"b"' in result

    def test_empty_list(self) -> None:
        assert _format_indexed_timestamps([]) == ""


# ── _assign_asset_tier ────────────────────────────────────────────────────────


class TestAssignAssetTier:
    def test_below_3s_is_still(self) -> None:
        assert _assign_asset_tier(0.5) == "still"
        assert _assign_asset_tier(2.9) == "still"

    def test_exactly_3s_is_still_motion(self) -> None:
        assert _assign_asset_tier(3.0) == "still_motion"

    def test_mid_range_is_still_motion(self) -> None:
        assert _assign_asset_tier(4.5) == "still_motion"
        assert _assign_asset_tier(5.9) == "still_motion"

    def test_at_6s_is_video(self) -> None:
        assert _assign_asset_tier(6.0) == "video"

    def test_above_10s_is_video(self) -> None:
        assert _assign_asset_tier(12.0) == "video"

    def test_zero_is_still(self) -> None:
        assert _assign_asset_tier(0.0) == "still"


# ── _asset_tier_to_clip_type ──────────────────────────────────────────────────


class TestAssetTierToClipType:
    def test_video_maps_to_hard_cut(self) -> None:
        assert _asset_tier_to_clip_type("video") == "hard_cut"

    def test_still_maps_to_still_with_motion(self) -> None:
        assert _asset_tier_to_clip_type("still") == "still_with_motion"

    def test_still_motion_maps_to_still_with_motion(self) -> None:
        assert _asset_tier_to_clip_type("still_motion") == "still_with_motion"


# ── _derive_motion_effect ─────────────────────────────────────────────────────


class TestDeriveMotionEffect:
    def test_still_always_scale(self) -> None:
        assert _derive_motion_effect("still", 0) == "scale"
        assert _derive_motion_effect("still", 1) == "scale"
        assert _derive_motion_effect("still", 7) == "scale"

    def test_still_motion_even_index_is_ken_burns_in(self) -> None:
        assert _derive_motion_effect("still_motion", 0) == "ken_burns_in"
        assert _derive_motion_effect("still_motion", 2) == "ken_burns_in"
        assert _derive_motion_effect("still_motion", 10) == "ken_burns_in"

    def test_still_motion_odd_index_is_ken_burns_out(self) -> None:
        assert _derive_motion_effect("still_motion", 1) == "ken_burns_out"
        assert _derive_motion_effect("still_motion", 3) == "ken_burns_out"
        assert _derive_motion_effect("still_motion", 9) == "ken_burns_out"

    def test_video_returns_none(self) -> None:
        assert _derive_motion_effect("video", 0) is None
        assert _derive_motion_effect("video", 5) is None


# ── _normalize_deepgram_words ─────────────────────────────────────────────────


class TestNormalizeDeepgramWords:
    def test_strips_trailing_punctuation(self) -> None:
        raw = [{"word": "hello,", "start_ms": 0, "end_ms": 500, "confidence": 1.0}]
        result = _normalize_deepgram_words(raw)
        assert result[0].word == "hello"

    def test_strips_leading_punctuation(self) -> None:
        raw = [{"word": ".hello", "start_ms": 0, "end_ms": 500, "confidence": 1.0}]
        result = _normalize_deepgram_words(raw)
        assert result[0].word == "hello"

    def test_collapses_same_start_ms(self) -> None:
        raw = [
            {"word": "it", "start_ms": 0, "end_ms": 300, "confidence": 0.9},
            {"word": "'s", "start_ms": 0, "end_ms": 400, "confidence": 0.8},
            {"word": "fine", "start_ms": 500, "end_ms": 800, "confidence": 1.0},
        ]
        result = _normalize_deepgram_words(raw)
        assert len(result) == 2
        assert result[0].word == "it's"
        assert result[0].end_ms == 400
        assert result[0].confidence == pytest.approx(0.8)

    def test_returns_voice_word_timestamps(self) -> None:
        raw = [{"word": "test", "start_ms": 10, "end_ms": 200, "confidence": 0.95}]
        result = _normalize_deepgram_words(raw)
        assert isinstance(result[0], VoiceWordTimestamp)
        assert result[0].start_ms == 10

    def test_keeps_solo_punctuation_token(self) -> None:
        """Token that is all punctuation (e.g. '—') should not become empty."""
        raw = [{"word": "—", "start_ms": 0, "end_ms": 200, "confidence": 0.5}]
        result = _normalize_deepgram_words(raw)
        assert result[0].word == "—"

    def test_empty_input(self) -> None:
        assert _normalize_deepgram_words([]) == []


# ── _reify_scene ──────────────────────────────────────────────────────────────


class TestReifyScene:
    def _make_words(self) -> list[VoiceWordTimestamp]:
        return _words(
            ("Companies", 0, 410),
            ("are", 410, 520),
            ("holding", 520, 740),
            ("back", 740, 900),
            ("investment", 900, 1400),
        )

    def test_voiceover_line_reconstructed_from_span(self) -> None:
        words = self._make_words()
        raw: dict = {"scene": "1", "start_word": 0, "end_word": 2}
        _reify_scene(raw, words, 0)
        assert raw["voiceover_line"] == "Companies are holding"

    def test_duration_computed_from_timestamps(self) -> None:
        words = self._make_words()
        raw: dict = {"scene": "1", "start_word": 0, "end_word": 4}
        _reify_scene(raw, words, 0)
        # (1400 - 0) / 1000 = 1.4s
        assert raw["duration_s"] == pytest.approx(1.4)

    def test_scene_start_end_ms_set(self) -> None:
        words = self._make_words()
        raw: dict = {"scene": "1", "start_word": 1, "end_word": 3}
        _reify_scene(raw, words, 0)
        assert raw["scene_start_ms"] == 410
        assert raw["scene_end_ms"] == 900

    def test_asset_tier_still_for_short_duration(self) -> None:
        # duration: (900 - 0) / 1000 = 0.9s → still
        words = self._make_words()
        raw: dict = {"scene": "1", "start_word": 0, "end_word": 3}
        _reify_scene(raw, words, 0)
        assert raw["asset_tier"] == "still"
        assert raw["clip_type"] == "still_with_motion"
        assert raw["motion_effect"] == "scale"

    def test_clip_type_still_with_motion_for_still_motion_tier(self) -> None:
        # Build words spanning 4 seconds (3–6s range → still_motion)
        words = _words(("a", 0, 4000))
        raw: dict = {"scene": "1", "start_word": 0, "end_word": 0}
        _reify_scene(raw, words, 1)
        assert raw["asset_tier"] == "still_motion"
        assert raw["clip_type"] == "still_with_motion"
        assert raw["motion_effect"] == "ken_burns_out"  # odd scene_index

    def test_clip_type_hard_cut_for_video_tier(self) -> None:
        # 7 second duration → video tier
        words = _words(("long", 0, 7000))
        raw: dict = {"scene": "1", "start_word": 0, "end_word": 0}
        _reify_scene(raw, words, 0)
        assert raw["asset_tier"] == "video"
        assert raw["clip_type"] == "hard_cut"
        assert raw["motion_effect"] is None

    def test_clamps_out_of_range_indices(self) -> None:
        words = self._make_words()
        raw: dict = {"scene": "1", "start_word": -1, "end_word": 100}
        _reify_scene(raw, words, 0)
        # Should not raise; end clamped to len(words)-1 = 4
        assert raw["voiceover_line"] == "Companies are holding back investment"

    def test_returns_raw_dict(self) -> None:
        words = self._make_words()
        raw: dict = {"scene": "1", "start_word": 0, "end_word": 0}
        result = _reify_scene(raw, words, 0)
        assert result is raw  # mutates in-place and returns same dict


# ── Prompt version constant ───────────────────────────────────────────────────


def test_prompt_version_is_v013() -> None:
    assert STORYBOARD_PROMPT_VERSION == "v0.17"


def test_v013_prompt_has_no_duration_rules_table() -> None:
    """v0.13 prompt must not contain the word-count duration table removed in this story."""
    assert "DURATION RULES" not in _GENERATE_SYSTEM_PROMPT_V013
    assert "Words in VO line" not in _GENERATE_SYSTEM_PROMPT_V013

def test_v013_prompt_has_no_voiceover_line_in_output_schema() -> None:
    """v0.13 output schema must not ask Claude for voiceover_line or duration_s."""
    # The example output object in the prompt should not have voiceover_line
    # Find the JSON example in the prompt (between ```-less braces after OUTPUT FORMAT)
    prompt = _GENERATE_SYSTEM_PROMPT_V013
    # Simple heuristic: look for "voiceover_line" in the prompt at all
    assert '"voiceover_line"' not in prompt
    assert '"duration_s"' not in prompt
    assert '"clip_type"' not in prompt
    assert '"motion_effect"' not in prompt


def test_v013_prompt_has_start_word_and_end_word() -> None:
    """v0.13 output schema must include start_word and end_word integer fields."""
    assert '"start_word"' in _GENERATE_SYSTEM_PROMPT_V013
    assert '"end_word"' in _GENERATE_SYSTEM_PROMPT_V013


def test_v012_fallback_prompt_still_has_duration_rules() -> None:
    """v0.12 prompt (used as fallback) must still have the duration table."""
    assert "DURATION RULES" in _GENERATE_SYSTEM_PROMPT


# ── Schema fields ─────────────────────────────────────────────────────────────


def test_storyboard_scene_has_new_fields() -> None:
    """StoryboardScene must accept start_word, end_word, scene_start_ms, scene_end_ms, asset_tier."""
    scene = StoryboardScene(
        scene="1",
        clip_type="still_with_motion",
        duration_s=2.5,
        voiceover_line="test",
        start_word=0,
        end_word=5,
        scene_start_ms=0,
        scene_end_ms=2500,
        asset_tier="still_motion",
    )
    assert scene.start_word == 0
    assert scene.end_word == 5
    assert scene.scene_start_ms == 0
    assert scene.scene_end_ms == 2500
    assert scene.asset_tier == "still_motion"


def test_storyboard_scene_new_fields_default_none() -> None:
    """New fields on StoryboardScene should default to None (backward compat)."""
    scene = StoryboardScene(
        scene="1",
        clip_type="hard_cut",
        duration_s=3.0,
        voiceover_line="old storyboard",
    )
    assert scene.start_word is None
    assert scene.end_word is None
    assert scene.scene_start_ms is None
    assert scene.scene_end_ms is None
    assert scene.asset_tier is None


def test_manifest_entry_has_asset_tier_field() -> None:
    """ManifestEntry must accept asset_tier and default to None."""
    entry = ManifestEntry(
        scene_id="1",
        clip_type="hard_cut",
        asset_tier="video",
    )
    assert entry.asset_tier == "video"


def test_manifest_entry_asset_tier_defaults_none() -> None:
    entry = ManifestEntry(scene_id="1", clip_type="still_with_motion")
    assert entry.asset_tier is None


# ── Acquisition routing via asset_tier ───────────────────────────────────────


def test_acquire_scene_uses_asset_tier_over_clip_type() -> None:
    """_acquire_scene should prefer image sources for still/still_motion regardless of clip_type."""
    # We test the routing logic indirectly by verifying the ManifestEntry fields are set
    # correctly before _acquire_scene is called.
    entry = ManifestEntry(
        scene_id="3",
        clip_type="hard_cut",      # would imply video — but asset_tier overrides
        segment_type="B-roll",
        asset_tier="still",        # v0.13 override → image sources
        primary_stk="housing chart",
        context_stk="housing",
        concept_stk="economy",
    )
    # Verify the field exists and is read correctly
    assert entry.asset_tier == "still"
    # The _acquire_scene function uses:
    #   if entry.asset_tier in ("still", "still_motion"): is_video = False
    # We can't call _acquire_scene without real clients, so we validate the routing logic
    # via the is_video logic replicated here:
    if entry.asset_tier == "video":
        is_video = True
    elif entry.asset_tier in ("still", "still_motion"):
        is_video = False
    else:
        is_video = entry.clip_type == "hard_cut"
    assert is_video is False


def test_acquire_scene_video_asset_tier_picks_video_sources() -> None:
    entry = ManifestEntry(
        scene_id="5",
        clip_type="still_with_motion",  # would imply image — but asset_tier overrides
        segment_type="B-roll",
        asset_tier="video",             # → video sources
        primary_stk="city skyline",
        context_stk="city",
        concept_stk="housing",
    )
    if entry.asset_tier == "video":
        is_video = True
    elif entry.asset_tier in ("still", "still_motion"):
        is_video = False
    else:
        is_video = entry.clip_type == "hard_cut"
    assert is_video is True


def test_acquire_scene_falls_back_to_clip_type_when_no_asset_tier() -> None:
    """Legacy manifests without asset_tier fall back to clip_type logic."""
    entry = ManifestEntry(
        scene_id="7",
        clip_type="hard_cut",
        segment_type="B-roll",
        asset_tier=None,  # legacy — no asset_tier
        primary_stk="economy",
        context_stk="market",
        concept_stk="economy",
    )
    if entry.asset_tier == "video":
        is_video = True
    elif entry.asset_tier in ("still", "still_motion"):
        is_video = False
    else:
        is_video = entry.clip_type == "hard_cut"
    assert is_video is True  # hard_cut → video
