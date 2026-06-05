"""Tests for src/ffmpeg_builder.py and src/routes/ffmpeg_script.py."""

from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.exceptions import FFmpegBuildError, StorageError
from src.ffmpeg_builder import (
    _local_path,
    _parse_sfx_delay_ms,
    _zoompan_filter,
    assign_words_to_scenes,
    build_ffmpeg_script,
    compute_scene_durations_from_alignment,
    get_audio_duration,
    redistribute_scene_durations,
)
from src.main import app
from src.models import (
    AssetManifest,
    AudioSettings,
    ManifestEntry,
    Storyboard,
    StoryboardGlobal,
    StoryboardScene,
    StoryboardSummary,
    VideoSettings,
    VisualPrompts,
    WordTimestamp,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "acct",
    "R2_ACCESS_KEY_ID": "key",
    "R2_SECRET_ACCESS_KEY": "secret",
    "R2_BUCKET_NAME": "bucket",
    "ANTHROPIC_API_KEY": "ant",
    "PEXELS_API_KEY": "pex",
    "REPLICATE_API_TOKEN": "rep",
    "FREESOUND_API_KEY": "fs",
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret-key",
}

RUN_ID = "2026-05-22_test-run"


def _settings() -> Settings:
    return Settings(**VALID_ENV)


def _scene(
    scene_id: str,
    clip_type: str = "hard_cut",
    duration_s: float = 3.0,
    sfx: str = "silence",
    sfx_timing: str = "scene_start",
    motion_effect: Optional[str] = None,
) -> StoryboardScene:
    return StoryboardScene(
        scene=scene_id,
        clip_type=clip_type,
        duration_s=duration_s,
        voiceover_line="Test voiceover line.",
        visual_prompts=VisualPrompts(
            primary_stk="housing market", fallback_stk="real estate", ai_generate="prompt"
        ),
        motion_effect=motion_effect,
        sfx=sfx,
        sfx_timing=sfx_timing,
    )


def _storyboard(scenes: list[StoryboardScene]) -> Storyboard:
    total = sum(s.duration_s for s in scenes)
    return Storyboard(**{
        "global": StoryboardGlobal(
            subtitle_style="bold", bg_music="lo-fi", visual_style="documentary"
        ),
        "scenes": scenes,
        "summary": StoryboardSummary(
            total_scenes=len(scenes), total_duration_s=total, rhythm="steady"
        ),
    })


def _entry(
    scene_id: str,
    clip_type: str = "hard_cut",
    file_key: Optional[str] = None,
    status: str = "acquired",
) -> ManifestEntry:
    if file_key is None:
        ext = "mp4" if clip_type == "hard_cut" else "jpeg"
        file_key = f"runs/{RUN_ID}/{'video' if clip_type == 'hard_cut' else 'images'}/{scene_id}.{ext}"
    return ManifestEntry(
        scene_id=scene_id,
        clip_type=clip_type,
        primary_query="query",
        fallback_query="fallback",
        ai_generate_prompt="prompt",
        status=status,
        source="pexels",
        file_key=file_key,
    )


def _manifest(entries: list[ManifestEntry]) -> AssetManifest:
    return AssetManifest(run_id=RUN_ID, entries=entries)


def _simple_storyboard_and_manifest() -> tuple[Storyboard, AssetManifest]:
    """One hard_cut scene with silence SFX — minimal valid pair."""
    scenes = [_scene("01", "hard_cut", 3.0)]
    sb = _storyboard(scenes)
    entries = [_entry("01", "hard_cut")]
    mf = _manifest(entries)
    return sb, mf


# ── Unit: _local_path ─────────────────────────────────────────────────────────


class TestLocalPath:
    def test_strips_run_prefix(self):
        key = f"runs/{RUN_ID}/video/01.mp4"
        assert _local_path(RUN_ID, key) == f"/tmp/{RUN_ID}/video/01.mp4"

    def test_images_path(self):
        key = f"runs/{RUN_ID}/images/02.jpeg"
        assert _local_path(RUN_ID, key) == f"/tmp/{RUN_ID}/images/02.jpeg"

    def test_webp_path(self):
        key = f"runs/{RUN_ID}/images/03.webp"
        assert _local_path(RUN_ID, key) == f"/tmp/{RUN_ID}/images/03.webp"

    def test_key_without_expected_prefix_still_works(self):
        # Defensive: if file_key doesn't start with runs/{run_id}/, use it as-is
        result = _local_path(RUN_ID, "some/other/path.mp4")
        assert result == f"/tmp/{RUN_ID}/some/other/path.mp4"


# ── Unit: _parse_sfx_delay_ms ─────────────────────────────────────────────────


class TestParseSfxDelayMs:
    def test_scene_start(self):
        # Offset 5.0s, timing = scene_start → 5000ms
        assert _parse_sfx_delay_ms("scene_start", 3.0, 5.0) == 5000

    def test_mid(self):
        # Offset 4.0s, duration 2.0s, timing = mid → (4.0 + 1.0) * 1000 = 5000
        assert _parse_sfx_delay_ms("mid", 2.0, 4.0) == 5000

    def test_end(self):
        # Offset 0.0s, duration 3.0s, timing = end → (0.0 + 2.5) * 1000 = 2500
        assert _parse_sfx_delay_ms("end", 3.0, 0.0) == 2500

    def test_seconds_format(self):
        # Offset 3.0s, timing = "1.5s" → (3.0 + 1.5) * 1000 = 4500
        assert _parse_sfx_delay_ms("1.5s", 3.0, 3.0) == 4500

    def test_zero_offset(self):
        assert _parse_sfx_delay_ms("scene_start", 4.0, 0.0) == 0

    def test_unknown_timing_defaults_to_scene_start(self):
        assert _parse_sfx_delay_ms("unknown_value", 3.0, 2.0) == 2000

    def test_invalid_seconds_format_defaults_to_scene_start(self):
        assert _parse_sfx_delay_ms("xs", 3.0, 1.5) == 1500

    def test_result_is_never_negative(self):
        assert _parse_sfx_delay_ms("scene_start", 3.0, 0.0) >= 0


# ── Unit: _zoompan_filter ─────────────────────────────────────────────────────


