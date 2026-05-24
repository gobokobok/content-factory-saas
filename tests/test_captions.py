"""Tests for src/captions.py."""

from typing import Optional

import pytest

from src.captions import build_ass, build_captions_ass, format_ass_time
from src.models import StoryboardScene, VisualPrompts


# ── Helpers ───────────────────────────────────────────────────────────────────


def _scene(
    scene_id: str,
    duration_s: float = 3.0,
    on_screen_text: Optional[str] = None,
    voiceover_line: str = "Test line.",
) -> StoryboardScene:
    return StoryboardScene(
        scene=scene_id,
        clip_type="hard_cut",
        duration_s=duration_s,
        voiceover_line=voiceover_line,
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

    def test_alignment_is_center_screen(self):
        # Alignment=5 (middle-center), MarginV=0
        result = build_ass([_scene("01")])
        assert ",5," in result

    def test_margin_v_is_zero_for_center_alignment(self):
        result = build_ass([_scene("01")])
        # Last three comma-separated Style values are MarginL,MarginR,MarginV
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        assert fields[-2] == "0"  # MarginV

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

    def test_straight_double_quotes_stripped(self):
        result = build_ass([_scene("01", on_screen_text='"A clear room. A clear mind."')])
        assert "A CLEAR ROOM. A CLEAR MIND." in result
        assert '"' not in result.split("Dialogue")[1]

    def test_curly_double_quotes_stripped(self):
        result = build_ass([_scene("01", on_screen_text='“Housing crisis”')])
        assert "HOUSING CRISIS" in result
        assert "“" not in result
        assert "”" not in result

    def test_whitespace_trimmed_after_quote_strip(self):
        result = build_ass([_scene("01", on_screen_text='  "  spaced  "  ')])
        assert "SPACED" in result

    def test_no_quotes_text_unchanged_except_uppercase(self):
        result = build_ass([_scene("01", on_screen_text="PRICES UP")])
        assert "PRICES UP" in result


# ── Unit: build_captions_ass ──────────────────────────────────────────────────


class TestBuildCaptionsAss:
    def test_script_info_present(self):
        result = build_captions_ass([_scene("01")])
        assert "PlayResX: 1080" in result
        assert "PlayResY: 1920" in result

    def test_voicecaption_style_present(self):
        result = build_captions_ass([_scene("01")])
        assert "Style: VoiceCaption,Open Sans,42" in result

    def test_style_is_not_bold(self):
        result = build_captions_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        # fields[7] = Bold; 0 = not bold (existing Default style uses -1 for bold)
        assert fields[7] == "0"

    def test_alignment_is_bottom_center(self):
        result = build_captions_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        # fields[0]="Style: VoiceCaption", [1]=Fontname, [2]=Fontsize, [3-6]=colours,
        # [7]=Bold, [8]=Italic, [9]=Underline, [10]=StrikeOut, [11-12]=Scale,
        # [13]=Spacing, [14]=Angle, [15]=BorderStyle, [16]=Outline, [17]=Shadow,
        # [18]=Alignment, [19]=MarginL, [20]=MarginR, [21]=MarginV, [22]=Encoding
        assert fields[18] == "2"  # 2 = bottom-center

    def test_margin_v_is_80(self):
        result = build_captions_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        assert fields[-2] == "80"  # MarginV

    def test_voiceover_line_appears_verbatim(self):
        result = build_captions_ass([_scene("01", voiceover_line="Housing costs have tripled.")])
        assert "Housing costs have tripled." in result

    def test_text_is_not_uppercased(self):
        result = build_captions_ass([_scene("01", voiceover_line="lower case text")])
        assert "lower case text" in result
        assert "LOWER CASE TEXT" not in result

    def test_empty_voiceover_line_produces_no_dialogue(self):
        result = build_captions_ass([_scene("01", voiceover_line="")])
        assert "Dialogue" not in result

    def test_whitespace_only_voiceover_line_produces_no_dialogue(self):
        result = build_captions_ass([_scene("01", voiceover_line="   ")])
        assert "Dialogue" not in result

    def test_empty_scene_list_returns_header_only(self):
        result = build_captions_ass([])
        assert "[Script Info]" in result
        assert "Dialogue" not in result

    def test_result_ends_with_newline(self):
        assert build_captions_ass([_scene("01")]).endswith("\n")
        assert build_captions_ass([_scene("01", voiceover_line="text")]).endswith("\n")

    def test_first_scene_starts_at_zero(self):
        result = build_captions_ass([_scene("01", duration_s=3.0)])
        assert "0:00:00.00" in result

    def test_second_scene_starts_after_first(self):
        scenes = [
            _scene("01", duration_s=2.5),
            _scene("02", duration_s=3.0, voiceover_line="second line"),
        ]
        result = build_captions_ass(scenes)
        assert "0:00:02.50" in result

    def test_scene_end_time_matches_start_plus_duration(self):
        result = build_captions_ass([_scene("01", duration_s=4.0)])
        assert "0:00:00.00,0:00:04.00" in result

    def test_uses_voicecaption_style_in_dialogue(self):
        result = build_captions_ass([_scene("01")])
        dialogue_line = [l for l in result.splitlines() if l.startswith("Dialogue:")][0]
        assert "VoiceCaption" in dialogue_line

    def test_does_not_strip_quotes(self):
        result = build_captions_ass([_scene("01", voiceover_line='"quoted text"')])
        assert '"quoted text"' in result

    def test_mixed_empty_and_non_empty_scenes(self):
        scenes = [
            _scene("01", voiceover_line=""),
            _scene("02", voiceover_line="second scene text"),
        ]
        result = build_captions_ass(scenes)
        assert result.count("Dialogue") == 1
        assert "second scene text" in result
