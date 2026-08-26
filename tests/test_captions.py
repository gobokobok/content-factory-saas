"""Tests for src/captions.py."""



from src.captions import (
    _chunk_text,
    build_ass,
    build_captions_ass,
    build_word_synced_captions_ass,
    format_ass_time,
)
from src.models import StoryboardScene, VisualPrompts, WordTimestamp

# ── Helpers ───────────────────────────────────────────────────────────────────


def _scene(
    scene_id: str,
    duration_s: float = 3.0,
    on_screen_text: str | None = None,
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
        assert "Style: VoiceCaption,Titillium Web SemiBold,145" in result

    def test_voicecaption_bold_field_is_0(self):
        result = build_captions_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        # Titillium Web SemiBold is bundled as a distinct static weight — Bold
        # stays 0 even for the (heavier) TikTok style; see D070.
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

    def test_margin_v_is_350(self):
        result = build_captions_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        assert fields[-2] == "350"  # MarginV

    def test_voicecaption_outline_is_6(self):
        result = build_captions_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        assert fields[16] == "6"  # Outline field

    def test_voicecaption_shadow_is_1(self):
        result = build_captions_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        assert fields[17] == "1"  # Shadow field

    def test_voicecaption_margins_are_at_least_10_percent_of_play_res_x(self):
        # PlayResX is 1080 — MarginL/MarginR must each be >=10% (108px) so
        # captions never bleed off-screen at either edge.
        result = build_captions_ass([_scene("01")])
        style_line = [l for l in result.splitlines() if l.startswith("Style:")][0]
        fields = style_line.split(",")
        margin_l, margin_r = int(fields[19]), int(fields[20])
        assert margin_l >= 108
        assert margin_r >= 108

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


# ── Unit: build_word_synced_captions_ass ──────────────────────────────────────


def _word(word: str, start_ms: int, end_ms: int, confidence: float = 0.99) -> WordTimestamp:
    return WordTimestamp(word=word, start_ms=start_ms, end_ms=end_ms, confidence=confidence)


class TestBuildWordSyncedCaptionsAss:
    """build_word_synced_captions_ass takes list[list[WordTimestamp]] — one list per scene."""

    def test_empty_scene_list_returns_header_only(self):
        result = build_word_synced_captions_ass([])
        assert "[Script Info]" in result
        assert "Dialogue" not in result

    def test_scene_with_no_words_produces_no_dialogue(self):
        result = build_word_synced_captions_ass([[]])
        assert "Dialogue" not in result

    def test_uses_voicecaption_style(self):
        result = build_word_synced_captions_ass([[_word("hello", 0, 500)]])
        assert "Style: VoiceCaption" in result

    def test_single_word_produces_one_dialogue(self):
        result = build_word_synced_captions_ass([[_word("hello", 0, 500)]])
        assert result.count("Dialogue:") == 1

    def test_timing_derived_from_word_ms(self):
        # word at 1500ms → 2000ms → 0:00:01.50 → 0:00:02.00
        result = build_word_synced_captions_ass([[_word("rents", 1500, 2000)]])
        assert "0:00:01.50" in result
        assert "0:00:02.00" in result

    def test_active_word_highlighted_in_yellow(self):
        result = build_word_synced_captions_ass([[_word("crisis", 0, 600)]])
        assert "{\\c&H0000FFFF&}crisis" in result

    def test_color_reset_to_white_after_active_word(self):
        result = build_word_synced_captions_ass([[_word("crisis", 0, 600)]])
        assert "{\\c&H00FFFFFF&}" in result

    def test_5_word_chunk_produces_5_dialogue_events(self):
        words = [
            _word("one", 0, 200),
            _word("two", 300, 500),
            _word("three", 600, 800),
            _word("four", 900, 1100),
            _word("five", 1200, 1400),
        ]
        result = build_word_synced_captions_ass([words])
        assert result.count("Dialogue:") == 5

    def test_6th_word_within_same_scene_starts_new_chunk(self):
        words = [
            _word("one", 0, 200),
            _word("two", 300, 500),
            _word("three", 600, 800),
            _word("four", 900, 1100),
            _word("five", 1200, 1400),
            _word("six", 1500, 1700),
        ]
        result = build_word_synced_captions_ass([words])
        # 6 words in one scene → 2 chunks: [one..five] and [six]
        lines = [l for l in result.splitlines() if l.startswith("Dialogue:") and "six" in l]
        assert len(lines) == 1
        assert "one" not in lines[0]  # six is in its own chunk

    def test_10_words_in_one_scene_produce_10_dialogue_events(self):
        words = [_word(str(i), i * 200, i * 200 + 150) for i in range(10)]
        result = build_word_synced_captions_ass([words])
        assert result.count("Dialogue:") == 10

    def test_words_from_different_scenes_never_share_a_chunk(self):
        # Scene 1: 2 words, Scene 2: 3 words.
        # Without scene grouping they'd merge into one 5-word chunk.
        scene1 = [_word("one", 0, 200), _word("interruption", 250, 780)]
        scene2 = [_word("23", 900, 1100), _word("minutes", 1200, 1500), _word("focus", 1600, 2000)]
        result = build_word_synced_captions_ass([scene1, scene2])
        # Event where "one" is highlighted must NOT contain "23"
        one_events = [
            l for l in result.splitlines()
            if "Dialogue:" in l and "{\\c&H0000FFFF&}one" in l
        ]
        assert len(one_events) == 1
        assert "23" not in one_events[0]

    def test_two_scenes_produce_independent_event_sets(self):
        scene1 = [_word("housing", 0, 500), _word("costs", 600, 900)]
        scene2 = [_word("tripled", 1000, 1500)]
        result = build_word_synced_captions_ass([scene1, scene2])
        # 2 events from scene1 + 1 event from scene2 = 3 total
        assert result.count("Dialogue:") == 3

    def test_first_word_in_chunk_has_no_white_prefix(self):
        words = [_word("housing", 0, 500), _word("costs", 600, 900)]
        result = build_word_synced_captions_ass([words])
        first_event = [l for l in result.splitlines() if "housing" in l and "Dialogue:" in l][0]
        # Dialogue format has two ",," separators; last split segment is the text
        text_part = first_event.split(",,")[-1]
        assert text_part.startswith("{\\c&H0000FFFF&}housing")

    def test_surrounding_words_appear_without_color_tags_before_active(self):
        words = [_word("one", 0, 200), _word("two", 300, 500), _word("three", 600, 800)]
        result = build_word_synced_captions_ass([words])
        two_event = [l for l in result.splitlines() if "Dialogue:" in l][1]
        text_part = two_event.split(",,")[-1]
        assert text_part.startswith("one {\\c&H0000FFFF&}two")

    def test_word_event_extends_to_next_word_start_not_own_end(self):
        # "one" ends at 200ms but "two" starts at 300ms — 100ms gap.
        # Event for "one" must extend to 300ms so caption stays visible.
        words = [_word("one", 0, 200), _word("two", 300, 500)]
        result = build_word_synced_captions_ass([words])
        one_event = [l for l in result.splitlines() if "{\\c&H0000FFFF&}one" in l][0]
        # Dialogue: 0,START,END,...  — END is field index 2
        end_field = one_event.split(",")[2]
        assert end_field == "0:00:00.30"  # two's start_ms, not one's end_ms

    def test_last_word_in_chunk_ends_at_next_chunk_start(self):
        # 6-word scene → two chunks: [w0..w4] and [w5].
        # Last word of first chunk (w4, end=1400ms) should extend to w5's start (1500ms).
        words = [
            _word("one", 0, 200), _word("two", 300, 500), _word("three", 600, 800),
            _word("four", 900, 1100), _word("five", 1200, 1400), _word("six", 1500, 1700),
        ]
        result = build_word_synced_captions_ass([words])
        five_events = [l for l in result.splitlines() if "{\\c&H0000FFFF&}five" in l]
        assert len(five_events) == 1
        end_field = five_events[0].split(",")[2]
        assert end_field == "0:00:01.50"  # six's start_ms, not five's end_ms

    def test_last_word_of_final_chunk_ends_at_own_end_ms(self):
        # "three" is the last word of the only chunk — must end at its own end_ms.
        words = [_word("one", 0, 200), _word("two", 300, 500), _word("three", 600, 800)]
        result = build_word_synced_captions_ass([words])
        three_events = [l for l in result.splitlines() if "{\\c&H0000FFFF&}three" in l]
        end_field = three_events[0].split(",")[2]
        assert end_field == "0:00:00.80"  # three's own end_ms

    def test_result_ends_with_newline(self):
        result = build_word_synced_captions_ass([[_word("x", 0, 100)]])
        assert result.endswith("\n")

    def test_each_event_uses_voicecaption_style(self):
        words = [_word("a", 0, 200), _word("b", 300, 500)]
        result = build_word_synced_captions_ass([words])
        dialogue_lines = [l for l in result.splitlines() if l.startswith("Dialogue:")]
        assert all("VoiceCaption" in l for l in dialogue_lines)


# ── Unit: subtitle style variants ────────────────────────────────────────────


class TestSubtitleStyleVariants:
    """Verify TikTok vs Classic ASS header differences."""

    def test_tiktok_style_has_145pt_font(self):
        """Default TikTok style uses 145pt Titillium Web SemiBold."""
        result = build_captions_ass([_scene("01")])
        assert "Titillium Web SemiBold,145" in result

    def test_tiktok_style_is_not_bold(self):
        """TikTok style has Bold=0 — SemiBold weight comes from the bundled font, not the Bold flag."""
        result = build_captions_ass([_scene("01")])
        style_line = next(l for l in result.splitlines() if l.startswith("Style: VoiceCaption"))
        fields = style_line.split(",")
        assert fields[7] == "0"  # Bold field

    def test_classic_style_has_100pt_font(self):
        """Classic style uses 100pt Titillium Web SemiBold (smaller than TikTok's 145pt)."""
        result = build_captions_ass([_scene("01")], subtitle_style="Classic")
        assert "Titillium Web SemiBold,100" in result

    def test_classic_style_not_bold(self):
        """Classic style has Bold=0."""
        result = build_captions_ass([_scene("01")], subtitle_style="Classic")
        style_line = next(l for l in result.splitlines() if l.startswith("Style: VoiceCaption"))
        fields = style_line.split(",")
        assert fields[7] == "0"  # Bold field

    def test_classic_style_smaller_outline(self):
        """Classic style has Outline=2 (vs TikTok's 6)."""
        result = build_captions_ass([_scene("01")], subtitle_style="Classic")
        style_line = next(l for l in result.splitlines() if l.startswith("Style: VoiceCaption"))
        fields = style_line.split(",")
        assert fields[16] == "2"  # Outline field

    def test_classic_style_smaller_marginv(self):
        """Classic style has MarginV=180 (vs TikTok's 350)."""
        result = build_captions_ass([_scene("01")], subtitle_style="Classic")
        style_line = next(l for l in result.splitlines() if l.startswith("Style: VoiceCaption"))
        fields = style_line.split(",")
        assert fields[21] == "180"  # MarginV field

    def test_classic_style_margins_are_at_least_10_percent_of_play_res_x(self):
        result = build_captions_ass([_scene("01")], subtitle_style="Classic")
        style_line = next(l for l in result.splitlines() if l.startswith("Style: VoiceCaption"))
        fields = style_line.split(",")
        margin_l, margin_r = int(fields[19]), int(fields[20])
        assert margin_l >= 108
        assert margin_r >= 108

    def test_word_synced_tiktok_uses_145pt(self):
        """Word-synced captions with TikTok style use 145pt header."""
        words = [_word("test", 0, 500)]
        result = build_word_synced_captions_ass([words], subtitle_style="TikTok")
        assert "Titillium Web SemiBold,145" in result

    def test_word_synced_classic_uses_100pt(self):
        """Word-synced captions with Classic style use 100pt header."""
        words = [_word("test", 0, 500)]
        result = build_word_synced_captions_ass([words], subtitle_style="Classic")
        assert "Titillium Web SemiBold,100" in result

    def test_unknown_style_falls_back_to_tiktok(self):
        """An unrecognised style name falls back to TikTok header."""
        result = build_captions_ass([_scene("01")], subtitle_style="Unknown")
        assert "Titillium Web SemiBold,145" in result