class TestZoompanFilter:
    def test_still_with_motion_gentle_zoom(self):
        result = _zoompan_filter("still_with_motion", None, 75)
        assert "1+0.05*on/75" in result
        assert "d=75" in result
        assert "s=1080x1920" in result
        # fps= is intentionally NOT in the zoompan string — it is a separate fps filter
        # inserted after zoompan in _render_image_scene to reset PTS and avoid the
        # "MB rate > level limit" libx264 error caused by looped-image time bases.
        assert "fps=" not in result

    def test_animated_zoom_in(self):
        result = _zoompan_filter("animated", "zoom_in", 100)
        assert "1+0.1*on/100" in result

    def test_animated_zoom_out(self):
        result = _zoompan_filter("animated", "zoom_out", 100)
        assert "1.1-0.1*on/100" in result

    def test_animated_pan_left(self):
        result = _zoompan_filter("animated", "pan_left", 100)
        assert "z='1.1'" in result
        assert "(iw-iw/zoom)*on/100" in result

    def test_animated_pan_right(self):
        result = _zoompan_filter("animated", "pan_right", 100)
        assert "z='1.1'" in result
        assert "(iw-iw/zoom)*(1-on/100)" in result

    def test_animated_none_motion_defaults_to_zoom_in(self):
        result = _zoompan_filter("animated", None, 100)
        assert "1+0.1*on/100" in result

    def test_animated_unknown_effect_falls_back_to_zoom_in(self):
        result = _zoompan_filter("animated", "spin_around", 100)
        assert "1+0.1*on/100" in result

    def test_still_with_motion_always_ignores_motion_effect(self):
        # still_with_motion is always gentle zoom regardless of motion_effect
        result_no_effect = _zoompan_filter("still_with_motion", None, 100)
        result_with_effect = _zoompan_filter("still_with_motion", "zoom_in", 100)
        assert result_no_effect == result_with_effect

    def test_frames_in_zoompan_suffix(self):
        result = _zoompan_filter("still_with_motion", None, 42)
        assert ":d=42:" in result

    def test_output_size_in_suffix(self):
        result = _zoompan_filter("animated", "zoom_in", 50)
        assert "1080x1920" in result


# ── Unit: build_ffmpeg_script ─────────────────────────────────────────────────


