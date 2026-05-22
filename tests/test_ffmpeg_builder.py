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
    build_ffmpeg_script,
)
from src.main import app
from src.models import (
    AssetManifest,
    ManifestEntry,
    Storyboard,
    StoryboardGlobal,
    StoryboardScene,
    StoryboardSummary,
    VisualPrompts,
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
        assert "fps=25" in result

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

    def test_animated_pan_left_uses_pan_expression(self):
        scenes = [_scene("03", "animated", 3.0, motion_effect="pan_left")]
        sb = _storyboard(scenes)
        mf = _manifest([_entry("03", "animated")])
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "(iw-iw/zoom)*on/" in script

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

    def test_music_silence_fallback_generated(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "_silence.mp3" in script
        assert "anullsrc" in script

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

    def test_music_volume_is_fifteen_percent(self):
        sb, mf = _simple_storyboard_and_manifest()
        script = build_ffmpeg_script(RUN_ID, sb, mf)
        assert "volume=0.15" in script

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
            mock_storage.get_json.side_effect = [_storyboard_data(), manifest]
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
            ]
            mock_storage.upload_text.side_effect = StorageError("R2 down")
            resp = client.post(f"/runs/{self.RUN}/ffmpeg-script")

        assert resp.status_code == 500
        mock_storage.update_run_log.assert_called_once_with(
            self.RUN, "ffmpeg_script", "failed",
            error=mock_storage.update_run_log.call_args[1]["error"],
        )
