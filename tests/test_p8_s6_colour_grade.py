"""Tests for P8-S6: colour grading presets and blur-fill for landscape stills."""

import logging

from src.ffmpeg_builder import (
    _COLOUR_GRADE_PRESETS,
    _apply_color_grade,
    _get_color_grade_filter,
    _render_image_scene,
    build_ffmpeg_script,
)
from src.models import (
    AssetManifest,
    ManifestEntry,
    Storyboard,
    StoryboardGlobal,
    StoryboardScene,
    StoryboardSummary,
    VisualPrompts,
)

RUN_ID = "test-run-p8s6"


def _scene(scene_id: str = "01", clip_type: str = "still_with_motion", duration_s: float = 3.0) -> StoryboardScene:
    """Build a minimal StoryboardScene."""
    return StoryboardScene(
        scene=scene_id,
        clip_type=clip_type,
        duration_s=duration_s,
        voiceover_line="Test line.",
        visual_prompts=VisualPrompts(
            primary_stk="housing", fallback_stk="real estate", ai_generate="prompt"
        ),
        sfx="silence",
        sfx_timing="scene_start",
    )


def _storyboard(scenes: list[StoryboardScene]) -> Storyboard:
    """Build a minimal Storyboard."""
    total = sum(s.duration_s for s in scenes)
    return Storyboard(**{
        "global": StoryboardGlobal(subtitle_style="bold", bg_music="lo-fi", visual_style="documentary"),
        "scenes": scenes,
        "summary": StoryboardSummary(total_scenes=len(scenes), total_duration_s=total, rhythm="steady"),
    })


def _entry(scene_id: str = "01", clip_type: str = "still_with_motion") -> ManifestEntry:
    """Build a minimal ManifestEntry with a file_key."""
    ext = "mp4" if clip_type == "hard_cut" else "jpeg"
    subdir = "video" if clip_type == "hard_cut" else "images"
    return ManifestEntry(
        scene_id=scene_id,
        clip_type=clip_type,
        primary_query="query",
        fallback_query="fallback",
        ai_generate_prompt="prompt",
        status="acquired",
        source="pexels",
        file_key=f"runs/{RUN_ID}/{subdir}/{scene_id}.{ext}",
    )


def _manifest(entries: list[ManifestEntry]) -> AssetManifest:
    """Build a minimal AssetManifest."""
    return AssetManifest(run_id=RUN_ID, entries=entries)


# ── _get_color_grade_filter ───────────────────────────────────────────────────


class TestGetColorGradeFilter:
    def test_neutral_returns_none(self):
        """neutral preset → no filter (output unchanged)."""
        assert _get_color_grade_filter("neutral") is None

    def test_vivid_returns_filter_string(self):
        result = _get_color_grade_filter("vivid")
        assert result == "eq=saturation=1.3:contrast=1.08"

    def test_warm_returns_filter_string(self):
        result = _get_color_grade_filter("warm")
        assert result is not None
        assert "colorchannelmixer" in result
        assert "eq=saturation" in result

    def test_cinematic_returns_filter_string(self):
        result = _get_color_grade_filter("cinematic")
        assert result is not None
        assert "curves" in result
        assert "eq=saturation" in result

    def test_muted_returns_filter_string(self):
        result = _get_color_grade_filter("muted")
        assert result is not None
        assert "eq=saturation=0.75" in result

    def test_all_non_neutral_presets_non_empty(self):
        """Every named preset other than neutral must produce a non-empty filter string."""
        for name in _COLOUR_GRADE_PRESETS:
            result = _get_color_grade_filter(name)
            assert result, f"preset '{name}' returned empty/None"

    def test_unknown_preset_returns_none(self, caplog):
        """Unknown preset falls back to neutral (no filter) and logs a warning."""
        with caplog.at_level(logging.WARNING, logger="src.ffmpeg_builder"):
            result = _get_color_grade_filter("neon_glitch")
        assert result is None
        assert "neon_glitch" in caplog.text

    def test_unknown_preset_warning_message(self, caplog):
        """Warning message mentions the preset name."""
        with caplog.at_level(logging.WARNING, logger="src.ffmpeg_builder"):
            _get_color_grade_filter("fake")
        assert "fake" in caplog.text


# ── _apply_color_grade ────────────────────────────────────────────────────────


