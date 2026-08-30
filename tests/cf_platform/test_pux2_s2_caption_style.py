"""Tests for P-UX2-S2: caption style presets (D082).

Covers:
- _build_captions_with_y_override in both "standard" and "punch" modes
- _captions_header selects the punch header, and only at 9:16
- caption_style flows RenderWorkerRequest -> state.inputs -> _build_render_script
"""

from cf_platform.workers.render_worker import _build_captions_with_y_override
from src.captions import _CAPTIONS_ASS_HEADER, _CAPTIONS_ASS_HEADER_PUNCH, _captions_header


class _Word:
    """Minimal stand-in for VoiceWordTimestamp."""

    def __init__(self, word: str, start_ms: int, end_ms: int) -> None:
        self.word = word
        self.start_ms = start_ms
        self.end_ms = end_ms


class _Scene:
    """Minimal stand-in for a StoryboardScene with no lower-third override."""

    render_options = None


def _words(*pairs: tuple[str, int, int]) -> list:
    return [_Word(w, s, e) for w, s, e in pairs]


_SIX = _words(
    ("one", 0, 400), ("two", 400, 800), ("three", 800, 1200),
    ("four", 1200, 1600), ("five", 1600, 2000), ("six", 2000, 2400),
)


def _dialogues(ass: str) -> list[str]:
    return [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]


def _text_of(line: str) -> str:
    # Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
    return line.split(",", 9)[9]


# ── Standard preset (unchanged behaviour) ─────────────────────────────────────


class TestStandardCaptions:
    def test_one_dialogue_event_per_word(self) -> None:
        ass = _build_captions_with_y_override([_SIX], [_Scene()], "TikTok")
        assert len(_dialogues(ass)) == 6

    def test_line_holds_the_whole_five_word_chunk(self) -> None:
        ass = _build_captions_with_y_override([_SIX], [_Scene()], "TikTok")
        first = _text_of(_dialogues(ass)[0])
        assert "two" in first and "five" in first
        # word 6 belongs to the next chunk
        assert "six" not in first

    def test_active_word_is_highlighted(self) -> None:
        ass = _build_captions_with_y_override([_SIX], [_Scene()], "TikTok")
        assert "{\\c&H0000FFFF&}" in _dialogues(ass)[0]

    def test_text_is_not_uppercased(self) -> None:
        ass = _build_captions_with_y_override([_SIX], [_Scene()], "TikTok")
        assert "one" in _text_of(_dialogues(ass)[0])
        assert "ONE" not in _text_of(_dialogues(ass)[0])


# ── Punch preset ──────────────────────────────────────────────────────────────


class TestPunchCaptions:
    def test_one_dialogue_event_per_word(self) -> None:
        ass = _build_captions_with_y_override(
            [_SIX], [_Scene()], "TikTok", caption_style="punch"
        )
        assert len(_dialogues(ass)) == 6

    def test_each_line_holds_exactly_one_word(self) -> None:
        ass = _build_captions_with_y_override(
            [_SIX], [_Scene()], "TikTok", caption_style="punch"
        )
        for line in _dialogues(ass):
            assert len(_text_of(line).split()) == 1

    def test_text_is_uppercased(self) -> None:
        ass = _build_captions_with_y_override(
            [_SIX], [_Scene()], "TikTok", caption_style="punch"
        )
        assert _text_of(_dialogues(ass)[0]) == "ONE"

    def test_no_highlight_tag(self) -> None:
        # With one word on screen the "active" word IS the line, so highlighting it
        # would turn every caption yellow.
        ass = _build_captions_with_y_override(
            [_SIX], [_Scene()], "TikTok", caption_style="punch"
        )
        assert "{\\c&H0000FFFF&}" not in ass

    def test_timing_is_gapless(self) -> None:
        ass = _build_captions_with_y_override(
            [_SIX], [_Scene()], "TikTok", caption_style="punch"
        )
        lines = _dialogues(ass)
        ends = [ln.split(",")[2] for ln in lines]
        starts = [ln.split(",")[1] for ln in lines]
        assert ends[:-1] == starts[1:]

    def test_uses_the_punch_header(self) -> None:
        ass = _build_captions_with_y_override(
            [_SIX], [_Scene()], "TikTok", caption_style="punch"
        )
        assert ass.startswith(_CAPTIONS_ASS_HEADER_PUNCH)

    def test_word_timestamps_are_not_mutated(self) -> None:
        # Uppercasing is display-only — word_ts.word still drives start_ms/end_ms.
        words = _words(("one", 0, 400))
        _build_captions_with_y_override([words], [_Scene()], "TikTok", caption_style="punch")
        assert words[0].word == "one"


# ── Header selection ──────────────────────────────────────────────────────────


class TestCaptionsHeader:
    def test_punch_header_at_portrait(self) -> None:
        assert _captions_header("TikTok", "9:16", "punch") is _CAPTIONS_ASS_HEADER_PUNCH

    def test_standard_header_unchanged(self) -> None:
        assert _captions_header("TikTok", "9:16", "standard") is _CAPTIONS_ASS_HEADER
        assert _captions_header("TikTok", "9:16") is _CAPTIONS_ASS_HEADER

    def test_punch_is_portrait_only(self) -> None:
        # Landscape keeps the legacy headers, matching how D070 is scoped.
        assert _captions_header("TikTok", "16:9", "punch") is not _CAPTIONS_ASS_HEADER_PUNCH

    def test_punch_font_is_larger_than_standard(self) -> None:
        assert "SemiBold,130," in _CAPTIONS_ASS_HEADER_PUNCH
        assert "SemiBold,80," in _CAPTIONS_ASS_HEADER


# ── Plumbing ──────────────────────────────────────────────────────────────────


class TestCaptionStylePlumbing:
    def test_render_request_defaults_to_standard(self) -> None:
        from cf_platform.interfaces.routes.workers import RenderWorkerRequest

        assert RenderWorkerRequest(run_id="r").caption_style == "standard"

    def test_render_request_accepts_punch(self) -> None:
        from cf_platform.interfaces.routes.workers import RenderWorkerRequest

        assert RenderWorkerRequest(run_id="r", caption_style="punch").caption_style == "punch"

    def test_video_settings_carries_caption_style(self) -> None:
        from src.models import VideoSettings

        assert VideoSettings().caption_style == "standard"
        assert VideoSettings(caption_style="punch").caption_style == "punch"

    def test_build_render_script_accepts_caption_style(self) -> None:
        import inspect

        from cf_platform.workers.render_worker import _build_render_script

        assert "caption_style" in inspect.signature(_build_render_script).parameters
