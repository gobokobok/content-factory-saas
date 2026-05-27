"""Tests for src/captions.py."""

from typing import Optional

import pytest

from src.captions import _chunk_text, build_ass, build_captions_ass, format_ass_time
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
        assert "Style: Default,Open Sans,56" in result

    def test_default_style_is_white(self):
        result = build_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        assert "&H00FFFFFF" in style_line  # white in ASS BGR

    def test_default_style_outline_is_3(self):
        result = build_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        assert fields[16] == "3"  # Outline field

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
        assert "Style: VoiceCaption,Poppins,92" in result

    def test_voicecaption_bold_field_is_1(self):
        result = build_captions_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        # Bold=1 requests the Bold weight of Poppins from fontconfig
        assert fields[7] == "1"

    def test_alignment_is_bottom_center(self):
        result = build_captions_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        # fields[0]="Style: VoiceCaption", [1]=Fontname, [2]=Fontsize, [3-6]=colours,
        # [7]=Bold, [8]=Italic, [9]=Underline, [10]=StrikeOut, [11-12]=Scale,
        # [13]=Spacing, [14]=Angle, [15]=BorderStyle, [16]=Outline, [17]=Shadow,
        # [18]=Alignment, [19]=MarginL, [20]=MarginR, [21]=MarginV, [22]=Encoding
        assert fields[18] == "2"  # 2 = bottom-center

    def test_margin_v_is_250(self):
        result = build_captions_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        assert fields[-2] == "250"  # MarginV

    def test_voicecaption_outline_is_8(self):
        result = build_captions_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        assert fields[16] == "8"  # Outline field

    def test_voicecaption_shadow_is_1(self):
        result = build_captions_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        assert fields[17] == "1"  # Shadow field

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

    def test_long_voiceover_line_produces_multiple_dialogue_events(self):
        # 10 words → 2 chunks of 5 → 2 Dialogue events
        result = build_captions_ass([
            _scene("01", duration_s=6.0, voiceover_line="one two three four five six seven eight nine ten")
        ])
        assert result.count("Dialogue:") == 2

    def test_chunk_duration_is_even_split(self):
        # 10 words, 6.0s → 2 chunks of 3.0s each
        result = build_captions_ass([
            _scene("01", duration_s=6.0, voiceover_line="one two three four five six seven eight nine ten")
        ])
        assert "0:00:00.00,0:00:03.00" in result
        assert "0:00:03.00,0:00:06.00" in result


# ── Unit: _chunk_text ─────────────────────────────────────────────────────────


class TestChunkText:
    def test_exact_multiple_splits_evenly(self):
        assert _chunk_text("one two three four five six seven eight nine ten") == [
            "one two three four five",
            "six seven eight nine ten",
        ]

    def test_odd_word_count_last_chunk_is_smaller(self):
        # 7 words → [5, 2]
        result = _chunk_text("a b c d e f g")
        assert result == ["a b c d e", "f g"]

    def test_short_line_under_chunk_size_is_single_chunk(self):
        assert _chunk_text("hello world") == ["hello world"]

    def test_single_word_is_single_chunk(self):
        assert _chunk_text("word") == ["word"]

    def test_exactly_chunk_size_is_single_chunk(self):
        assert _chunk_text("a b c d e") == ["a b c d e"]

    def test_custom_chunk_size(self):
        assert _chunk_text("a b c d e f", chunk_size=3) == ["a b c", "d e f"]

    def test_empty_string_returns_empty_list(self):
        assert _chunk_text("") == []
