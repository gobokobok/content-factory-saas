"""Tests for P9-S6 — Portrait/landscape format parameter (`--format` flag).

Covers:
  - parse_run_args: --format flag parsing (portrait, landscape, missing, invalid)
  - parse_produce_args: --format flag parsing (same)
  - parse_pick_command: --format flag parsing (same, including 4-tuple structure)
  - PipelineState.format_track: default value and valid assignment
  - RenderWorker resolution selection: portrait → 1080×1920, landscape → 1920×1080
  - StoryboardWorker prompt header: portrait → 9:16 vertical, landscape → 16:9 horizontal
"""


from cf_platform.core.schemas import PipelineState
from cf_platform.interfaces.telegram import (
    parse_pick_command,
    parse_produce_args,
    parse_run_args,
)

# ── parse_run_args --format flag ─────────────────────────────────────────────


class TestParseRunArgsFormat:
    """parse_run_args extracts --format flag in any position."""

    def test_default_landscape_when_no_flag(self):
        _, _, fmt = parse_run_args("american housing economics")
        assert fmt == "landscape"

    def test_landscape_flag(self):
        _, _, fmt = parse_run_args("american housing economics --format landscape")
        assert fmt == "landscape"

    def test_portrait_flag_explicit(self):
        _, _, fmt = parse_run_args("american housing economics --format portrait")
        assert fmt == "portrait"

    def test_flag_before_duration(self):
        niche, dur, fmt = parse_run_args("housing --format landscape --duration 45")
        assert niche == "housing"
        assert dur == 45
        assert fmt == "landscape"

    def test_flag_after_duration(self):
        niche, dur, fmt = parse_run_args("housing --duration 45 --format landscape")
        assert niche == "housing"
        assert dur == 45
        assert fmt == "landscape"

    def test_unknown_format_falls_back_to_landscape(self):
        _, _, fmt = parse_run_args("housing --format widescreen")
        assert fmt == "landscape"

    def test_case_insensitive(self):
        _, _, fmt = parse_run_args("housing --format Landscape")
        assert fmt == "landscape"


# ── parse_produce_args --format flag ─────────────────────────────────────────


class TestParseProduceArgsFormat:
    """parse_produce_args extracts --format flag in any position."""

    def test_default_landscape_when_no_flag(self):
        _, _, fmt = parse_produce_args("Why starter homes vanished")
        assert fmt == "landscape"

    def test_landscape_flag(self):
        _, _, fmt = parse_produce_args("Why starter homes vanished --format landscape")
        assert fmt == "landscape"

    def test_unknown_format_falls_back_to_landscape(self):
        _, _, fmt = parse_produce_args("Some title --format 4k")
        assert fmt == "landscape"

    def test_title_preserved_when_flag_present(self):
        title, _, _ = parse_produce_args("Why starter homes vanished --format landscape")
        assert title == "Why starter homes vanished"


# ── parse_pick_command --format flag ─────────────────────────────────────────


class TestParsePickCommandFormat:
    """parse_pick_command now returns a 4-tuple with format_track as fourth element."""

    def test_default_landscape(self):
        result = parse_pick_command("/pick abc-123 2")
        assert result is not None
        assert result[3] == "landscape"

    def test_landscape_flag(self):
        result = parse_pick_command("/pick abc-123 2 --format landscape")
        assert result is not None
        run_id, n, dur, fmt = result
        assert run_id == "abc-123"
        assert n == 2
        assert fmt == "landscape"

    def test_landscape_with_duration(self):
        result = parse_pick_command("/pick abc-123 1 --duration 90 --format landscape")
        assert result is not None
        _, _, dur, fmt = result
        assert dur == 90
        assert fmt == "landscape"

    def test_unknown_format_returns_landscape(self):
        result = parse_pick_command("/pick abc-123 2 --format ultra")
        assert result is not None
        assert result[3] == "landscape"

    def test_malformed_still_returns_none(self):
        assert parse_pick_command("/pick abc-123") is None
        assert parse_pick_command("/pick abc-123 6") is None


# ── PipelineState.format_track ───────────────────────────────────────────────


class TestPipelineStateFormatTrack:
    """PipelineState gains format_track with portrait default."""

    def test_default_is_portrait(self):
        state = PipelineState(run_id="r", user_id="u", inputs={}, artifacts={})
        assert state.format_track == "portrait"

    def test_landscape_accepted(self):
        state = PipelineState(run_id="r", user_id="u", inputs={}, artifacts={}, format_track="landscape")
        assert state.format_track == "landscape"

    def test_portrait_explicit(self):
        state = PipelineState(run_id="r", user_id="u", inputs={}, artifacts={}, format_track="portrait")
        assert state.format_track == "portrait"