class TestApplyColorGrade:
    def test_output_contains_filter_string(self):
        """The generated bash snippet embeds the filter string in a -vf argument."""
        snippet = _apply_color_grade("eq=saturation=1.3:contrast=1.08", "$WORK/video_only.mp4")
        assert "eq=saturation=1.3:contrast=1.08" in snippet

    def test_output_contains_video_source(self):
        """The snippet reads from the given video_source path."""
        snippet = _apply_color_grade("eq=saturation=1.3", "$WORK/video_captioned.mp4")
        assert "$WORK/video_captioned.mp4" in snippet

    def test_output_writes_graded_file(self):
        """The snippet writes to video_graded.mp4."""
        snippet = _apply_color_grade("eq=saturation=1.3", "$WORK/video_only.mp4")
        assert "video_graded.mp4" in snippet

    def test_output_is_valid_ffmpeg_command(self):
        """The snippet starts with 'ffmpeg' (or a comment then ffmpeg)."""
        snippet = _apply_color_grade("eq=saturation=1.3", "$WORK/video_only.mp4")
        assert "ffmpeg" in snippet


# ── build_ffmpeg_script — colour grade integration ────────────────────────────


class TestBuildFfmpegScriptColorGrade:
    def _build(self, preset: str = "neutral") -> str:
        scenes = [_scene("01", "hard_cut")]
        sb = _storyboard(scenes)
        entries = [_entry("01", "hard_cut")]
        mf = _manifest(entries)
        return build_ffmpeg_script(
            RUN_ID, sb, mf,
            color_grade_preset=preset,
            blur_fill_enabled=False,
        )

    def test_neutral_preset_no_grade_step(self):
        """neutral → no colour-grade ffmpeg call in the script."""
        script = self._build("neutral")
        assert "video_graded.mp4" not in script

    def test_vivid_preset_adds_grade_step(self):
        """vivid → colour-grade step is present and uses the correct filter."""
        script = self._build("vivid")
        assert "video_graded.mp4" in script
        assert "eq=saturation=1.3" in script

    def test_warm_preset_adds_grade_step(self):
        script = self._build("warm")
        assert "video_graded.mp4" in script
        assert "colorchannelmixer" in script

    def test_cinematic_preset_adds_grade_step(self):
        script = self._build("cinematic")
        assert "video_graded.mp4" in script
        assert "curves" in script

    def test_muted_preset_adds_grade_step(self):
        script = self._build("muted")
        assert "video_graded.mp4" in script
        assert "eq=saturation=0.75" in script

    def test_grade_step_before_audio(self):
        """The colour-grade step must appear before the audio assembly section."""
        script = self._build("vivid")
        grade_pos = script.index("video_graded.mp4")
        audio_pos = script.index("Audio assembly")
        assert grade_pos < audio_pos

    def test_audio_reads_from_graded_video(self):
        """When a grade is applied, audio assembly must read from video_graded.mp4, not video_only."""
        script = self._build("vivid")
        audio_section_start = script.index("Audio assembly")
        audio_section = script[audio_section_start:]
        assert "video_graded.mp4" in audio_section

    def test_unknown_preset_falls_back_to_neutral(self, caplog):
        """Unknown preset falls back to neutral — no grade step in the script."""
        with caplog.at_level(logging.WARNING, logger="src.ffmpeg_builder"):
            script = self._build("cyberpunk")
        assert "video_graded.mp4" not in script
        assert "cyberpunk" in caplog.text


# ── _render_image_scene — blur-fill ──────────────────────────────────────────