class TestBuildFfmpegScript:
    def test_starts_with_shebang(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert script.startswith("#!/bin/bash")

    def test_header_contains_run_id(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert RUN_ID in script

    def test_header_contains_scene_count(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "scenes:          1" in script

    def test_header_contains_total_duration(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "total_duration:  3.0s" in script

    def test_header_contains_generated_at(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "generated_at:" in script

    def test_base_path_uses_run_id(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert f'BASE="/tmp/{RUN_ID}"' in script

    def test_hard_cut_scene_uses_video_input(self):
        scenes = [_scene("01", "hard_cut", 4.0)]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "video/01.mp4" in script
        assert "-loop 1" not in script

    def test_hard_cut_scene_applies_portrait_scale_crop(self):
        scenes = [_scene("01", "hard_cut", 4.0)]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "scale=1080:1920" in script
        assert "crop=1080:1920" in script
        assert "setsar=1:1" in script

    def test_hard_cut_scene_sets_duration(self):
        scenes = [_scene("01", "hard_cut", 4.5)]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "-t 4.5" in script

    def test_still_with_motion_uses_loop_flag(self):
        scenes = [_scene("02", "still_with_motion", 3.0)]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("02", "still_with_motion")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "-loop 1" in script

    def test_still_with_motion_uses_zoompan(self):
        scenes = [_scene("02", "still_with_motion", 4.0)]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("02", "still_with_motion")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "zoompan" in script
        assert "0.05" in script  # gentle zoom factor
        assert "setsar=1:1" in script

    def test_animated_pan_left_uses_pan_expression(self):
        scenes = [_scene("03", "animated", 3.0, motion_effect="pan_left")]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("03", "animated")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "(iw-iw/zoom)*on/" in script

    def test_still_with_motion_prescales_to_output_dimensions(self):
        """Pre-scale must match s= output size so the centering formula iw/2-(iw/zoom/2) is correct."""
        scenes = [_scene("02", "still_with_motion", 4.0)]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("02", "still_with_motion")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "scale=1080:1920" in script
        assert "crop=1080:1920" in script
        # Must NOT use the old 2× scale which broke centering
        assert "scale=2160:3840" not in script
        assert "crop=2160:3840" not in script

    def test_animated_prescales_to_output_dimensions(self):
        """Same pre-scale requirement applies to all animated clip types."""
        scenes = [_scene("03", "animated", 3.0, motion_effect="pan_left")]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("03", "animated")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "scale=1080:1920" in script
        assert "crop=1080:1920" in script
        assert "scale=2160:3840" not in script

    def test_image_scene_vf_chain_order_is_scale_zoompan_fps_setsar(self):
        """vf filter chain must be: scale+crop → zoompan → fps=25 → setsar=1:1.

        The fps filter between zoompan and setsar resets PTS from the looped-image
        microsecond time base to a sane 1/25 base, preventing the libx264
        'MB rate > level limit' error (exit code 187).
        """
        scenes = [_scene("02", "still_with_motion", 3.0)]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("02", "still_with_motion")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        # Find the vf= argument for the image scene
        vf_start = script.index("scale=1080:1920:force_original_aspect_ratio=increase")
        vf_chunk = script[vf_start:vf_start + 250]
        assert vf_chunk.index("scale=") < vf_chunk.index("zoompan=")
        assert vf_chunk.index("zoompan=") < vf_chunk.index("fps=25")
        assert vf_chunk.index("fps=25") < vf_chunk.index("setsar=1:1")

    def test_animated_zoom_out_uses_decreasing_expression(self):
        scenes = [_scene("03", "animated", 3.0, motion_effect="zoom_out")]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("03", "animated")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "1.1-0.1*on/" in script

    def test_silence_sfx_not_in_audio_inputs(self):
        scenes = [_scene("01", "hard_cut", 3.0, sfx="silence")]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "sfx/silence.mp3" not in script
        assert "adelay" not in script

    def test_non_silence_sfx_appears_in_audio_section(self):
        scenes = [_scene("01", "hard_cut", 3.0, sfx="soft_whoosh", sfx_timing="scene_start")]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "sfx/soft_whoosh.mp3" in script
        assert "adelay=0|0" in script  # first scene offset = 0ms

    def test_sfx_delay_accumulates_across_scenes(self):
        scenes = [
            _scene("01", "hard_cut", 5.0, sfx="silence"),
            _scene("02", "hard_cut", 3.0, sfx="impact", sfx_timing="scene_start"),
        ]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut"), _entry("02", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        # Scene 02 starts at 5.0s → 5000ms delay
        assert "adelay=5000|5000" in script

    def test_multiple_sfx_get_separate_inputs(self):
        scenes = [
            _scene("01", "hard_cut", 3.0, sfx="whoosh", sfx_timing="scene_start"),
            _scene("02", "hard_cut", 3.0, sfx="impact", sfx_timing="scene_start"),
        ]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut"), _entry("02", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "sfx/whoosh.mp3" in script
        assert "sfx/impact.mp3" in script
        assert "sfx0" in script
        assert "sfx1" in script

    def test_amix_input_count_is_dynamic(self):
        scenes = [
            _scene("01", "hard_cut", 3.0, sfx="whoosh"),
            _scene("02", "hard_cut", 3.0, sfx="silence"),
        ]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut"), _entry("02", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        # amix count is driven by bash variable, not hardcoded
        assert "amix=inputs=${_n_audio}" in script
        assert "_n_audio=2" in script  # initialised to vo + music

    def test_no_sfx_amix_is_dynamic(self):
        scenes = [_scene("01", "hard_cut", 3.0, sfx="silence")]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "amix=inputs=${_n_audio}" in script
        assert "_n_audio=2" in script

    def test_sfx_wrapped_in_file_existence_check(self):
        scenes = [_scene("01", "hard_cut", 3.0, sfx="whoosh", sfx_timing="scene_start")]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert 'if [ -f "$BASE/sfx/whoosh.mp3" ]; then' in script

    def test_sfx_inputs_use_bash_array(self):
        scenes = [_scene("01", "hard_cut", 3.0, sfx="whoosh", sfx_timing="scene_start")]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "_sfx_inputs=()" in script
        assert '"${_sfx_inputs[@]}"' in script

    def test_debug_section_present_in_script(self):
        scenes = [_scene("01", "hard_cut", 3.0)]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "=== PRE-FLIGHT CHECK ===" in script
        assert "ffmpeg -version" in script
        assert 'test -f "$VO"' in script
        assert 'test -f "$MUSIC"' in script
        assert 'ls "$BASE/video/"' in script
        assert 'ls "$BASE/images/"' in script

    def test_debug_section_before_scene_section(self):
        scenes = [_scene("01", "hard_cut", 3.0)]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert script.index("PRE-FLIGHT") < script.index("Per-scene processing")

    def test_concat_list_contains_all_scenes(self):
        scenes = [
            _scene("01", "hard_cut", 3.0),
            _scene("02", "still_with_motion", 4.0),
            _scene("03", "animated", 3.5),
        ]
        sb = _storyboard(scenes)
        mf = _manifest([
            _entry("01", "hard_cut"),
            _entry("02", "still_with_motion"),
            _entry("03", "animated"),
        ])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "scene_01.mp4" in script
        assert "scene_02.mp4" in script
        assert "scene_03.mp4" in script

    def test_output_resolution_is_portrait(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "1080" in script
        assert "1920" in script

    def test_voiceover_check_aborts_on_missing_file(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "voiceover" in script
        assert "exit 1" in script

    def test_music_silence_fallback_uses_anullsrc(self):
        """No-music path sets MUSIC_ARGS to anullsrc — no fragile silence file generated."""
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "anullsrc" in script
        assert "MUSIC_ARGS" in script
        assert "${MUSIC_ARGS[@]}" in script
        assert "_silence.mp3" not in script

    def test_raises_ffmpeg_build_error_for_missing_file_key(self):
        scenes = [_scene("01", "hard_cut", 3.0)]
        sb = _storyboard(scenes)
        entry = ManifestEntry(
            scene_id="01", clip_type="hard_cut",
            primary_query="q", fallback_query="f", ai_generate_prompt="p",
            status="pending", file_key=None,
        )
        mf = _manifest([entry])
        with pytest.raises(FFmpegBuildError, match="01"):
            build_ffmpeg_script(RUN_ID, sb, mf)

    def test_raises_ffmpeg_build_error_for_missing_manifest_entry(self):
        scenes = [_scene("01", "hard_cut", 3.0), _scene("02", "hard_cut", 3.0)]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut")])  # scene 02 missing
        with pytest.raises(FFmpegBuildError, match="02"):
            build_ffmpeg_script(RUN_ID, sb, mf)

    def test_error_message_includes_scene_id(self):
        scenes = [_scene("03a", "still_with_motion", 4.0)]
        sb = _storyboard(scenes)
        entry = ManifestEntry(
            scene_id="03a", clip_type="still_with_motion",
            primary_query="q", fallback_query="f", ai_generate_prompt="p",
            status="pending", file_key=None,
        )
        mf = _manifest([entry])
        with pytest.raises(FFmpegBuildError) as exc_info:
            build_ffmpeg_script(RUN_ID, sb, mf)
        assert "03a" in str(exc_info.value)

    def test_audio_inputs_reset_pts_to_prevent_start_time_offset(self):
        """VO and music must have asetpts=PTS-STARTPTS to strip non-zero container start_time.

        MP3s cut from longer tracks often encode a non-zero start_time in their container
        metadata. Without PTS reset, FFmpeg pads silence from t=0 to start_time before
        playing audio, causing music/VO to appear delayed. Regression guard for smoke-test
        bug observed 2026-05-23.
        """
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "[1:a]asetpts=PTS-STARTPTS,volume=1.0[vo]" in script
        assert "[2:a]asetpts=PTS-STARTPTS,volume=0.060[music]" in script

    def test_default_audio_applies_ducking_to_fifteen_percent(self):
        """Default AudioSettings: 15% volume × 0.4 ducking factor = 0.060 effective."""
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "volume=0.060[music]" in script

    def test_voiceover_full_volume(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "volume=1.0" in script

    def test_final_output_path(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert f"/tmp/{RUN_ID}/output/final.mp4" in script

    def test_set_euo_pipefail(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "set -euo pipefail" in script


# ── Route: POST /runs/{run_id}/ffmpeg-script ──────────────────────────────────


@pytest.fixture()
def client():
    """TestClient with settings override and no-raise for HTTP error assertions."""
    app.dependency_overrides[get_settings] = lambda: _settings()
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _storyboard_data() -> dict:
    return {
        "global": {"subtitle_style": "bold", "bg_music": "lo-fi", "visual_style": "doc"},
        "scenes": [
            {
                "scene": "01",
                "clip_type": "hard_cut",
                "duration_s": 3.0,
                "voiceover_line": "Line one.",
                "visual_prompts": {
                    "primary_stk": "housing",
                    "fallback_stk": "real estate",
                    "ai_generate": "prompt",
                },
                "motion_effect": None,
                "sfx": "silence",
                "sfx_timing": "scene_start",
            }
        ],
        "summary": {"total_scenes": 1, "total_duration_s": 3.0, "rhythm": "steady"},
    }


def _manifest_data(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "entries": [
            {
                "scene_id": "01",
                "clip_type": "hard_cut",
                "primary_query": "housing",
                "fallback_query": "real estate",
                "ai_generate_prompt": "prompt",
                "status": "acquired",
                "source": "pexels",
                "file_key": f"runs/{run_id}/video/01.mp4",
            }
        ],
    }


class TestFfmpegScriptRoute:
    RUN = "2026-05-22_test-run"

    def test_success_returns_200_with_script_key(self, client):
        with patch("src.routes.ffmpeg_script.R2Client") as MockR2:
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = [
                _storyboard_data(),
                _manifest_data(self.RUN),
                StorageError("no alignment"),
                StorageError("no settings"),
            ]
            resp = client.post(f"/runs/{self.RUN}/ffmpeg-script")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "complete"
        assert body["script_key"] == f"runs/{self.RUN}/ffmpeg_script.sh"

    def test_success_uploads_script_to_r2(self, client):
        with patch("src.routes.ffmpeg_script.R2Client") as MockR2:
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = [
                _storyboard_data(),
                _manifest_data(self.RUN),
                StorageError("no alignment"),
                StorageError("no settings"),
            ]
            client.post(f"/runs/{self.RUN}/ffmpeg-script")

        mock_storage.upload_text.assert_called_once()
        call_args = mock_storage.upload_text.call_args
        assert call_args[0][0] == f"runs/{self.RUN}/ffmpeg_script.sh"
        assert "#!/bin/bash" in call_args[0][1]

    def test_success_updates_run_log_complete(self, client):
        with patch("src.routes.ffmpeg_script.R2Client") as MockR2:
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = [
                _storyboard_data(),
                _manifest_data(self.RUN),
                StorageError("no alignment"),
                StorageError("no settings"),
            ]
            client.post(f"/runs/{self.RUN}/ffmpeg-script")

        mock_storage.update_run_log.assert_called_once_with(
            self.RUN, "ffmpeg_script", "complete",
            output_url=f"runs/{self.RUN}/ffmpeg_script.sh",
        )

    def test_missing_storyboard_returns_404(self, client):
        with patch("src.routes.ffmpeg_script.R2Client") as MockR2:
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = StorageError("not found")
            resp = client.post(f"/runs/{self.RUN}/ffmpeg-script")

        assert resp.status_code == 404
        assert "Storyboard not found" in resp.json()["detail"]

    def test_missing_manifest_returns_404(self, client):
        with patch("src.routes.ffmpeg_script.R2Client") as MockR2:
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = [
                _storyboard_data(),
                StorageError("manifest missing"),
            ]
            resp = client.post(f"/runs/{self.RUN}/ffmpeg-script")

        assert resp.status_code == 404
        assert "Asset manifest not found" in resp.json()["detail"]

    def test_unacquired_scene_returns_422_and_logs_failed(self, client):
        manifest = {
            "run_id": self.RUN,
            "entries": [
                {
                    "scene_id": "01",
                    "clip_type": "hard_cut",
                    "primary_query": "q",
                    "fallback_query": "f",
                    "ai_generate_prompt": "p",
                    "status": "pending",
                    "source": None,
                    "file_key": None,
                }
            ],
        }
        with patch("src.routes.ffmpeg_script.R2Client") as MockR2:
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = [
                _storyboard_data(), manifest, StorageError("no alignment"), StorageError("no settings")
            ]
            resp = client.post(f"/runs/{self.RUN}/ffmpeg-script")

        assert resp.status_code == 422
        assert "01" in resp.json()["detail"]
        mock_storage.update_run_log.assert_called_once_with(
            self.RUN, "ffmpeg_script", "failed", error=mock_storage.update_run_log.call_args[1]["error"]
        )

    def test_r2_upload_failure_returns_500_and_logs_failed(self, client):
        with patch("src.routes.ffmpeg_script.R2Client") as MockR2:
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = [
                _storyboard_data(),
                _manifest_data(self.RUN),
                StorageError("no alignment"),
                StorageError("no settings"),
            ]
            mock_storage.upload_text.side_effect = StorageError("R2 down")
            resp = client.post(f"/runs/{self.RUN}/ffmpeg-script")

        assert resp.status_code == 500
        mock_storage.update_run_log.assert_called_once_with(
            self.RUN, "ffmpeg_script", "failed",
            error=mock_storage.update_run_log.call_args[1]["error"],
        )


# ── Unit: get_audio_duration ──────────────────────────────────────────────────


class TestGetAudioDuration:
    FFPROBE_OUTPUT = '{"format": {"duration": "45.123456", "filename": "test.mp3"}}'

    def test_returns_float_duration(self, tmp_path):
        fake_file = tmp_path / "test.mp3"
        fake_file.write_bytes(b"fake")
        with patch("src.ffmpeg_builder.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=self.FFPROBE_OUTPUT, stderr="")
            result = get_audio_duration(fake_file)
        assert result == pytest.approx(45.123456)

    def test_raises_on_nonzero_returncode(self, tmp_path):
        fake_file = tmp_path / "test.mp3"
        fake_file.write_bytes(b"fake")
        with patch("src.ffmpeg_builder.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="ffprobe: error")
            with pytest.raises(FFmpegBuildError, match="ffprobe failed"):
                get_audio_duration(fake_file)

    def test_raises_on_missing_duration_key(self, tmp_path):
        fake_file = tmp_path / "test.mp3"
        fake_file.write_bytes(b"fake")
        with patch("src.ffmpeg_builder.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout='{"format": {}}', stderr="")
            with pytest.raises(FFmpegBuildError, match="Could not parse"):
                get_audio_duration(fake_file)

    def test_raises_on_invalid_json(self, tmp_path):
        fake_file = tmp_path / "test.mp3"
        fake_file.write_bytes(b"fake")
        with patch("src.ffmpeg_builder.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="not json", stderr="")
            with pytest.raises(FFmpegBuildError, match="Could not parse"):
                get_audio_duration(fake_file)

    def test_passes_file_path_to_ffprobe(self, tmp_path):
        fake_file = tmp_path / "voice.mp3"
        fake_file.write_bytes(b"fake")
        with patch("src.ffmpeg_builder.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=self.FFPROBE_OUTPUT, stderr="")
            get_audio_duration(fake_file)
        args = mock_run.call_args[0][0]
        assert str(fake_file) in args
        assert "ffprobe" in args[0]


# ── Unit: redistribute_scene_durations ───────────────────────────────────────


class TestRedistributeSceneDurations:
    def test_total_duration_distributed_proportionally(self):
        # Scene A: 3 words, Scene B: 6 words → 1:2 ratio over 30s → 10s, 20s
        scenes = [
            _scene("01", duration_s=5.0),  # voiceover_line = "Test voiceover line." (3 words)
            _scene("02", duration_s=5.0),  # same default
        ]
        # Override voiceover_line lengths for deterministic test
        scenes[0] = scenes[0].model_copy(update={"voiceover_line": "one two three"})
        scenes[1] = scenes[1].model_copy(update={"voiceover_line": "one two three four five six"})
        result = redistribute_scene_durations(scenes, 30.0)
        assert result[0].duration_s == pytest.approx(10.0, abs=0.05)
        assert result[1].duration_s == pytest.approx(20.0, abs=0.05)

    def test_scene_ids_unchanged(self):
        scenes = [_scene("01"), _scene("02")]
        result = redistribute_scene_durations(scenes, 20.0)
        assert result[0].scene == "01"
        assert result[1].scene == "02"

    def test_clip_type_unchanged(self):
        scenes = [_scene("01", "still_with_motion"), _scene("02", "animated")]
        result = redistribute_scene_durations(scenes, 20.0)
        assert result[0].clip_type == "still_with_motion"
        assert result[1].clip_type == "animated"

    def test_returns_new_instances_not_mutations(self):
        scenes = [_scene("01", duration_s=5.0)]
        result = redistribute_scene_durations(scenes, 10.0)
        assert result[0] is not scenes[0]
        assert scenes[0].duration_s == 5.0  # original unchanged

    def test_minimum_duration_enforced(self):
        # Very short audio over many scenes — each gets at least 0.5s
        scenes = [_scene(str(i)) for i in range(10)]
        result = redistribute_scene_durations(scenes, 2.0)
        for s in result:
            assert s.duration_s >= 0.5

    def test_empty_voiceover_line_gets_weight_one(self):
        scenes = [
            _scene("01"),
            _scene("02"),
        ]
        scenes[0] = scenes[0].model_copy(update={"voiceover_line": ""})
        scenes[1] = scenes[1].model_copy(update={"voiceover_line": "a b c"})
        result = redistribute_scene_durations(scenes, 40.0)
        # Empty line → weight 1, "a b c" → weight 3 → 10s and 30s
        assert result[0].duration_s == pytest.approx(10.0, abs=0.05)
        assert result[1].duration_s == pytest.approx(30.0, abs=0.05)

    def test_single_scene_gets_full_audio_duration(self):
        scenes = [_scene("01", duration_s=5.0)]
        result = redistribute_scene_durations(scenes, 42.0)
        assert result[0].duration_s == pytest.approx(42.0, abs=0.05)


# ── Unit: assign_words_to_scenes ─────────────────────────────────────────────


def _wts(word: str, start_ms: int, end_ms: int) -> WordTimestamp:
    return WordTimestamp(word=word, start_ms=start_ms, end_ms=end_ms, confidence=0.99)


def _scene_with_vo(scene_id: str, voiceover_line: str, duration_s: float = 3.0) -> StoryboardScene:
    s = _scene(scene_id, duration_s=duration_s)
    return s.model_copy(update={"voiceover_line": voiceover_line})


class TestAssignWordsToScenes:
    def test_single_scene_all_words_match(self):
        scenes = [_scene_with_vo("01", "housing costs tripled")]
        words = [_wts("housing", 0, 500), _wts("costs", 600, 900), _wts("tripled", 1000, 1500)]
        result = assign_words_to_scenes(scenes, words)
        assert len(result) == 1
        assert [w.word for w in result[0]] == ["housing", "costs", "tripled"]

    def test_two_scenes_words_partitioned_correctly(self):
        scenes = [
            _scene_with_vo("01", "one interruption"),
            _scene_with_vo("02", "twenty three minutes"),
        ]
        words = [
            _wts("one", 0, 180), _wts("interruption", 250, 780),
            _wts("twenty", 900, 1100), _wts("three", 1150, 1350), _wts("minutes", 1400, 1700),
        ]
        result = assign_words_to_scenes(scenes, words)
        assert [w.word for w in result[0]] == ["one", "interruption"]
        assert [w.word for w in result[1]] == ["twenty", "three", "minutes"]

    def test_punctuation_stripped_for_matching(self):
        scenes = [_scene_with_vo("01", "costs.")]
        words = [_wts("costs", 0, 400)]
        result = assign_words_to_scenes(scenes, words)
        assert len(result[0]) == 1
        assert result[0][0].word == "costs"

    def test_case_insensitive_matching(self):
        scenes = [_scene_with_vo("01", "Housing")]
        words = [_wts("housing", 0, 500)]
        result = assign_words_to_scenes(scenes, words)
        assert len(result[0]) == 1

    def test_unmatched_deepgram_words_skipped(self):
        # Deepgram inserts a filler "um" not in the storyboard
        scenes = [_scene_with_vo("01", "rents rising")]
        words = [_wts("um", 0, 100), _wts("rents", 200, 600), _wts("rising", 700, 1100)]
        result = assign_words_to_scenes(scenes, words)
        assert [w.word for w in result[0]] == ["rents", "rising"]

    def test_scene_with_no_matching_words_returns_empty_list(self):
        scenes = [_scene_with_vo("01", "xyz abc")]
        words = [_wts("housing", 0, 500), _wts("costs", 600, 900)]
        result = assign_words_to_scenes(scenes, words)
        assert result[0] == []

    def test_empty_word_list_returns_empty_lists(self):
        scenes = [_scene_with_vo("01", "housing costs")]
        result = assign_words_to_scenes(scenes, [])
        assert result == [[]]

    def test_empty_scene_list_returns_empty_result(self):
        words = [_wts("housing", 0, 500)]
        result = assign_words_to_scenes([], words)
        assert result == []

    def test_result_length_equals_scene_count(self):
        scenes = [_scene_with_vo("01", "a b"), _scene_with_vo("02", "c d"), _scene_with_vo("03", "e")]
        words = [_wts("a", 0, 100), _wts("b", 200, 300), _wts("c", 400, 500),
                 _wts("d", 600, 700), _wts("e", 800, 900)]
        result = assign_words_to_scenes(scenes, words)
        assert len(result) == 3

    def test_word_objects_are_original_instances(self):
        scenes = [_scene_with_vo("01", "housing")]
        w = _wts("housing", 0, 500)
        result = assign_words_to_scenes(scenes, [w])
        assert result[0][0] is w

    def test_hyphenated_voiceover_word_matched_as_two_tokens(self):
        # "6-minute" in voiceover → split to "6" and "minute" for matching
        scenes = [_scene_with_vo("01", "problems in 6-minute fragments")]
        words = [
            _wts("problems", 0, 400), _wts("in", 500, 600),
            _wts("6", 700, 800), _wts("minute", 850, 1100),
            _wts("fragments", 1200, 1600),
        ]
        result = assign_words_to_scenes(scenes, words)
        assert len(result[0]) == 5  # all 5 Deepgram words matched

    def test_hyphenated_word_preserves_order(self):
        scenes = [_scene_with_vo("01", "six-figure income")]
        words = [_wts("six", 0, 300), _wts("figure", 400, 700), _wts("income", 800, 1200)]
        result = assign_words_to_scenes(scenes, words)
        assert [w.word for w in result[0]] == ["six", "figure", "income"]


# ── Unit: compute_scene_durations_from_alignment ─────────────────────────────


class TestComputeSceneDurationsFromAlignment:
    def test_mid_scene_duration_uses_next_scene_start(self):
        # Scene 1 words start at 0ms; Scene 2 words start at 900ms (includes 120ms pause)
        # Scene 1 duration should be 0.9s, not 0.78s (words-only span)
        scenes = [_scene_with_vo("01", "one interruption", 3.0), _scene_with_vo("02", "next", 3.0)]
        scene_words = [
            [_wts("one", 0, 180), _wts("interruption", 250, 780)],
            [_wts("next", 900, 1200)],
        ]
        result = compute_scene_durations_from_alignment(scenes, scene_words)
        assert result[0].duration_s == pytest.approx(0.9, abs=0.001)

    def test_last_scene_duration_uses_word_span(self):
        # Last scene: words 1000ms–1500ms → duration = 0.5s
        scenes = [_scene_with_vo("01", "final words", 3.0)]
        scene_words = [[_wts("final", 1000, 1250), _wts("words", 1300, 1500)]]
        result = compute_scene_durations_from_alignment(scenes, scene_words)
        assert result[0].duration_s == pytest.approx(0.5, abs=0.001)

    def test_pause_absorbed_into_preceding_scene(self):
        # Scene 1 ends at 780ms but Scene 2 starts at 900ms — 120ms pause goes to Scene 1
        scenes = [_scene_with_vo("01", "a", 3.0), _scene_with_vo("02", "b", 3.0)]
        scene_words = [[_wts("a", 0, 780)], [_wts("b", 900, 1200)]]
        result = compute_scene_durations_from_alignment(scenes, scene_words)
        assert result[0].duration_s == pytest.approx(0.9, abs=0.001)
        # Last scene: word span = 300ms → floored to _MIN_SCENE_DURATION_S (0.5s)
        assert result[1].duration_s == pytest.approx(0.5, abs=0.001)

    def test_scene_with_no_matched_words_keeps_original_duration(self):
        scenes = [_scene_with_vo("01", "unmatched xyz", 5.0)]
        result = compute_scene_durations_from_alignment(scenes, [[]])
        assert result[0].duration_s == 5.0

    def test_minimum_duration_enforced(self):
        # Two scenes very close together → gap rounds to < _MIN_SCENE_DURATION_S
        scenes = [_scene_with_vo("01", "a", 3.0), _scene_with_vo("02", "b", 3.0)]
        scene_words = [[_wts("a", 0, 50)], [_wts("b", 100, 200)]]
        result = compute_scene_durations_from_alignment(scenes, scene_words)
        assert result[0].duration_s >= 0.5

    def test_scene_ids_unchanged(self):
        scenes = [_scene_with_vo("01", "a", 3.0), _scene_with_vo("02", "b", 3.0)]
        scene_words = [[_wts("a", 0, 400)], [_wts("b", 500, 900)]]
        result = compute_scene_durations_from_alignment(scenes, scene_words)
        assert result[0].scene == "01"
        assert result[1].scene == "02"

    def test_returns_new_instances_not_mutations(self):
        scenes = [_scene_with_vo("01", "a", 5.0)]
        result = compute_scene_durations_from_alignment(scenes, [[_wts("a", 0, 300)]])
        assert result[0] is not scenes[0]
        assert scenes[0].duration_s == 5.0


# ── Unit: filter_complex concat replaces concat demuxer ──────────────────────


class TestFilterComplexConcat:
    def test_no_concat_demuxer_in_script(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "-f concat" not in script

    def test_no_concat_txt_in_script(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "concat.txt" not in script

    def test_filter_complex_present(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "-filter_complex" in script

    def test_setpts_reset_per_scene(self):
        scenes = [_scene("01", "hard_cut", 3.0), _scene("02", "hard_cut", 4.0)]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut"), _entry("02", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "[0:v]setpts=PTS-STARTPTS[v0]" in script
        assert "[1:v]setpts=PTS-STARTPTS[v1]" in script

    def test_concat_filter_uses_correct_scene_count(self):
        scenes = [_scene("01", "hard_cut", 3.0), _scene("02", "hard_cut", 4.0), _scene("03", "hard_cut", 2.0)]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut"), _entry("02", "hard_cut"), _entry("03", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "concat=n=3" in script

    def test_all_scene_files_are_inputs_to_concat(self):
        scenes = [_scene("01", "hard_cut", 3.0), _scene("02", "still_with_motion", 4.0)]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut"), _entry("02", "still_with_motion")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        concat_section = script[script.index("no concat demuxer"):]
        assert "scene_01.mp4" in concat_section
        assert "scene_02.mp4" in concat_section

    def test_output_mapped_from_vout(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert '-map "[vout]"' in script

    def test_filter_complex_count_matches_manifest_entries_not_storyboard_total(self):
        # Storyboard summary claims 3 scenes but manifest has 2 entries.
        # concat=n= must reflect the 2 manifest entries, not the stale summary value.
        scenes = [_scene("01", "hard_cut", 3.0), _scene("02", "hard_cut", 3.0)]
        sb = Storyboard(**{
            "global": StoryboardGlobal(subtitle_style="bold", bg_music="lo-fi", visual_style="doc"),
            "scenes": scenes,
            "summary": StoryboardSummary(total_scenes=3, total_duration_s=6.0, rhythm="steady"),
        })
        mf = _manifest([_entry("01", "hard_cut"), _entry("02", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "concat=n=2" in script
        assert "concat=n=3" not in script


# ── Route: voiceover pacing calibration ──────────────────────────────────────


class TestFfmpegScriptRouteVoiceover:
    RUN = "2026-05-22_test-run"

    def test_voiceover_found_redistributes_durations(self, client):
        """When voiceover exists and no alignment.json, scene durations are redistributed."""
        with (
            patch("src.routes.ffmpeg_script.R2Client") as MockR2,
            patch("src.routes.ffmpeg_script.get_audio_duration", return_value=20.0) as mock_dur,
        ):
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = [
                _storyboard_data(),
                _manifest_data(self.RUN),
                StorageError("no alignment"),
                StorageError("no settings"),
            ]
            mock_storage.list_keys.return_value = [f"runs/{self.RUN}/voiceover/voice.mp3"]
            mock_storage.get_bytes.return_value = b"fake-audio"
            resp = client.post(f"/runs/{self.RUN}/ffmpeg-script")

        assert resp.status_code == 200
        mock_dur.assert_called_once()
        # Single scene → full 20s after redistribution
        uploaded_script = mock_storage.upload_text.call_args[0][1]
        assert "-t 20.0" in uploaded_script

    def test_no_voiceover_uses_storyboard_durations(self, client):
        """When no voiceover is in R2, original storyboard durations are used unchanged."""
        with (
            patch("src.routes.ffmpeg_script.R2Client") as MockR2,
            patch("src.routes.ffmpeg_script.get_audio_duration") as mock_dur,
        ):
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = [
                _storyboard_data(),
                _manifest_data(self.RUN),
                StorageError("no alignment"),
                StorageError("no settings"),
            ]
            mock_storage.list_keys.return_value = []
            resp = client.post(f"/runs/{self.RUN}/ffmpeg-script")

        assert resp.status_code == 200
        mock_dur.assert_not_called()
        uploaded_script = mock_storage.upload_text.call_args[0][1]
        assert "-t 3.0" in uploaded_script  # original storyboard duration unchanged

    def test_alignment_present_skips_redistribution(self, client):
        """When alignment.json is in R2, ffprobe redistribution is skipped entirely."""
        with (
            patch("src.routes.ffmpeg_script.R2Client") as MockR2,
            patch("src.routes.ffmpeg_script.get_audio_duration") as mock_dur,
        ):
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = [
                _storyboard_data(),
                _manifest_data(self.RUN),
                {"run_id": self.RUN, "word_count": 5, "used_fallback": False, "words": []},
                StorageError("no settings"),
            ]
            resp = client.post(f"/runs/{self.RUN}/ffmpeg-script")

        assert resp.status_code == 200
        mock_dur.assert_not_called()
        # Original storyboard duration preserved (3.0s)
        uploaded_script = mock_storage.upload_text.call_args[0][1]
        assert "-t 3.0" in uploaded_script

    def test_alignment_words_produce_word_synced_captions(self, client):
        """When alignment.json has words matching voiceover_line, script has word-synced captions."""
        # Storyboard voiceover_line must contain words that match the alignment data.
        # _storyboard_data() has voiceover_line="Line one." which won't match "housing" etc.
        # Use a variant where the voiceover matches the alignment words.
        storyboard = _storyboard_data()
        storyboard["scenes"][0]["voiceover_line"] = "housing costs tripled"
        alignment = {
            "run_id": self.RUN,
            "word_count": 3,
            "used_fallback": False,
            "words": [
                {"word": "housing", "start_ms": 0, "end_ms": 500, "confidence": 0.99},
                {"word": "costs", "start_ms": 600, "end_ms": 900, "confidence": 0.99},
                {"word": "tripled", "start_ms": 1000, "end_ms": 1500, "confidence": 0.99},
            ],
        }
        with patch("src.routes.ffmpeg_script.R2Client") as MockR2:
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = [
                storyboard, _manifest_data(self.RUN), alignment, StorageError("no settings")
            ]
            resp = client.post(f"/runs/{self.RUN}/ffmpeg-script")

        assert resp.status_code == 200
        uploaded_script = mock_storage.upload_text.call_args[0][1]
        assert "housing" in uploaded_script
        assert "costs" in uploaded_script
        assert "tripled" in uploaded_script
        assert "{\\c&H0000FFFF&}" in uploaded_script


# ── Unit: captions integration in build_ffmpeg_script ────────────────────────


class TestCaptionsInScript:
    """Verify voiceover captions write and burn steps are wired into the generated script.

    On-screen text overlay (_write_captions_ass / _burn_captions) is intentionally
    unwired — __ASS_EOF__ and captions.ass are NOT expected in the generated script.
    Chain: video_only.mp4 → voiceover captions → video_captioned.mp4 → audio → final.mp4
    """

    def test_script_contains_voiceover_captions_ass_write(self):
        scenes = [_scene("01", "hard_cut", 3.0)]
        script = build_ffmpeg_script(RUN_ID, _storyboard(scenes), _manifest([_entry("01", "hard_cut")]))
        assert "voiceover_captions.ass" in script
        assert "'__VCAP_EOF__'" in script

    def test_on_screen_captions_ass_not_in_script(self):
        # on-screen overlay is unwired — captions.ass and __ASS_EOF__ must not appear
        scenes = [_scene("01", "hard_cut", 3.0)]
        script = build_ffmpeg_script(RUN_ID, _storyboard(scenes), _manifest([_entry("01", "hard_cut")]))
        assert "__ASS_EOF__" not in script
        # "captions.ass" must not appear standalone (voiceover_captions.ass is still present)
        assert '"$WORK/captions.ass"' not in script

    def test_script_contains_burn_voiceover_captions_step(self):
        scenes = [_scene("01", "hard_cut", 3.0)]
        script = build_ffmpeg_script(RUN_ID, _storyboard(scenes), _manifest([_entry("01", "hard_cut")]))
        assert "video_captioned.mp4" in script
        assert 'vf "ass=' in script

    def test_voiceover_captions_burn_reads_from_video_only(self):
        # Single caption pass: video_only.mp4 → video_captioned.mp4
        scenes = [_scene("01", "hard_cut", 3.0)]
        script = build_ffmpeg_script(RUN_ID, _storyboard(scenes), _manifest([_entry("01", "hard_cut")]))
        vcap_block_start = script.index("# ── Burn voiceover captions")
        vcap_block_end = script.index("video_captioned.mp4") + len("video_captioned.mp4")
        vcap_block = script[vcap_block_start:vcap_block_end]
        assert "video_only.mp4" in vcap_block
        assert "video_captioned2.mp4" not in script

    def test_audio_section_reads_from_captioned_video(self):
        # Audio mix must read video_captioned.mp4 (only caption pass output)
        scenes = [_scene("01", "hard_cut", 3.0)]
        script = build_ffmpeg_script(RUN_ID, _storyboard(scenes), _manifest([_entry("01", "hard_cut")]))
        audio_block_start = script.rfind("# ── Audio assembly")
        assert audio_block_start != -1
        audio_block = script[audio_block_start:]
        assert "video_captioned.mp4" in audio_block
        assert "video_captioned2.mp4" not in audio_block
        assert "video_only.mp4" not in audio_block

    def test_caption_chain_ordering(self):
        # voiceover write → voiceover burn → audio (no on-screen write/burn steps)
        scenes = [_scene("01", "hard_cut", 3.0)]
        script = build_ffmpeg_script(RUN_ID, _storyboard(scenes), _manifest([_entry("01", "hard_cut")]))
        pos_vcap_write = script.index("__VCAP_EOF__")
        pos_captioned = script.index("video_captioned.mp4")
        pos_audio = script.index("# ── Audio assembly")
        assert pos_vcap_write < pos_captioned < pos_audio

    def test_voiceover_line_not_uppercased_in_script(self):
        scenes = [_scene("01", "hard_cut", 3.0)]
        scenes[0] = scenes[0].model_copy(update={"voiceover_line": "rents are rising fast"})
        script = build_ffmpeg_script(RUN_ID, _storyboard(scenes), _manifest([_entry("01", "hard_cut")]))
        assert "rents are rising fast" in script
        assert "RENTS ARE RISING FAST" not in script

    def test_word_synced_captions_used_when_scene_words_provided(self):
        """When scene_words supplied, caption text comes from word list not voiceover_line."""
        sb, mf = _simple_storyboard_and_manifest()
        sw = [[WordTimestamp(word="crisis", start_ms=0, end_ms=600, confidence=0.99)]]
        script = build_ffmpeg_script(RUN_ID, sb, mf, scene_words=sw)
        assert "crisis" in script
        assert "{\\c&H0000FFFF&}crisis" in script

    def test_no_scene_words_falls_back_to_scene_boundary_captions(self):
        """Without scene_words, captions use voiceover_line from scenes."""
        scenes = [_scene("01", "hard_cut", 3.0)]
        scenes[0] = scenes[0].model_copy(update={"voiceover_line": "rents are soaring high"})
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "rents are soaring high" in script
        assert "{\\c&H0000FFFF&}" not in script

    def test_none_scene_words_falls_back_to_scene_boundary_captions(self):
        """Explicit None uses scene-boundary captions."""
        scenes = [_scene("01", "hard_cut", 3.0)]
        scenes[0] = scenes[0].model_copy(update={"voiceover_line": "unique fallback line"})
        sb = _storyboard(scenes)
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf, scene_words=None)
        assert "unique fallback line" in script


# ── Unit: audio settings (volume, ducking, playback mode) ────────────────────


class TestAudioSettings:
    """Verify music volume, ducking factor, and loop/fit mode are applied to the generated script."""

    def _make_script(self, audio: AudioSettings) -> str:
        """Build a minimal one-scene script with the given audio settings."""
        scenes = [_scene("01", "hard_cut", 3.0)]
        return build_ffmpeg_script(
            RUN_ID,
            _storyboard(scenes),
            _manifest([_entry("01", "hard_cut")]),
            audio=audio,
        )

    def test_default_audio_applies_ducking_to_fifteen_percent(self):
        """AudioSettings(): 15% volume × 0.4 ducking factor = 0.060 effective."""
        script = self._make_script(AudioSettings())
        assert "volume=0.060[music]" in script

    def test_custom_volume_ducking_off(self):
        """Ducking OFF: configured volume applied directly with no reduction."""
        script = self._make_script(AudioSettings(music_volume=40, ducking_enabled=False))
        assert "volume=0.400[music]" in script

    def test_custom_volume_ducking_on(self):
        """Ducking ON: 40% × _DUCKING_FACTOR (0.4) = 0.160 effective volume."""
        script = self._make_script(AudioSettings(music_volume=40, ducking_enabled=True))
        assert "volume=0.160[music]" in script

    def test_zero_volume_produces_zero_filter(self):
        """Volume slider at 0% → volume=0.000 regardless of ducking."""
        script = self._make_script(AudioSettings(music_volume=0, ducking_enabled=False))
        assert "volume=0.000[music]" in script

    def test_full_volume_ducking_off(self):
        """100% volume with ducking OFF → volume=1.000."""
        script = self._make_script(AudioSettings(music_volume=100, ducking_enabled=False))
        assert "volume=1.000[music]" in script

    def test_loop_mode_sets_stream_loop_flag(self):
        """Loop mode adds -stream_loop -1 before the music file input."""
        script = self._make_script(AudioSettings(playback_mode="loop"))
        music_start = script.index("# ── Background music")
        music_section = script[music_start:music_start + 500]
        assert "-stream_loop -1" in music_section

    def test_fit_mode_no_stream_loop_flag(self):
        """Fit mode (default) does not add -stream_loop to MUSIC_ARGS."""
        script = self._make_script(AudioSettings(playback_mode="fit"))
        assert "-stream_loop" not in script

    def test_none_audio_uses_same_defaults_as_audio_settings(self):
        """Omitting audio= produces identical filter output to AudioSettings()."""
        scenes = [_scene("01", "hard_cut", 3.0)]
        sb, mf = _storyboard(scenes), _manifest([_entry("01", "hard_cut")])
        script_none = build_ffmpeg_script(RUN_ID, sb, mf, audio=None)
        assert "volume=0.060[music]" in script_none

    def test_voiceover_volume_unchanged(self):
        """VO volume is always 1.0 regardless of audio settings."""
        script = self._make_script(AudioSettings(music_volume=80, ducking_enabled=False))
        assert "volume=1.0[vo]" in script


# ── Route: audio settings loaded from R2 ─────────────────────────────────────


class TestFfmpegScriptRouteAudioSettings:
    """Verify the route loads settings.json and passes audio to the script builder."""

    RUN = "2026-05-22_test-run"

    def _settings_json(self, music_volume: int = 40, ducking_enabled: bool = False) -> dict:
        return {
            "aspect_ratio": "9:16",
            "visual_style": "Realistic",
            "subtitles_enabled": True,
            "subtitle_style": "TikTok",
            "audio": {
                "music_volume": music_volume,
                "ducking_enabled": ducking_enabled,
                "playback_mode": "fit",
            },
        }

    def test_audio_settings_applied_when_settings_json_present(self, client):
        """When settings.json exists, configured volume replaces defaults in the script."""
        with patch("src.routes.ffmpeg_script.R2Client") as MockR2:
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = [
                _storyboard_data(),
                _manifest_data(self.RUN),
                StorageError("no alignment"),
                self._settings_json(music_volume=40, ducking_enabled=False),
            ]
            client.post(f"/runs/{self.RUN}/ffmpeg-script")

        uploaded_script = mock_storage.upload_text.call_args[0][1]
        assert "volume=0.400[music]" in uploaded_script

    def test_default_audio_used_when_settings_json_missing(self, client):
        """When settings.json is absent, AudioSettings() defaults apply (0.060 effective)."""
        with patch("src.routes.ffmpeg_script.R2Client") as MockR2:
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = [
                _storyboard_data(),
                _manifest_data(self.RUN),
                StorageError("no alignment"),
                StorageError("no settings"),
            ]
            client.post(f"/runs/{self.RUN}/ffmpeg-script")

        uploaded_script = mock_storage.upload_text.call_args[0][1]
        assert "volume=0.060[music]" in uploaded_script


# ── Unit: aspect ratio dimensions ────────────────────────────────────────────


class TestAspectRatioDimensions:
    """Verify build_ffmpeg_script uses the correct output dimensions per aspect_ratio."""

    def _script(self, aspect_ratio: str) -> str:
        vs = VideoSettings(aspect_ratio=aspect_ratio)
        sb = _storyboard([_scene("01", "hard_cut")])
        mf = _manifest([_entry("01", "hard_cut")])
        return build_ffmpeg_script(RUN_ID, sb, mf, video_settings=vs)

    def test_9_16_produces_1080x1920(self):
        """Default 9:16 aspect ratio produces 1080×1920 scale/crop in scene commands."""
        script = self._script("9:16")
        assert "scale=1080:1920" in script
        assert "crop=1080:1920" in script

    def test_16_9_produces_1920x1080(self):
        """16:9 aspect ratio produces 1920×1080 scale/crop in scene commands."""
        script = self._script("16:9")
        assert "scale=1920:1080" in script
        assert "crop=1920:1080" in script

    def test_1_1_produces_1080x1080(self):
        """1:1 aspect ratio produces 1080×1080 scale/crop in scene commands."""
        script = self._script("1:1")
        assert "scale=1080:1080" in script
        assert "crop=1080:1080" in script

    def test_9_16_is_default_when_no_video_settings(self):
        """Omitting video_settings defaults to 9:16 (1080×1920)."""
        sb = _storyboard([_scene("01", "hard_cut")])
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "scale=1080:1920" in script

    def test_16_9_zoompan_uses_correct_dimensions(self):
        """16:9 image scenes use 1920×1080 in the zoompan s= parameter."""
        vs = VideoSettings(aspect_ratio="16:9")
        sb = _storyboard([_scene("01", "still_with_motion")])
        mf = _manifest([_entry("01", "still_with_motion")])
        script = build_ffmpeg_script(RUN_ID, sb, mf, video_settings=vs)
        assert "s=1920x1080" in script


# ── Unit: subtitles setting ───────────────────────────────────────────────────


class TestSubtitlesSetting:
    """Verify subtitles='none' skips caption burn and routes audio correctly."""

    def test_subtitles_none_omits_vcap_heredoc(self):
        """subtitles='none' produces a script without the voiceover_captions.ass heredoc."""
        vs = VideoSettings(subtitles="none")
        scenes = [_scene("01", "hard_cut")]
        sb = _storyboard(scenes)
        sb = sb.model_copy(update={"scenes": [
            scenes[0].model_copy(update={"voiceover_line": "Some text here."})
        ]})
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf, video_settings=vs)
        assert "__VCAP_EOF__" not in script

    def test_subtitles_none_audio_reads_from_video_only(self):
        """subtitles='none' routes audio assembly to video_only.mp4, not video_captioned.mp4."""
        vs = VideoSettings(subtitles="none")
        sb = _storyboard([_scene("01", "hard_cut")])
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf, video_settings=vs)
        assert '"$WORK/video_only.mp4"' in script
        assert '"$WORK/video_captioned.mp4"' not in script

    def test_subtitles_tiktok_includes_vcap_heredoc(self):
        """subtitles='TikTok' (default) produces the voiceover captions heredoc."""
        vs = VideoSettings(subtitles="TikTok")
        sb = _storyboard([_scene("01", "hard_cut")])
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf, video_settings=vs)
        assert "__VCAP_EOF__" in script
        assert '"$WORK/video_captioned.mp4"' in script

    def test_subtitles_classic_includes_vcap_heredoc(self):
        """subtitles='Classic' also produces the voiceover captions heredoc."""
        vs = VideoSettings(subtitles="Classic")
        sb = _storyboard([_scene("01", "hard_cut")])
        mf = _manifest([_entry("01", "hard_cut")])
        script = build_ffmpeg_script(RUN_ID, sb, mf, video_settings=vs)
        assert "__VCAP_EOF__" in script