# ── RenderWorker resolution selection ────────────────────────────────────────


class TestRenderWorkerResolution:
    """_build_render_script selects 1080×1920 for portrait, 1920×1080 for landscape."""

    def _extract_dimensions(self, script: str) -> tuple[int, int]:
        """Parse out_w and out_h from the ffmpeg scale filter in the render script."""
        import re
        match = re.search(r"scale=(\d+):(\d+)", script)
        assert match, f"No scale= filter found in script:\n{script[:500]}"
        return int(match.group(1)), int(match.group(2))

    def _make_minimal_storyboard(self):
        from src.models import Storyboard, StoryboardGlobal, StoryboardScene, StoryboardSummary, VisualPrompts
        scene = StoryboardScene(
            scene="01",
            segment_type="B-roll",
            voiceover_line="Test voiceover.",
            primary_stk="test footage",
            context_stk="context",
            concept_stk="concept",
            clip_type="hard_cut",
            duration_s=5.0,
            visual_prompts=VisualPrompts(
                primary_stk="test primary",
                fallback_stk="test fallback",
                ai_generate="",
            ),
        )
        return Storyboard(
            **{
                "global": StoryboardGlobal(title="Test", niche="test", subtitle_style="highlight", bg_music="none", visual_style="cinematic"),
                "scenes": [scene],
                "summary": StoryboardSummary(total_scenes=1, total_duration_s=5.0, rhythm="HC"),
            }
        )

    def _make_minimal_manifest(self, storyboard):
        from src.models import AssetManifest, ManifestEntry
        entry = ManifestEntry(
            scene_id="01",
            clip_type="still_with_motion",
            segment_type="B-roll",
            file_key="runs/test-run/images/01.jpg",
            source="pexels",
            qa_passed=True,
            qa_clip_score=None,
            fallback_used=False,
        )
        return AssetManifest(run_id="test-run", entries=[entry])

    def test_portrait_produces_1080x1920(self):
        from cf_platform.workers.render_worker import _build_render_script
        storyboard = self._make_minimal_storyboard()
        manifest = self._make_minimal_manifest(storyboard)
        script = _build_render_script(
            run_id="test-run",
            storyboard=storyboard,
            manifest=manifest,
            scene_words=None,
            color_grade_preset="neutral",
            blur_fill_enabled=True,
            format_track="portrait",
        )
        w, h = self._extract_dimensions(script)
        assert w == 1080
        assert h == 1920

    def test_landscape_produces_1920x1080(self):
        from cf_platform.workers.render_worker import _build_render_script
        storyboard = self._make_minimal_storyboard()
        manifest = self._make_minimal_manifest(storyboard)
        script = _build_render_script(
            run_id="test-run",
            storyboard=storyboard,
            manifest=manifest,
            scene_words=None,
            color_grade_preset="neutral",
            blur_fill_enabled=False,
            format_track="landscape",
        )
        w, h = self._extract_dimensions(script)
        assert w == 1920
        assert h == 1080


# ── StoryboardWorker prompt header ───────────────────────────────────────────


class TestStoryboardWorkerPromptHeader:
    """_GENERATE_SYSTEM_PROMPT substitution selects the correct format line."""

    def test_portrait_uses_9_16_vertical(self):
        from cf_platform.workers.storyboard_worker import (
            _FORMAT_LINE_PORTRAIT,
            _FORMAT_LINE_SENTINEL,
            _GENERATE_SYSTEM_PROMPT,
        )
        prompt = _GENERATE_SYSTEM_PROMPT.replace(_FORMAT_LINE_SENTINEL, _FORMAT_LINE_PORTRAIT)
        assert "9:16 vertical" in prompt
        assert "YouTube Short" in prompt

    def test_landscape_uses_16_9_horizontal(self):
        from cf_platform.workers.storyboard_worker import (
            _FORMAT_LINE_LANDSCAPE,
            _FORMAT_LINE_SENTINEL,
            _GENERATE_SYSTEM_PROMPT,
        )
        prompt = _GENERATE_SYSTEM_PROMPT.replace(_FORMAT_LINE_SENTINEL, _FORMAT_LINE_LANDSCAPE)
        assert "16:9 horizontal" in prompt
        assert "YouTube video" in prompt

    def test_sentinel_present_in_base_prompt(self):
        from cf_platform.workers.storyboard_worker import (
            _FORMAT_LINE_SENTINEL,
            _GENERATE_SYSTEM_PROMPT,
        )
        assert _FORMAT_LINE_SENTINEL in _GENERATE_SYSTEM_PROMPT