class TestRenderImageSceneBlurFill:
    _LOCAL = f"/tmp/{RUN_ID}/images/01.jpeg"
    _OUT = '"$WORK/scene_01.mp4"'

    def _image_scene(self, **kwargs) -> StoryboardScene:
        return _scene("01", "still_with_motion", **kwargs)

    def test_blur_fill_disabled_no_boxblur(self):
        """When blur_fill_enabled=False, the normal scale+crop+zoompan path is used."""
        scene = self._image_scene()
        result = _render_image_scene(scene, self._LOCAL, self._OUT, 1, blur_fill_enabled=False)
        assert "boxblur" not in result
        assert "ffprobe" not in result

    def test_blur_fill_disabled_contains_zoompan(self):
        """The normal path still uses zoompan animation."""
        scene = self._image_scene()
        result = _render_image_scene(scene, self._LOCAL, self._OUT, 1, blur_fill_enabled=False)
        assert "zoompan" in result

    def test_blur_fill_enabled_no_ffprobe(self):
        """When blur_fill_enabled=True, blur is applied directly — no runtime dimension probe needed."""
        scene = self._image_scene()
        result = _render_image_scene(scene, self._LOCAL, self._OUT, 1, blur_fill_enabled=True)
        assert "ffprobe" not in result

    def test_blur_fill_enabled_contains_boxblur(self):
        """When enabled, boxblur is present in the script."""
        scene = self._image_scene()
        result = _render_image_scene(scene, self._LOCAL, self._OUT, 1, blur_fill_enabled=True)
        assert "boxblur" in result

    def test_blur_fill_enabled_contains_overlay(self):
        """When enabled, the blur+portrait composite uses overlay."""
        scene = self._image_scene()
        result = _render_image_scene(scene, self._LOCAL, self._OUT, 1, blur_fill_enabled=True)
        assert "overlay" in result

    def test_blur_fill_enabled_contains_zoompan(self):
        """When enabled, zoompan is applied to the composite so the portrait is not static."""
        scene = self._image_scene()
        result = _render_image_scene(scene, self._LOCAL, self._OUT, 1, blur_fill_enabled=True)
        assert "boxblur" in result
        assert "zoompan" in result

    def test_blur_fill_overlay_centres_foreground(self):
        """The overlay expression centres the foreground element."""
        scene = self._image_scene()
        result = _render_image_scene(scene, self._LOCAL, self._OUT, 1, blur_fill_enabled=True)
        assert "overlay=(W-w)/2:(H-h)/2" in result

    def test_blur_fill_uses_correct_output_dimensions(self):
        """Blur-fill scale uses the caller-supplied output dimensions."""
        scene = self._image_scene()
        result = _render_image_scene(scene, self._LOCAL, self._OUT, 1, out_w=1920, out_h=1080, blur_fill_enabled=True)
        assert "scale=1920:1080" in result

    def test_default_blur_fill_enabled_is_false(self):
        """blur_fill_enabled defaults to False — normal scale+crop+zoompan path used."""
        scene = self._image_scene()
        result = _render_image_scene(scene, self._LOCAL, self._OUT, 1)
        assert "boxblur" not in result
        assert "zoompan" in result


# ── build_ffmpeg_script — blur-fill propagation ───────────────────────────────


class TestBuildFfmpegScriptBlurFill:
    def _build(self, clip_type: str = "still_with_motion", blur_fill_enabled: bool = True) -> str:
        scenes = [_scene("01", clip_type)]
        sb = _storyboard(scenes)
        entries = [_entry("01", clip_type)]
        mf = _manifest(entries)
        return build_ffmpeg_script(
            RUN_ID, sb, mf,
            color_grade_preset="neutral",
            blur_fill_enabled=blur_fill_enabled,
        )

    def test_image_scene_blur_fill_enabled_for_person_photo(self):
        """Blur-fill is applied when blur_fill_enabled=True AND the entry is a wikimedia_person photo."""
        scenes = [_scene("01", "still_with_motion")]
        sb = _storyboard(scenes)
        # Person photo entry — _render_scene gates blur on source="wikimedia_person"
        person_entry = ManifestEntry(
            scene_id="01",
            clip_type="still_with_motion",
            primary_query="query",
            fallback_query="fallback",
            ai_generate_prompt="prompt",
            status="acquired",
            source="wikimedia_person",
            file_key=f"runs/{RUN_ID}/images/01.jpeg",
        )
        mf = _manifest([person_entry])
        script = build_ffmpeg_script(RUN_ID, sb, mf, color_grade_preset="neutral", blur_fill_enabled=True)
        assert "boxblur" in script

    def test_image_scene_blur_fill_not_applied_for_pexels(self):
        """Blur-fill is NOT applied for regular Pexels images even when blur_fill_enabled=True."""
        script = self._build("still_with_motion", blur_fill_enabled=True)
        # _entry() defaults to source="pexels" — blur gate should prevent blur
        assert "boxblur" not in script
        assert "zoompan" in script

    def test_image_scene_blur_fill_disabled(self):
        """No blur-fill when disabled."""
        script = self._build("still_with_motion", blur_fill_enabled=False)
        assert "boxblur" not in script

    def test_video_scene_no_blur_fill_regardless(self):
        """Video (hard_cut) scenes never get blur-fill."""
        script = self._build("hard_cut", blur_fill_enabled=True)
        assert "boxblur" not in script
