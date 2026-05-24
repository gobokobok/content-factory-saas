"""Tests for src/captions.py."""

from typing import Optional

import pytest

from src.captions import build_ass, format_ass_time
from src.models import StoryboardScene, VisualPrompts


# ── Helpers ───────────────────────────────────────────────────────────────────


def _scene(
    scene_id: str,
    duration_s: float = 3.0,
    on_screen_text: Optional[str] = None,
) -> StoryboardScene:
    return StoryboardScene(
        scene=scene_id,
        clip_type="hard_cut",
        duration_s=duration_s,
        voiceover_line="Test line.",
        visual_prompts=VisualPrompts(
            primary_stk="housing", fallback_stk="real estate", ai_generate="prompt"
        ),
        on_screen_text=on_screen_text,
        sfx="silence",
        sfx_timing="scene_start",
    )


# ── Unit: format_ass_time ─────────────────────────────────────────────────────


class TestFormatAssTime:
    def test_zero(self):
        assert format_ass_time(0.0) == "0:00:00.00"

    def test_sub_second(self):
        assert format_ass_time(0.5) == "0:00:00.50"

    def test_one_and_half_seconds(self):
        assert format_ass_time(1.5) == "0:00:01.50"

    def test_one_minute(self):
        assert format_ass_time(60.0) == "0:01:00.00"

    def test_minutes_and_seconds(self):
        assert format_ass_time(62.0) == "0:01:02.00"

    def test_one_hour(self):
        assert format_ass_time(3600.0) == "1:00:00.00"

    def test_hour_minutes_seconds(self):
        assert format_ass_time(3661.0) == "1:01:01.00"

    def test_centiseconds_precision(self):
        # 2.75s → 275cs → 0:00:02.75
        assert format_ass_time(2.75) == "0:00:02.75"

    def test_rounding_at_half_centisecond(self):
        # 1.005 * 100 = 100.499... in IEEE 754, so rounds down to 100cs
        assert format_ass_time(1.005) == "0:00:01.00"


# ── Unit: build_ass ───────────────────────────────────────────────────────────


class TestBuildAss:
    def test_script_info_present(self):
        result = build_ass([_scene("01")])
        assert "PlayResX: 1080" in result
        assert "PlayResY: 1920" in result

    def test_style_definition_present(self):
        result = build_ass([_scene("01")])
        assert "Style: Default,Open Sans,72" in result

    def test_events_section_header_present(self):
        result = build_ass([_scene("01")])
        assert "[Events]" in result

    def test_null_on_screen_text_produces_no_dialogue(self):
        scenes = [_scene("01", on_screen_text=None), _scene("02", on_screen_text=None)]
        result = build_ass(scenes)
        assert "Dialogue" not in result

    def test_all_null_returns_header_only(self):
        result = build_ass([_scene("01"), _scene("02")])
        assert result.count("Dialogue") == 0

    def test_on_screen_text_produces_dialogue_event(self):
        result = build_ass([_scene("01", on_screen_text="Hello World")])
        assert "Dialogue:" in result

    def test_text_is_uppercased(self):
        result = build_ass([_scene("01", on_screen_text="hello world")])
        assert "HELLO WORLD" in result
        assert "hello world" not in result

    def test_null_scenes_skipped_others_included(self):
        scenes = [
            _scene("01", on_screen_text=None),
            _scene("02", on_screen_text="Keep this"),
        ]
        result = build_ass(scenes)
        assert result.count("Dialogue") == 1
        assert "KEEP THIS" in result

    def test_first_scene_starts_at_zero(self):
        result = build_ass([_scene("01", duration_s=2.0, on_screen_text="text")])
        assert "0:00:00.00" in result

    def test_second_scene_starts_after_first(self):
        scenes = [
            _scene("01", duration_s=2.5, on_screen_text=None),
            _scene("02", duration_s=3.0, on_screen_text="second"),
        ]
        result = build_ass(scenes)
        # Scene 02 starts at 2.5s → 0:00:02.50
        assert "0:00:02.50" in result

    def test_scene_end_time_matches_start_plus_duration(self):
        result = build_ass([_scene("01", duration_s=4.0, on_screen_text="text")])
        # start=0:00:00.00, end=0:00:04.00
        assert "0:00:00.00,0:00:04.00" in result

    def test_multiple_events_ordered(self):
        scenes = [
            _scene("01", duration_s=2.0, on_screen_text="first"),
            _scene("02", duration_s=3.0, on_screen_text="second"),
        ]
        result = build_ass(scenes)
        first_pos = result.index("FIRST")
        second_pos = result.index("SECOND")
        assert first_pos < second_pos

    def test_empty_scene_list_returns_header_only(self):
        result = build_ass([])
        assert "[Script Info]" in result
        assert "Dialogue" not in result

    def test_result_ends_with_newline(self):
        # Ensures heredoc terminator lands on its own line
        assert build_ass([_scene("01")]).endswith("\n")
        assert build_ass([_scene("01", on_screen_text="hi")]).endswith("\n")
